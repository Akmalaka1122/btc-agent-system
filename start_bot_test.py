"""Start bot for interactive testing (no scheduler, manual cycles only)."""
import asyncio
import logging
import os
from dotenv import load_dotenv

from telegram_bot.bot import build_app, STATE
from core.orchestrator import Orchestrator
from core.data.binance_client import BinanceClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Suppress verbose logs
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("bot_test")

async def main():
    load_dotenv()
    
    logger.info("🚀 Starting bot for testing (no scheduler)...")
    
    # Initialize with real Binance client (read-only)
    binance = BinanceClient(timeout=10.0)
    
    orchestrator = Orchestrator(
        binance_client=binance,
        polymarket_client=None,
        liquidation_tracker=None,
        database=None,
    )
    
    # Build bot app
    app = build_app(orchestrator)
    
    logger.info(f"✅ Bot: @{(await app.bot.get_me()).username}")
    logger.info(f"✅ Admin ID: {os.getenv('TELEGRAM_ADMIN_IDS')}")
    logger.info(f"✅ Home chat: {os.getenv('TELEGRAM_CHAT_ID')}")
    logger.info("🟢 Bot ready! Waiting for commands...")
    logger.info("   Send /status or /run to test")
    logger.info("   Press Ctrl+C to stop")
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            logger.info("⏹️  Stopping bot...")
            await app.updater.stop()
            await app.stop()
            await binance.close()
            logger.info("✅ Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
