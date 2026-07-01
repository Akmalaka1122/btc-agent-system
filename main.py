"""
main.py — Paper Trading Bot with Telegram Gateway.

Runs 24/7:
1. Telegram bot polling (commands + conversational)
2. Scheduler loop (run_cycle every CYCLE_INTERVAL_SECONDS)
3. After each cycle: broadcast to Telegram + log decision
4. Outcome tracking: resolve previous cycle after 5min window
5. Self-correction: lessons injected into future cycles

Usage:
    python main.py
"""
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

from core.orchestrator import Orchestrator
from core.data.binance_client import BinanceClient
from core.data.polymarket_client import PolymarketClient
from core.data.db import Database
from core.decision_log import get_decision_log
from core.self_correction import get_outcome_tracker, get_lesson_generator
from telegram_bot.bot import build_app, STATE, broadcast_cycle, format_cycle_message

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
load_dotenv()

CYCLE_INTERVAL = int(os.getenv("CYCLE_INTERVAL_SECONDS", "300"))
LOG_DIR = Path.home() / ".hermes" / "btc-agent-system"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PENDING_FILE = LOG_DIR / "pending_outcomes.json"

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "paper_trading.log"),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("paper_trading")

# ─────────────────────────────────────────────
# Env validation
# ─────────────────────────────────────────────
REQUIRED_ENV = {
    "LLM_API_KEY": "LLM API key for agent calls",
    "TELEGRAM_BOT_TOKEN": "Telegram bot token",
    "TELEGRAM_CHAT_ID": "Telegram chat ID for broadcasts",
}

OPTIONAL_ENV = {
    "LLM_PROVIDER": "LLM provider (default: openai)",
    "LLM_MODEL": "LLM model name",
    "POLYMARKET_TOKEN_ID": "Polymarket YES/UP token ID for BTC 5m market",
}


def validate_env() -> list[str]:
    """Check required env vars. Returns list of missing keys."""
    missing = []
    for key, desc in REQUIRED_ENV.items():
        val = os.getenv(key)
        if not val or val.strip() == "":
            missing.append(f"{key} ({desc})")
        elif key == "CYCLE_INTERVAL_SECONDS":
            try:
                v = int(val)
                if v < 30:
                    logger.warning(f"CYCLE_INTERVAL_SECONDS={v} is very low (<30s), may hit rate limits")
            except ValueError:
                missing.append(f"{key} (must be integer)")
    return missing


# ─────────────────────────────────────────────
# Shutdown
# ─────────────────────────────────────────────
shutdown_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.info(f"Received signal {sig}, shutting down...")
    shutdown_event.set()


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ─────────────────────────────────────────────
# Pending outcomes persistence
# ─────────────────────────────────────────────
pending_outcomes = []  # List of (cycle_id, entry_price, resolve_after_iso)
_consecutive_failures = 0  # Track consecutive cycle failures for alerting


def save_pending_outcomes():
    """Persist pending_outcomes to JSON so they survive restarts."""
    try:
        data = [
            {"cycle_id": cid, "entry_price": ep, "resolve_after": ra.isoformat() if isinstance(ra, datetime) else ra}
            for cid, ep, ra in pending_outcomes
        ]
        with open(PENDING_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save pending outcomes: {e}")


def load_pending_outcomes():
    """Reload pending_outcomes from JSON on startup."""
    global pending_outcomes
    if not PENDING_FILE.exists():
        return
    try:
        with open(PENDING_FILE, "r") as f:
            data = json.load(f)
        pending_outcomes = [
            (d["cycle_id"], d["entry_price"], datetime.fromisoformat(d["resolve_after"]))
            for d in data
        ]
        # Filter out already-expired entries (resolve immediately)
        now = datetime.now(timezone.utc)
        expired = [p for p in pending_outcomes if p[2] <= now]
        if expired:
            logger.info(f"Loaded {len(pending_outcomes)} pending outcomes ({len(expired)} expired, will resolve ASAP)")
        else:
            logger.info(f"Loaded {len(pending_outcomes)} pending outcomes from disk")
    except Exception as e:
        logger.warning(f"Failed to load pending outcomes: {e}")
        pending_outcomes = []


async def resolve_pending_outcomes(tracker, generator, binance_client):
    """Check and resolve outcomes whose 5-minute window has passed.
    Reuses the shared binance_client instead of creating new ones."""
    now = datetime.now(timezone.utc)
    resolved_count = 0

    still_pending = []
    for pending in pending_outcomes:
        cycle_id, entry_price, resolve_after = pending

        if now >= resolve_after:
            try:
                current_price = await binance_client.get_price("BTCUSDT")

                outcome = tracker.resolve_outcome(cycle_id, current_price)
                if outcome:
                    lesson = generator.generate_lesson(outcome)
                    resolved_count += 1

                    emoji = "✅" if outcome["win"] else "❌"
                    logger.info(
                        f"Outcome resolved: {cycle_id} "
                        f"{emoji} {'WIN' if outcome['win'] else 'LOSS'} "
                        f"({outcome['actual_move_pct']:+.3f}%) "
                        f"PnL: ${outcome['pnl_usd']:+.2f} "
                        f"Lesson: {lesson['category']}"
                    )
            except Exception as e:
                logger.warning(f"Failed to resolve outcome {cycle_id}: {e}")
                still_pending.append(pending)
        else:
            still_pending.append(pending)

    pending_outcomes.clear()
    pending_outcomes.extend(still_pending)

    # Persist after resolve (so resolved items are removed from disk)
    save_pending_outcomes()

    return resolved_count


# ─────────────────────────────────────────────
# Scheduler loop
# ─────────────────────────────────────────────
async def scheduler_loop(orchestrator, app, binance_client):
    """Run trading cycles on interval."""
    global _consecutive_failures
    logger.info(f"⏰ Scheduler started (interval: {CYCLE_INTERVAL}s)")

    tracker = get_outcome_tracker()
    generator = get_lesson_generator()
    cycle_count = 0

    while not shutdown_event.is_set():
        if not STATE["running"]:
            logger.info("⏸ System PAUSED, waiting...")
            await asyncio.sleep(10)
            continue

        cycle_count += 1
        logger.info(f"{'='*60}")
        logger.info(f"CYCLE #{cycle_count} STARTING")
        logger.info(f"{'='*60}")

        try:
            # Run orchestrator cycle
            log = await orchestrator.run_cycle()

            # Record in STATE
            STATE["last_cycle"] = log
            STATE["history"].append(log)
            if len(STATE["history"]) > 20:
                STATE["history"].pop(0)

            # Broadcast to Telegram
            try:
                await broadcast_cycle(app, log)
            except Exception as e:
                logger.warning(f"Telegram broadcast failed: {e}")
                # Retry once after 2s
                try:
                    await asyncio.sleep(2)
                    await broadcast_cycle(app, log)
                    logger.info("Telegram broadcast retry succeeded")
                except Exception:
                    logger.error("Telegram broadcast retry also failed — user has no notification")

            # Track outcome for non-SKIP decisions
            if log.final_decision and log.final_decision.rating.value != "SKIP":
                try:
                    entry_price = await binance_client.get_price("BTCUSDT")

                    # Validate price before tracking (skip on bad data)
                    if not entry_price or entry_price <= 0:
                        logger.warning(
                            f"Skipping outcome tracking for {log.cycle_id}: "
                            f"invalid entry_price={entry_price}"
                        )
                    else:
                        # Persist entry to outcomes.json (so resolve_outcome finds it)
                        d = log.final_decision
                        tracker.record_entry(
                            cycle_id=log.cycle_id,
                            decision=d.rating.value,
                            confidence=d.confidence,
                            entry_price=entry_price,
                            confluence=getattr(d, "confluence_total", 0) or 0,
                            setup_match=getattr(d, "setup_match", "none") or "none",
                            reasoning=getattr(d, "reasoning", "") or "",
                            position_size_usd=d.position_size_usd,
                        )

                        # Resolve after CYCLE_INTERVAL seconds
                        resolve_after = datetime.now(timezone.utc) + timedelta(seconds=CYCLE_INTERVAL)

                        pending_outcomes.append((log.cycle_id, entry_price, resolve_after))
                        save_pending_outcomes()
                        logger.info(
                            f"Tracking outcome: {log.cycle_id} "
                            f"{log.final_decision.rating.value} "
                            f"@ ${entry_price:,.2f} "
                            f"(resolve in {CYCLE_INTERVAL}s)"
                        )
                except Exception as e:
                    logger.warning(f"Outcome tracking failed: {e}")

            # Resolve any pending outcomes
            resolved = await resolve_pending_outcomes(tracker, generator, binance_client)
            if resolved:
                logger.info(f"📊 Resolved {resolved} pending outcomes")

            # Log cycle summary
            if log.final_decision:
                d = log.final_decision
                logger.info(
                    f"Decision: {d.rating.value} | "
                    f"Confidence: {d.confidence}/10 | "
                    f"Position: ${d.position_size_usd:.2f} | "
                    f"Latency: {log.latency_seconds.get('total', 0):.1f}s"
                )
            else:
                logger.info(f"Decision: SKIP ({log.error})")

            stats = tracker.get_stats()
            logger.info(
                f"Stats: {stats['total_trades']} trades | "
                f"Win rate: {stats['win_rate']:.1%} | "
                f"PnL: ${stats['total_pnl']:+,.2f} | "
                f"Unresolved: {stats['unresolved']}"
            )

        except Exception as e:
            logger.error(f"Cycle {cycle_count} failed: {e}", exc_info=True)
            _consecutive_failures += 1
            if _consecutive_failures >= 3:
                try:
                    chat_id = os.getenv("TELEGRAM_CHAT_ID")
                    if chat_id:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ **ALERT**: {_consecutive_failures} consecutive cycle failures!\n"
                                 f"Last error: `{e}`\nSystem still running but may need attention.",
                            parse_mode="Markdown",
                        )
                except Exception:
                    pass
        else:
            _consecutive_failures = 0  # Reset on success

        # Wait for next cycle (with early exit on shutdown)
        logger.info(f"💤 Next cycle in {CYCLE_INTERVAL}s...")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CYCLE_INTERVAL)
            break  # shutdown_event was set
        except asyncio.TimeoutError:
            pass  # normal — timeout reached, run next cycle

    logger.info("⏰ Scheduler stopped")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    # ── Env validation (fail fast) ──
    missing = validate_env()
    if missing:
        for m in missing:
            logger.error(f"❌ Missing required env var: {m}")
        logger.error("Set these in .env and restart. Exiting.")
        sys.exit(1)

    # Warn on optional env
    for key, desc in OPTIONAL_ENV.items():
        if not os.getenv(key):
            logger.warning(f"Optional env not set: {key} — {desc}")

    logger.info("=" * 60)
    logger.info("BTC AGENT SYSTEM — PAPER TRADING MODE")
    logger.info("=" * 60)
    logger.info(f"Cycle interval: {CYCLE_INTERVAL}s ({CYCLE_INTERVAL//60}min)")
    logger.info(f"Log dir: {LOG_DIR}")

    # Initialize data clients
    binance = BinanceClient(timeout=15.0)
    logger.info("✅ Binance client initialized")

    polymarket = PolymarketClient(timeout=10.0)
    logger.info("✅ Polymarket client initialized")

    # Initialize database (circuit breaker + cycle history)
    db = Database()
    await db.init()
    logger.info("✅ Database initialized (SQLite)")

    # Initialize orchestrator with all clients
    orchestrator = Orchestrator(
        binance_client=binance,
        polymarket_client=polymarket,
        liquidation_tracker=None,
        database=db,
    )
    logger.info("✅ Orchestrator initialized (4 agents + data clients)")

    # Initialize decision log
    dl = get_decision_log()
    recent = dl.get_recent(limit=1)
    logger.info(f"✅ Decision log: {len(dl.get_recent(limit=100))} entries")

    # Initialize self-correction
    tracker = get_outcome_tracker()
    stats = tracker.get_stats()
    logger.info(f"✅ Outcome tracker: {stats['total_trades']} resolved, {stats['unresolved']} pending")

    # Load persisted pending outcomes (survived restart)
    load_pending_outcomes()

    # Build Telegram bot
    app = build_app(orchestrator)
    me = await app.bot.get_me()
    logger.info(f"✅ Telegram bot: @{me.username} (ID: {me.id})")
    logger.info(f"✅ Admin: {os.getenv('TELEGRAM_ADMIN_IDS')}")
    logger.info(f"✅ Chat: {os.getenv('TELEGRAM_CHAT_ID')}")

    # Startup notification
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    startup_msg = (
        f"🚀 **Paper Trading Started**\n\n"
        f"⏰ Interval: {CYCLE_INTERVAL}s ({CYCLE_INTERVAL//60}min)\n"
        f"📊 History: {stats['total_trades']} trades\n"
        f"📈 Win rate: {stats['win_rate']:.1%}\n"
        f"💰 PnL: ${stats['total_pnl']:+,.2f}\n"
        f"⏳ Pending outcomes: {len(pending_outcomes)}\n\n"
        f"Commands: /status /run /pause /resume\n"
        f"Chat: \"why skip?\" / \"summary\" / \"show losses\""
    )
    if chat_id:
        try:
            await app.bot.send_message(
                chat_id=chat_id, text=startup_msg, parse_mode="Markdown"
            )
            logger.info("✅ Startup notification sent")
        except Exception as e:
            logger.warning(f"Startup notification failed: {e}")
            # Retry once
            try:
                await asyncio.sleep(3)
                await app.bot.send_message(chat_id=chat_id, text=startup_msg, parse_mode="Markdown")
                logger.info("✅ Startup notification sent (retry)")
            except Exception:
                logger.error("Startup notification failed twice — continuing without notification")

    # Start bot + scheduler
    logger.info("🟢 Starting bot polling + scheduler...")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        # Run scheduler in background (pass shared binance_client)
        scheduler_task = asyncio.create_task(scheduler_loop(orchestrator, app, binance))

        # Wait for shutdown
        try:
            await shutdown_event.wait()
        finally:
            logger.info("⏹ Shutting down...")
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass

            # Save pending outcomes before exit
            save_pending_outcomes()
            logger.info(f"💾 Saved {len(pending_outcomes)} pending outcomes to disk")

            # Shutdown notification
            if chat_id:
                try:
                    final_stats = tracker.get_stats()
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"⏹ **Paper Trading Stopped**\n\n"
                            f"📊 Trades: {final_stats['total_trades']}\n"
                            f"📈 Win rate: {final_stats['win_rate']:.1%}\n"
                            f"💰 PnL: ${final_stats['total_pnl']:+,.2f}"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            await app.updater.stop()
            await app.stop()
            await binance.close()
            await polymarket.close()
            await db.close()
            logger.info("✅ Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
