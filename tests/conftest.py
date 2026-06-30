"""conftest.py — shared fixtures for test suite."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def event_loop():
    """Override default event loop for pytest-asyncio."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_binance_client():
    """Mock BinanceClient that returns realistic data."""
    client = AsyncMock()
    client.get_ohlcv.return_value = [
        {
            "open_time": "2025-01-01T00:00:00Z",
            "open": 100000.0, "high": 100500.0,
            "low": 99500.0, "close": 100200.0,
            "volume": 150.5, "close_time": "2025-01-01T00:05:00Z",
            "quote_volume": 15050000.0, "trades": 1200,
        },
        {
            "open_time": "2025-01-01T00:05:00Z",
            "open": 100200.0, "high": 100800.0,
            "low": 100100.0, "close": 100600.0,
            "volume": 180.2, "close_time": "2025-01-01T00:10:00Z",
            "quote_volume": 18060000.0, "trades": 1500,
        },
    ]
    client.get_orderbook_snapshot.return_value = {
        "bids": [(100000.0, 1.5), (99999.0, 2.0)],
        "asks": [(100001.0, 1.2), (100002.0, 1.8)],
        "bid_ask_imbalance": 0.52,
        "spread": 1.0,
        "best_bid": 100000.0,
        "best_ask": 100001.0,
        "bid_volume": 3.5,
        "ask_volume": 3.0,
    }
    client.get_funding_rate.return_value = {
        "funding_rate": 0.0001,
        "mark_price": 100200.0,
        "index_price": 100195.0,
        "next_funding_time": 1735689600000,
    }
    client.get_open_interest.return_value = {"open_interest": 85000.5}
    client.get_ticker_24h.return_value = {
        "price_change_pct": 2.5,
        "high_24h": 101000.0,
        "low_24h": 98000.0,
        "last_price": 100600.0,
        "volume_24h": 50000.0,
        "quote_volume_24h": 5_000_000_000.0,
    }
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_liq_tracker():
    """Mock LiquidationTracker."""
    tracker = MagicMock()
    tracker.get_recent.return_value = {
        "long_liquidations_usd": 2_500_000.0,
        "short_liquidations_usd": 1_200_000.0,
        "total_liquidations_usd": 3_700_000.0,
        "count": 15,
        "connected": True,
    }
    return tracker
