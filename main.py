"""
main.py — entry point.

Menjalankan:
1. Telegram bot (polling, untuk command /status /history /pause /resume /run)
2. Scheduler yang trigger orchestrator.run_cycle() tiap CYCLE_INTERVAL_SECONDS,
   lalu broadcast hasilnya ke Telegram.

Jalankan: python main.py
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.orchestrator import Orchestrator
from telegram_bot.bot import build_app, broadcast_cycle, STATE

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

CYCLE_INTERVAL = int(os.getenv("CYCLE_INTERVAL_SECONDS", "300"))  # default 5 menit
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

if not os.getenv("LLM_API_KEY"):
    raise RuntimeError(
        "LLM_API_KEY not set. Copy .env.example to .env and fill in your API key.\n"
        "See .env.example for provider options (Xpiki, UniModel, OpenAI, etc.)"
    )


async def scheduled_cycle(orchestrator: Orchestrator, app):
    if not STATE["running"]:
        logger.info("Scheduler paused, skipping cycle.")
        return
    try:
        market_context = (
            "Scheduled cycle — fetch current BTC market data, sentiment, news, "
            "and on-chain metrics, then run full analysis for the next 5-minute window."
        )
        log = await orchestrator.run_cycle(market_context)
        await broadcast_cycle(app, log)
        logger.info(
            f"Cycle {log.cycle_id} done in {log.latency_seconds.get('total', 0):.1f}s "
            f"-> {log.final_decision.rating.value if log.final_decision else 'ERROR'}"
        )
    except Exception:
        logger.exception("Cycle failed with unhandled exception")


async def main():
    if PAPER_TRADING:
        logger.warning("PAPER_TRADING=true — tidak ada eksekusi order nyata, hanya logging + Telegram alert.")

    orchestrator = Orchestrator()
    app = build_app(orchestrator)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_cycle, "interval", seconds=CYCLE_INTERVAL,
        args=[orchestrator, app], id="btc_cycle", max_instances=1,
    )
    scheduler.start()

    logger.info(f"System starting. Cycle interval: {CYCLE_INTERVAL}s")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
