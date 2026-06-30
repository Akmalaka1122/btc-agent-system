"""
bot.py — Telegram integration untuk versi minimal (4 agent).
Sama seperti versi penuh, tapi format pesan disesuaikan field CycleLog yang baru.
"""
import asyncio
import os
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode

from core.orchestrator import Orchestrator
from core.schemas import CycleLog
logger = logging.getLogger("telegram_bot")

def _escape_md(text: str) -> str:
    """Escape Telegram Markdown special chars."""
    for ch in ['_', '*', '[', ']', '(', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        text = text.replace(ch, f'\{ch}')
    return text

logger = logging.getLogger("telegram_bot")

ADMIN_IDS = set(int(x) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit())
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE = {"running": True, "last_cycle": None, "history": [], "current_provider": None}


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_cycle_message(log: CycleLog) -> str:
    if log.error or not log.final_decision:
        return (
            f"⚠️ *Cycle {log.cycle_id}* — {log.timestamp:%H:%M:%S} UTC\n"
            f"Status: DEGRADED → SKIP — {_escape_md(log.error or 'unknown error')}\n"
            f"Verification flags: {len(log.verification_flags)}\n"
            f"Total latency: {log.latency_seconds.get('total', 0):.1f}s"
        )

    d = log.final_decision
    emoji = {"UP": "🟢", "LEAN_UP": "🟢", "SKIP": "⚪", "LEAN_DOWN": "🔴", "DOWN": "🔴"}.get(d.rating.value, "⚪")

    return (
        f"{emoji} *Cycle {log.cycle_id}* — {log.timestamp:%H:%M:%S} UTC\n\n"
        f"*Decision:* `{d.rating.value}`\n"
        f"*Confidence:* {d.confidence}/10\n"
        f"*Position size:* ${d.position_size_usd:,.2f}\n"
        f"*Expected value:* {d.expected_value:.4f}\n"
        f"*Risk/Reward:* {d.risk_reward_ratio:.2f}\n\n"
        f"*Reasoning:*\n{_escape_md(d.reasoning[:500])}\n\n"
        f"*Warnings:* {_escape_md(', '.join(d.warnings)) if d.warnings else 'none'}\n\n"
        f"_Latency: {log.latency_seconds.get('total', 0):.1f}s | "
        f"This is system output, NOT financial advice._"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    running = "🟢 RUNNING" if STATE["running"] else "🔴 PAUSED"
    last = STATE["last_cycle"]
    last_info = f"{last.cycle_id} at {last.timestamp:%H:%M:%S} UTC" if last else "belum ada cycle"
    await update.message.reply_text(f"System: {running}\nLast cycle: {last_info}\nHistory: {len(STATE['history'])}")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not STATE["history"]:
        await update.message.reply_text("Belum ada history.")
        return
    lines = []
    for log in STATE["history"][-5:]:
        rating = log.final_decision.rating.value if log.final_decision else "SKIP(degraded)"
        lines.append(f"`{log.cycle_id}` {log.timestamp:%H:%M:%S} → {rating}")
    await update.message.reply_text("*5 cycle terakhir:*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    STATE["running"] = False
    await update.message.reply_text("⏸ Paused. /resume untuk lanjut.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    STATE["running"] = True
    await update.message.reply_text("▶️ Resumed.")


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    await update.message.reply_text("⏳ Menjalankan 1 cycle manual... (hasil dikirim otomatis)")
    asyncio.create_task(_run_manual_cycle(update, context))


async def _run_manual_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        orchestrator: Orchestrator = context.bot_data["orchestrator"]
        log = await orchestrator.run_cycle("Manual trigger — fetch current BTC market data and run analysis.")
        _record_cycle(log)
        await update.message.reply_text(format_cycle_message(log), parse_mode=ParseMode.MARKDOWN)
        if CHAT_ID and update.effective_chat and str(update.effective_chat.id) != str(CHAT_ID):
            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID, text=format_cycle_message(log), parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Failed to broadcast manual run: {e}")
    except Exception as e:
        logger.exception("Manual cycle failed")
        await update.message.reply_text(f"❌ Cycle failed: {e}")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch LLM provider. Usage: /model zyloo or /model xiaomi or /model (show current)"""
    from core.agent import PROVIDERS
    import re

    args = context.args
    if not args:
        # Show current provider + available list
        current = os.getenv("LLM_PROVIDER", "xiaomi")
        provider_list = "\n".join(
            f"  {'▸' if name == current else '○'} `{name}` — {p['default_model']}"
            for name, p in PROVIDERS.items()
        )
        await update.message.reply_text(
            f"*Current:* `{current}`\n\n"
            f"*Available providers:*\n{provider_list}\n\n"
            f"Usage: `/model <name>`\n"
            f"Example: `/model zyloo`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target = args[0].lower()
    if target not in PROVIDERS:
        await update.message.reply_text(
            f"❌ `{target}` not found.\nAvailable: {', '.join(f'`{k}`' for k in PROVIDERS)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Security: Validate target string (defense-in-depth, even though whitelist checked above)
    if not re.match(r'^[a-z0-9_-]+$', target):
        await update.message.reply_text(
            f"❌ Invalid provider name format: `{target}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.warning(f"Blocked invalid provider name: {target}")
        return

    # Update .env file with backup
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        # Create backup before modifying
        backup_path = env_path.with_suffix('.env.backup')
        try:
            import shutil
            shutil.copy2(env_path, backup_path)
        except Exception as e:
            logger.warning(f"Failed to create .env backup: {e}")
        
        content = env_path.read_text()
        if "LLM_PROVIDER=" in content:
            content = re.sub(r"LLM_PROVIDER=.*", f"LLM_PROVIDER={target}", content)
        else:
            content += f"\nLLM_PROVIDER={target}\n"
        env_path.write_text(content)

    # Also set in-process env so next cycle picks it up immediately
    os.environ["LLM_PROVIDER"] = target
    STATE["current_provider"] = target

    model_name = PROVIDERS[target]["default_model"]
    await update.message.reply_text(
        f"✅ Switched to *{target}* (`{model_name}`)\n"
        f"Berlaku mulai cycle berikutnya.",
        parse_mode=ParseMode.MARKDOWN,
    )


def _record_cycle(log: CycleLog):
    STATE["last_cycle"] = log
    STATE["history"].append(log)
    if len(STATE["history"]) > 20:
        STATE["history"].pop(0)


async def broadcast_cycle(app: Application, log: CycleLog):
    _record_cycle(log)
    if CHAT_ID:
        try:
            await app.bot.send_message(chat_id=CHAT_ID, text=format_cycle_message(log), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-command text messages (conversational queries)."""
    if not update.message or not update.message.text:
        return
    
    user_id = update.message.from_user.id if update.message.from_user else None
    message = update.message.text.strip()
    
    logger.info(f"📩 Message from {user_id}: {message[:50]}")
    
    # Import here to avoid circular dependency
    from telegram_bot.conversational import handle_message
    
    try:
        response = await handle_message(message, user_id)
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"📤 Reply sent to {user_id}")
    except Exception as e:
        logger.error(f"Conversational handler error: {e}")
        try:
            await update.message.reply_text(
                f"❌ Error: {str(e)[:100]}"
            )
        except Exception:
            pass


def build_app(orchestrator: Orchestrator) -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")
    app = Application.builder().token(token).build()
    app.bot_data["orchestrator"] = orchestrator
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("model", cmd_model))
    
    # Message handler for conversational queries (non-commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    return app
