"""
binance_client.py — REST client untuk data BTC real-time dari Binance.

Endpoints:
  - OHLCV (klines): spot REST — 5m candles untuk technical analysis
  - Orderbook depth: spot REST — bid/ask imbalance untuk microstructure
  - Funding rate: futures REST — premium/discount indicator
  - Open interest: futures REST — positioning gauge

Liquidation data via WebSocket di file terpisah (liquidation_tracker.py).
"""
import httpx
import logging
from datetime import datetime, timezone

logger = logging.getLogger("binance_client")

BASE_URL = "https://fapi.binance.com"  # futures — funding/OI
SPOT_URL = "https://api.binance.com"   # spot — klines/depth


class BinanceClient:
    def __init__(self, timeout: float = 10.0):
        self.client = httpx.AsyncClient(timeout=timeout)

    async def get_ohlcv(
        self, symbol: str = "BTCUSDT", interval: str = "5m", limit: int = 50
    ) -> list[dict]:
        """
        Fetch OHLCV klines. interval: 1m, 5m, 15m, 1h, dll.
        Return list candle terbaru (newest last).
        """
        resp = await self.client.get(
            f"{SPOT_URL}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        raw = resp.json()
        return [
            {
                "open_time": datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "close_time": datetime.fromtimestamp(c[6] / 1000, tz=timezone.utc),
                "quote_volume": float(c[7]),
                "trades": int(c[8]),
            }
            for c in raw
        ]

    async def get_orderbook_snapshot(
        self, symbol: str = "BTCUSDT", limit: int = 20
    ) -> dict:
        """
        Orderbook depth snapshot. Return bids/asks + computed imbalance.
        bid_ask_imbalance > 0.5 = more bid volume (bullish pressure).
        """
        resp = await self.client.get(
            f"{SPOT_URL}/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        bids = [(float(p), float(q)) for p, q in data["bids"]]
        asks = [(float(p), float(q)) for p, q in data["asks"]]
        bid_vol = sum(q for _, q in bids)
        ask_vol = sum(q for _, q in asks)
        total = bid_vol + ask_vol
        return {
            "bids": bids,
            "asks": asks,
            "bid_ask_imbalance": bid_vol / total if total > 0 else 0.5,
            "spread": asks[0][0] - bids[0][0] if bids and asks else None,
            "best_bid": bids[0][0] if bids else None,
            "best_ask": asks[0][0] if asks else None,
            "bid_volume": bid_vol,
            "ask_volume": ask_vol,
        }

    async def get_funding_rate(self, symbol: str = "BTCUSDT") -> dict:
        """
        Funding rate + mark price dari futures endpoint.
        Positive = longs pay shorts (market bullish), negative = opposite.
        """
        resp = await self.client.get(
            f"{BASE_URL}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "funding_rate": float(data["lastFundingRate"]),
            "mark_price": float(data["markPrice"]),
            "index_price": float(data.get("indexPrice", 0)),
            "next_funding_time": int(data.get("nextFundingTime", 0)),
        }

    async def get_open_interest(self, symbol: str = "BTCUSDT") -> dict:
        """Current open interest di futures market."""
        resp = await self.client.get(
            f"{BASE_URL}/fapi/v1/openInterest",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        return {"open_interest": float(resp.json()["openInterest"])}

    async def get_ticker_24h(self, symbol: str = "BTCUSDT") -> dict:
        """24h price change stats — useful untuk quick context."""
        resp = await self.client.get(
            f"{SPOT_URL}/api/v3/ticker/24hr",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "price_change_pct": float(data["priceChangePercent"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
            "last_price": float(data["lastPrice"]),
            "volume_24h": float(data["volume"]),
            "quote_volume_24h": float(data["quoteVolume"]),
        }

    async def close(self):
        await self.client.aclose()

    async def get_price(self, symbol: str = "BTCUSDT") -> float:
        """Get current price — lightweight single endpoint."""
        resp = await self.client.get(
            f"{SPOT_URL}/api/v3/ticker/price",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        return float(resp.json()["price"])
