"""
liquidation_tracker.py — WebSocket listener untuk Binance forceOrder stream.

Harus jalan sebagai background task terpisah dari cycle utama.
Menyimpan liquidation events ke rolling buffer (default 30 menit).
Dipanggil oleh orchestrator via .get_recent(minutes=5) setiap cycle.
"""
import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger("liquidation_tracker")

STREAM_URL = "wss://fstream.binance.com/ws/btcusdt@forceOrder"


class LiquidationTracker:
    def __init__(self, buffer_minutes: int = 30):
        self.buffer: deque = deque()
        self.buffer_minutes = buffer_minutes
        self._task: asyncio.Task | None = None
        self._connected = False

    async def _listen(self):
        """Background loop: connect, listen, reconnect on disconnect."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — liquidation tracking disabled")
            return

        while True:
            try:
                async with websockets.connect(STREAM_URL) as ws:
                    self._connected = True
                    logger.info("Liquidation WebSocket connected")
                    async for message in ws:
                        try:
                            data = json.loads(message).get("o", {})
                            self.buffer.append({
                                "side": data.get("S", ""),       # SELL = long liquidated, BUY = short liquidated
                                "qty": float(data.get("q", 0)),
                                "price": float(data.get("p", 0)),
                                "time": datetime.now(timezone.utc),
                            })
                            self._prune()
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.debug(f"Liquidation parse error: {e}")
            except Exception as e:
                self._connected = False
                logger.warning(f"Liquidation WS disconnected: {e}, reconnecting in 3s")
                await asyncio.sleep(3)

    def _prune(self):
        """Remove events older than buffer window."""
        cutoff = datetime.now(timezone.utc).timestamp() - self.buffer_minutes * 60
        while self.buffer and self.buffer[0]["time"].timestamp() < cutoff:
            self.buffer.popleft()

    def get_recent(self, minutes: int = 5) -> dict:
        """
        Aggregated liquidation data untuk N menit terakhir.
        Dipanggil tiap cycle oleh orchestrator untuk inject ke market_context.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - minutes * 60
        recent = [x for x in self.buffer if x["time"].timestamp() >= cutoff]
        long_liq = sum(x["qty"] * x["price"] for x in recent if x["side"] == "SELL")
        short_liq = sum(x["qty"] * x["price"] for x in recent if x["side"] == "BUY")
        return {
            "long_liquidations_usd": round(long_liq, 2),
            "short_liquidations_usd": round(short_liq, 2),
            "total_liquidations_usd": round(long_liq + short_liq, 2),
            "count": len(recent),
            "connected": self._connected,
        }

    def start(self):
        """Start background WebSocket listener. Call once at startup."""
        if self._task is None:
            self._task = asyncio.create_task(self._listen())
            logger.info("LiquidationTracker started")

    def stop(self):
        """Stop background listener. Call at shutdown."""
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("LiquidationTracker stopped")
