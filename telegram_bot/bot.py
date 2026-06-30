"""
bot.py — Telegram integration.

Fitur:
- Auto-alert tiap cycle selesai (kirim final decision + ringkasan log)
- /status — cek apakah sistem running, cycle terakhir kapan
- /history — 5 keputusan terakhir
- /pause /resume — stop/start cycle scheduler (admin only)
- /run — trigger 1 cycle manual (admin only, buat testing)
"""
import os
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from core.orchestrator import Orchestrator
from core.schemas import CycleLog

logger = logging.getLogger("telegram_bot")

ADMIN_IDS = set(
    int(x) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit()
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# in-memory state (ganti ke DB/Redis kalau mau persist across restart)
STATE = {
    "running": True,
    "last_cycle": None,        # CycleLog
    "history": [],             # list of CycleLog, max 20
}


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_cycle_message(log: CycleLog) -> str:
    if log.error or not log.final_decision:
        return (
            f"⚠️ *Cycle {log.cycle_id}* — {log.timestamp:%H:%M:%S} UTC\n"
            f"Status: DEGRADED — {log.error or 'unknown error'}\n"
            f"Verification flags: {len(log.verification_flags)}\n"
            f"Data quality flags: {len(log.data_quality_flags)}\n"
            f"Total latency: {log.latency_seconds.get('total', 0):.1f}s"
        )

    d = log.final_decision
    emoji = {"UP": "🟢", "LEAN_UP": "🟢", "SKIP": "⚪", "LEAN_DOWN": "🔴", "DOWN": "🔴"}.get(d.rating.value, "⚪")
    flags_note = ""
    if log.data_quality_flags:
        flags_note = f"\n⚠️ Data flags: {len(log.data_quality_flags)} (lihat /history untuk detail)"

    return (
        f"{emoji} *Cycle {log.cycle_id}* — {log.timestamp:%H:%M:%S} UTC\n\n"
        f"*Decision:* `{d.rating.value}`\n"
        f"*Confidence:* {d.confidence}/10\n"
        f"*Position size:* ${d.position_size_usd:,.2f}\n"
        f"*Expected value:* {d.expected_value:.4f}\n"
        f"*Risk/Reward:* {d.risk_reward_ratio:.2f}\n\n"
        f"*Reasoning:*\n{d.reasoning[:500]}\n\n"
        f"*Key factors:* {', '.join(d.key_factors[:5])}\n"
        f"*Warnings:* {', '.join(d.warnings) if d.warnings else 'none'}"
        f"{flags_note}\n\n"
        f"_Total latency: {log.latency_seconds.get('total', 0):.1f}s | "
        f"This is system output, NOT financial advice._"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    running = "🟢 RUNNING" if STATE["running"] else "🔴 PAUSED"
    last = STATE["last_cycle"]
    last_info = f"{last.cycle_id} at {last.timestamp:%H:%M:%S} UTC" if last else "belum ada cycle"
    await update.message.reply_text(
        f"System status: {running}\nLast cycle: {last_info}\nHistory stored: {len(STATE['history'])}"
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not STATE["history"]:
        await update.message.reply_text("Belum ada history.")
        return
    lines = []
    for log in STATE["history"][-5:]:
        d = log.final_decision
        rating = d.rating.value if d else "ERROR"
        lines.append(f"`{log.cycle_id}` {log.timestamp:%H:%M:%S} → {rating}")
    await update.message.reply_text("*5 cycle terakhir:*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    STATE["running"] = False
    await update.message.reply_text("⏸ Scheduler dipause. Pakai /resume untuk lanjut.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    STATE["running"] = True
    await update.message.reply_text("▶️ Scheduler resumed.")


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    await update.message.reply_text("Menjalankan 1 cycle manual...")
    orchestrator: Orchestrator = context.bot_data["orchestrator"]
    market_context = "Manual trigger — fetch current BTC market data and run full analysis."
    log = await orchestrator.run_cycle(market_context)
    _record_cycle(log)
    await update.message.reply_text(format_cycle_message(log), parse_mode=ParseMode.MARKDOWN)


def _record_cycle(log: CycleLog):
    STATE["last_cycle"] = log
    STATE["history"].append(log)
    if len(STATE["history"]) > 20:
        STATE["history"].pop(0)


async def broadcast_cycle(app: Application, log: CycleLog):
    """Dipanggil scheduler tiap selesai 1 cycle otomatis."""
    _record_cycle(log)
    if CHAT_ID:
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=format_cycle_message(log),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")


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

    return app
