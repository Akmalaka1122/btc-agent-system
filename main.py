"""
main.py — entry point.

Menjalankan:
1. Database init (SQLite — cycle history, circuit breakers)
2. Binance client (REST — OHLCV, orderbook, funding, OI)
3. Polymarket client (CLOB — market odds)
4. Liquidation tracker (WebSocket — background listener)
5. Telegram bot (polling, untuk command /status /history /pause /resume /run)
6. Scheduler yang trigger orchestrator.run_cycle() tiap CYCLE_INTERVAL_SECONDS,
   lalu broadcast hasilnya ke Telegram.

Jalankan: python main.py
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.orchestrator import Orchestrator
from core.data.binance_client import BinanceClient
from core.data.polymarket_client import PolymarketClient
from core.data.liquidation_tracker import LiquidationTracker
from core.data.db import Database
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
        "See .env.example for provider options (OpenRouter, Xiaomi, DeepSeek, Anthropic, OpenAI)"
    )


async def build_market_context(binance: BinanceClient, liq_tracker: LiquidationTracker) -> str:
    """
    Build market context string dari real data.
    Dipanggil oleh scheduled_cycle dan manual /run.
    """
    sections = []

    try:
        candles = await binance.get_ohlcv(interval="5m", limit=50)
        if candles:
            last = candles[-1]
            prev = candles[-2] if len(candles) > 1 else last
            sections.append(
                f"## BTC Price (5m candles)\n"
                f"Current: ${last['close']:,.2f}\n"
                f"Last candle: O=${last['open']:,.2f} H=${last['high']:,.2f} "
                f"L=${last['low']:,.2f} C=${last['close']:,.2f} Vol={last['volume']:,.2f}\n"
                f"Prev candle: O=${prev['open']:,.2f} H=${prev['high']:,.2f} "
                f"L=${prev['low']:,.2f} C=${prev['close']:,.2f}\n"
                f"Change: {((last['close'] - prev['close']) / prev['close'] * 100):+.3f}%"
            )
    except Exception as e:
        logger.warning(f"OHLCV fetch failed: {e}")
        sections.append("## BTC Price: UNAVAILABLE")

    try:
        book = await binance.get_orderbook_snapshot(limit=20)
        sections.append(
            f"## Orderbook (top 20)\n"
            f"Bid: ${book['best_bid']:,.2f} | Ask: ${book['best_ask']:,.2f}\n"
            f"Spread: ${book['spread']:,.2f}\n"
            f"Bid vol: {book['bid_volume']:.3f} BTC | Ask vol: {book['ask_volume']:.3f} BTC\n"
            f"Imbalance: {book['bid_ask_imbalance']:.3f}"
        )
    except Exception as e:
        logger.warning(f"Orderbook fetch failed: {e}")
        sections.append("## Orderbook: UNAVAILABLE")

    try:
        funding = await binance.get_funding_rate()
        fr = funding['funding_rate'] * 100
        sections.append(
            f"## Funding\n"
            f"Rate: {fr:+.4f}% | Mark: ${funding['mark_price']:,.2f}"
        )
    except Exception as e:
        logger.warning(f"Funding fetch failed: {e}")

    try:
        oi = await binance.get_open_interest()
        sections.append(f"## Open Interest\n{oi['open_interest']:.3f} BTC")
    except Exception as e:
        logger.warning(f"OI fetch failed: {e}")

    try:
        liq = liq_tracker.get_recent(minutes=5)
        if liq["count"] > 0:
            sections.append(
                f"## Liquidations (5m)\n"
                f"Longs: ${liq['long_liquidations_usd']:,.0f} | "
                f"Shorts: ${liq['short_liquidations_usd']:,.0f} | "
                f"Count: {liq['count']}"
            )
        else:
            sections.append("## Liquidations (5m)\nNone")
    except Exception as e:
        logger.warning(f"Liquidation fetch failed: {e}")

    return "\n\n".join(sections) if sections else "⚠️ NO DATA — all sources failed"


async def scheduled_cycle(orchestrator: Orchestrator, app, binance, liq_tracker):
    if not STATE["running"]:
        logger.info("Scheduler paused, skipping cycle.")
        return
    try:
        # Build real market context from Binance + liquidation data
        market_context = await build_market_context(binance, liq_tracker)
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
        logger.warning("PAPER_TRADING=true — tidak ada eksekusi order nyata.")

    # --- Initialize data clients ---
    binance = BinanceClient(timeout=10.0)
    polymarket = PolymarketClient(timeout=10.0)
    liq_tracker = LiquidationTracker(buffer_minutes=30)
    db = Database("btc_agent_system.db")

    # Start DB
    await db.init()
    logger.info("Database initialized")

    # Start liquidation WebSocket listener
    liq_tracker.start()
    logger.info("Liquidation tracker started")

    # --- Initialize orchestrator with data clients ---
    orchestrator = Orchestrator(
        binance_client=binance,
        polymarket_client=polymarket,
        liquidation_tracker=liq_tracker,
        database=db,
    )

    # --- Telegram bot ---
    app = build_app(orchestrator)

    # --- Scheduler ---
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_cycle, "interval", seconds=CYCLE_INTERVAL,
        args=[orchestrator, app, binance, liq_tracker],
        id="btc_cycle", max_instances=1,
    )
    scheduler.start()

    logger.info(f"System starting. Cycle interval: {CYCLE_INTERVAL}s | Provider: {os.getenv('LLM_PROVIDER', 'openrouter')}")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            logger.info("Shutting down...")
            await app.updater.stop()
            await app.stop()
            liq_tracker.stop()
            await binance.close()
            await polymarket.close()
            await db.close()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
