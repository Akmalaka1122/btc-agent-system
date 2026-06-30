"""test_data_clients.py — Binance + Polymarket client tests with mocked HTTP."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.data.binance_client import BinanceClient
from core.data.liquidation_tracker import LiquidationTracker


class TestBinanceClient:
    @pytest.mark.asyncio
    async def test_get_ohlcv(self):
        """Mock Binance klines endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            [1735689600000, "100000.00", "100500.00", "99500.00", "100200.00",
             "150.50", 1735689900000, "15050000.00", 1200,
             "75.25", "7525000.00", "0"],
            [1735689900000, "100200.00", "100800.00", "100100.00", "100600.00",
             "180.20", 1735690200000, "18060000.00", 1500,
             "90.10", "9030000.00", "0"],
        ]

        client = BinanceClient()
        with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_response):
            candles = await client.get_ohlcv(interval="5m", limit=2)

        assert len(candles) == 2
        assert candles[0]["open"] == 100000.0
        assert candles[0]["close"] == 100200.0
        assert candles[1]["high"] == 100800.0
        assert candles[0]["volume"] == 150.5

    @pytest.mark.asyncio
    async def test_get_orderbook_snapshot(self):
        """Mock Binance depth endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "bids": [["100000.00", "1.500"], ["99999.00", "2.000"]],
            "asks": [["100001.00", "1.200"], ["100002.00", "1.800"]],
        }

        client = BinanceClient()
        with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_response):
            book = await client.get_orderbook_snapshot(limit=2)

        assert book["best_bid"] == 100000.0
        assert book["best_ask"] == 100001.0
        assert book["spread"] == 1.0
        assert book["bid_volume"] == 3.5
        assert book["ask_volume"] == 3.0
        assert 0 < book["bid_ask_imbalance"] < 1

    @pytest.mark.asyncio
    async def test_get_funding_rate(self):
        """Mock Binance premiumIndex endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "symbol": "BTCUSDT",
            "markPrice": "100200.00",
            "indexPrice": "100195.00",
            "lastFundingRate": "0.00010000",
            "nextFundingTime": 1735689600000,
        }

        client = BinanceClient()
        with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_response):
            funding = await client.get_funding_rate()

        assert funding["funding_rate"] == 0.0001
        assert funding["mark_price"] == 100200.0

    @pytest.mark.asyncio
    async def test_get_open_interest(self):
        """Mock Binance openInterest endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "openInterest": "85000.500",
            "symbol": "BTCUSDT",
            "time": 1735689600000,
        }

        client = BinanceClient()
        with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_response):
            oi = await client.get_open_interest()

        assert oi["open_interest"] == 85000.5

    @pytest.mark.asyncio
    async def test_get_ticker_24h(self):
        """Mock Binance 24h ticker."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "symbol": "BTCUSDT",
            "priceChangePercent": "2.50",
            "highPrice": "101000.00",
            "lowPrice": "98000.00",
            "lastPrice": "100600.00",
            "volume": "50000.00",
            "quoteVolume": "5000000000.00",
        }

        client = BinanceClient()
        with patch.object(client.client, "get", new_callable=AsyncMock, return_value=mock_response):
            ticker = await client.get_ticker_24h()

        assert ticker["price_change_pct"] == 2.5
        assert ticker["last_price"] == 100600.0


class TestLiquidationTracker:
    def test_get_recent_empty(self):
        """Empty buffer should return zeros."""
        tracker = LiquidationTracker()
        result = tracker.get_recent(minutes=5)
        assert result["long_liquidations_usd"] == 0
        assert result["short_liquidations_usd"] == 0
        assert result["count"] == 0
        assert result["connected"] is False

    def test_get_recent_with_data(self):
        """Buffer with events should aggregate correctly."""
        from datetime import datetime, timezone, timedelta

        tracker = LiquidationTracker()
        now = datetime.now(timezone.utc)

        # Add some liquidation events
        tracker.buffer.append({
            "side": "SELL",  # long liquidated
            "qty": 1.0,
            "price": 100000.0,
            "time": now - timedelta(minutes=2),
        })
        tracker.buffer.append({
            "side": "BUY",  # short liquidated
            "qty": 0.5,
            "price": 100000.0,
            "time": now - timedelta(minutes=1),
        })
        tracker._connected = True

        result = tracker.get_recent(minutes=5)
        assert result["long_liquidations_usd"] == 100000.0
        assert result["short_liquidations_usd"] == 50000.0
        assert result["total_liquidations_usd"] == 150000.0
        assert result["count"] == 2
        assert result["connected"] is True

    def test_prune_old_events(self):
        """Events outside buffer window should be pruned."""
        from datetime import datetime, timezone, timedelta

        tracker = LiquidationTracker(buffer_minutes=5)
        now = datetime.now(timezone.utc)

        # Old event (10 min ago — outside 5 min buffer)
        tracker.buffer.append({
            "side": "SELL", "qty": 1.0, "price": 100000.0,
            "time": now - timedelta(minutes=10),
        })
        # Recent event (1 min ago)
        tracker.buffer.append({
            "side": "BUY", "qty": 0.5, "price": 100000.0,
            "time": now - timedelta(minutes=1),
        })

        tracker._prune()
        assert len(tracker.buffer) == 1
        assert tracker.buffer[0]["side"] == "BUY"
