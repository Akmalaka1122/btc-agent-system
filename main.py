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
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from core.orchestrator import Orchestrator
from core.data.binance_client import BinanceClient
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
# Shutdown
# ─────────────────────────────────────────────
shutdown_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.info(f"Received signal {sig}, shutting down...")
    shutdown_event.set()


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


# ─────────────────────────────────────────────
# Pending outcomes (resolve after 5min)
# ─────────────────────────────────────────────
pending_outcomes = []  # List of (cycle_id, entry_price, resolve_after)


async def resolve_pending_outcomes(tracker, generator):
    """Check and resolve outcomes whose 5-minute window has passed."""
    now = datetime.now(timezone.utc)
    resolved_count = 0
    
    still_pending = []
    for pending in pending_outcomes:
        cycle_id, entry_price, resolve_after = pending
        
        if now >= resolve_after:
            try:
                # Fetch current price for outcome resolution
                from core.data.binance_client import BinanceClient as BC
                client = BC(timeout=10.0)
                try:
                    current_price = await client.get_price("BTCUSDT")
                finally:
                    await client.close()
                
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
    
    return resolved_count


# ─────────────────────────────────────────────
# Scheduler loop
# ─────────────────────────────────────────────
async def scheduler_loop(orchestrator, app):
    """Run trading cycles on interval."""
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
            
            # Track outcome for non-SKIP decisions
            if log.final_decision and log.final_decision.rating.value != "SKIP":
                try:
                    from core.data.binance_client import BinanceClient as BC2
                    _bc = BC2(timeout=10.0)
                    try:
                        entry_price = await _bc.get_price("BTCUSDT")
                    finally:
                        await _bc.close()
                    
                    # Resolve after CYCLE_INTERVAL seconds
                    resolve_after = datetime.now(timezone.utc)
                    from datetime import timedelta
                    resolve_after += timedelta(seconds=CYCLE_INTERVAL)
                    
                    pending_outcomes.append((log.cycle_id, entry_price, resolve_after))
                    logger.info(
                        f"Tracking outcome: {log.cycle_id} "
                        f"{log.final_decision.rating.value} "
                        f"@ ${entry_price:,.2f} "
                        f"(resolve in {CYCLE_INTERVAL}s)"
                    )
                except Exception as e:
                    logger.warning(f"Outcome tracking failed: {e}")
            
            # Resolve any pending outcomes
            resolved = await resolve_pending_outcomes(tracker, generator)
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
    logger.info("=" * 60)
    logger.info("BTC AGENT SYSTEM — PAPER TRADING MODE")
    logger.info("=" * 60)
    logger.info(f"Cycle interval: {CYCLE_INTERVAL}s ({CYCLE_INTERVAL//60}min)")
    logger.info(f"Log dir: {LOG_DIR}")
    
    # Initialize data client
    binance = BinanceClient(timeout=15.0)
    logger.info("✅ Binance client initialized")
    
    # Initialize orchestrator
    orchestrator = Orchestrator(
        binance_client=binance,
        polymarket_client=None,
        liquidation_tracker=None,
        database=None,
    )
    logger.info("✅ Orchestrator initialized (5 agents)")
    
    # Initialize decision log
    dl = get_decision_log()
    recent = dl.get_recent(limit=1)
    logger.info(f"✅ Decision log: {len(dl.get_recent(limit=100))} entries")
    
    # Initialize self-correction
    tracker = get_outcome_tracker()
    stats = tracker.get_stats()
    logger.info(f"✅ Outcome tracker: {stats['total_trades']} resolved, {stats['unresolved']} pending")
    
    # Build Telegram bot
    app = build_app(orchestrator)
    me = await app.bot.get_me()
    logger.info(f"✅ Telegram bot: @{me.username} (ID: {me.id})")
    logger.info(f"✅ Admin: {os.getenv('TELEGRAM_ADMIN_IDS')}")
    logger.info(f"✅ Chat: {os.getenv('TELEGRAM_CHAT_ID')}")
    
    # Startup notification
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        try:
            startup_msg = (
                f"🚀 **Paper Trading Started**\n\n"
                f"⏰ Interval: {CYCLE_INTERVAL}s ({CYCLE_INTERVAL//60}min)\n"
                f"📊 History: {stats['total_trades']} trades\n"
                f"📈 Win rate: {stats['win_rate']:.1%}\n"
                f"💰 PnL: ${stats['total_pnl']:+,.2f}\n\n"
                f"Commands: /status /run /pause /resume\n"
                f"Chat: \"why skip?\" / \"summary\" / \"show losses\""
            )
            await app.bot.send_message(
                chat_id=chat_id, text=startup_msg, parse_mode="Markdown"
            )
            logger.info("✅ Startup notification sent")
        except Exception as e:
            logger.warning(f"Startup notification failed: {e}")
    
    # Start bot + scheduler
    logger.info("🟢 Starting bot polling + scheduler...")
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        
        # Run scheduler in background
        scheduler_task = asyncio.create_task(scheduler_loop(orchestrator, app))
        
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
            logger.info("✅ Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
