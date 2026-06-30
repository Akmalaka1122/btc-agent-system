"""
market_simulator.py — Convert historical data to market_context format.

Takes downloaded Parquet files and simulates what Market Analyst would see
at each 5-minute window. Outputs structured market_context string that
matches orchestrator's live format.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger("market_simulator")


class MarketSimulator:
    """
    Simulate market conditions at any historical timeframe.
    
    Loads OHLCV, funding rate, and OI data once, then provides fast
    lookups for any timestamp window.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.ohlcv_df: Optional[pd.DataFrame] = None
        self.funding_df: Optional[pd.DataFrame] = None
        self.oi_df: Optional[pd.DataFrame] = None
        self._loaded = False
    
    def load_data(self, start_date: str, end_date: str, symbol: str = "BTCUSDT"):
        """Load all parquet files for the given date range."""
        logger.info(f"Loading data for {symbol} from {start_date} to {end_date}")
        
        # Load OHLCV
        ohlcv_path = self.data_dir / f"{symbol}_5m_ohlcv_{start_date}_{end_date}.parquet"
        if not ohlcv_path.exists():
            raise FileNotFoundError(
                f"OHLCV data not found: {ohlcv_path}\n"
                f"Run: python backtest/data_loader.py --start {start_date} --end {end_date}"
            )
        self.ohlcv_df = pd.read_parquet(ohlcv_path)
        self.ohlcv_df = self.ohlcv_df.sort_values("open_time").reset_index(drop=True)
        logger.info(f"Loaded {len(self.ohlcv_df)} OHLCV candles")
        
        # Load funding rate
        funding_path = self.data_dir / f"{symbol}_funding_{start_date}_{end_date}.parquet"
        if funding_path.exists():
            self.funding_df = pd.read_parquet(funding_path)
            self.funding_df = self.funding_df.sort_values("fundingTime").reset_index(drop=True)
            logger.info(f"Loaded {len(self.funding_df)} funding rate snapshots")
        else:
            logger.warning(f"Funding data not found: {funding_path}")
            self.funding_df = pd.DataFrame()
        
        # Load OI (optional, may not exist for older periods)
        oi_path = list(self.data_dir.glob(f"{symbol}_oi_5m_*.parquet"))
        if oi_path:
            self.oi_df = pd.read_parquet(oi_path[0])
            self.oi_df = self.oi_df.sort_values("timestamp").reset_index(drop=True)
            logger.info(f"Loaded {len(self.oi_df)} OI records")
        else:
            logger.warning("No OI data found (expected for periods >30 days old)")
            self.oi_df = pd.DataFrame()
        
        self._loaded = True
        logger.info(f"MarketSimulator ready: {len(self.ohlcv_df)} candles loaded")
    
    def get_market_context(
        self,
        current_time: datetime,
        lookback_candles: int = 50,
    ) -> str:
        """
        Build market_context string for a specific timestamp.
        
        Mimics what orchestrator._fetch_market_data() would produce,
        but from historical data instead of live API calls.
        
        Args:
            current_time: Timestamp to simulate (should align with candle close_time)
            lookback_candles: How many candles to include in context (default 50)
        
        Returns:
            Formatted market_context string ready for Market Analyst
        """
        if not self._loaded:
            raise RuntimeError("Call load_data() first")
        
        sections = []
        
        # --- BTC Price Data (OHLCV) ---
        # Get candles up to current_time
        candles = self.ohlcv_df[self.ohlcv_df["close_time"] <= current_time].tail(lookback_candles)
        
        if len(candles) < 2:
            return "⚠️ INSUFFICIENT DATA — not enough historical candles at this timestamp"
        
        last = candles.iloc[-1]
        prev = candles.iloc[-2]
        
        sections.append(
            f"## BTC Price Data (5m candles, last {len(candles)})\n"
            f"Current price: ${last['close']:,.2f}\n"
            f"Last candle: O=${last['open']:,.2f} H=${last['high']:,.2f} "
            f"L=${last['low']:,.2f} C=${last['close']:,.2f} V={last['volume']:,.2f}\n"
            f"Previous candle: O=${prev['open']:,.2f} H=${prev['high']:,.2f} "
            f"L=${prev['low']:,.2f} C=${prev['close']:,.2f}\n"
            f"Price change last 2 candles: "
            f"{((last['close'] - prev['close']) / prev['close'] * 100):+.3f}%"
        )
        
        # --- Orderbook (simulated from volume) ---
        # Real backtest can't reconstruct orderbook from OHLCV alone.
        # We'll use volume as proxy for liquidity, but mark it as simulated.
        avg_volume = candles["volume"].tail(20).mean()
        current_volume = last["volume"]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Simulate spread based on volatility (high-low range)
        volatility = (last["high"] - last["low"]) / last["close"] * 100  # % range
        simulated_spread = last["close"] * (volatility / 100) * 0.1  # rough estimate
        
        sections.append(
            f"## Orderbook Snapshot (simulated from volume)\n"
            f"⚠️ Note: Orderbook data unavailable in backtest — using volume proxy\n"
            f"Estimated spread: ${simulated_spread:.2f}\n"
            f"Volume ratio (current/20-candle avg): {volume_ratio:.2f}x\n"
            f"Liquidity indicator: {'high' if volume_ratio > 1.2 else 'low' if volume_ratio < 0.8 else 'normal'}"
        )
        
        # --- Funding Rate ---
        if not self.funding_df.empty:
            # Get most recent funding rate before current_time
            funding = self.funding_df[self.funding_df["fundingTime"] <= current_time]
            if not funding.empty:
                latest_funding = funding.iloc[-1]
                fr_pct = latest_funding["fundingRate"] * 100
                
                sections.append(
                    f"## Funding Rate & Mark Price\n"
                    f"Funding rate: {fr_pct:+.4f}% "
                    f"({'longs pay shorts — bullish crowding' if fr_pct > 0.01 else 'shorts pay longs — bearish crowding' if fr_pct < -0.01 else 'neutral'})\n"
                    f"Mark price: ${last['close']:,.2f} (approximated from spot close)\n"
                    f"Last funding time: {latest_funding['fundingTime']}"
                )
            else:
                sections.append("## Funding Rate: UNAVAILABLE (no data before this timestamp)")
        else:
            sections.append("## Funding Rate: UNAVAILABLE")
        
        # --- Open Interest ---
        if not self.oi_df.empty:
            oi = self.oi_df[self.oi_df["timestamp"] <= current_time]
            if not oi.empty:
                latest_oi = oi.iloc[-1]
                sections.append(
                    f"## Open Interest\n"
                    f"Current OI: {latest_oi['sumOpenInterest']:,.3f} BTC "
                    f"(${latest_oi['sumOpenInterestValue']:,.0f})"
                )
            else:
                sections.append("## Open Interest: UNAVAILABLE (no data before this timestamp)")
        else:
            sections.append("## Open Interest: UNAVAILABLE")
        
        # --- 24h Stats (computed from available candles) ---
        candles_24h = self.ohlcv_df[
            (self.ohlcv_df["close_time"] <= current_time) &
            (self.ohlcv_df["close_time"] >= current_time - timedelta(hours=24))
        ]
        
        if len(candles_24h) > 0:
            high_24h = candles_24h["high"].max()
            low_24h = candles_24h["low"].min()
            volume_24h = candles_24h["volume"].sum()
            quote_volume_24h = candles_24h["quote_volume"].sum()
            first_close = candles_24h.iloc[0]["close"]
            last_close = candles_24h.iloc[-1]["close"]
            price_change_pct = ((last_close - first_close) / first_close * 100) if first_close > 0 else 0
            
            sections.append(
                "## 24h Stats\n"
                f"24h change: {price_change_pct:+.2f}%\n"
                f"24h high: ${high_24h:,.2f} | 24h low: ${low_24h:,.2f}\n"
                f"24h volume: {volume_24h:,.2f} BTC (${quote_volume_24h:,.0f})"
            )
        else:
            sections.append("## 24h Stats: UNAVAILABLE (insufficient historical data)")
        
        # --- Liquidations ---
        # No liquidation data in backtest (WebSocket-only in live system)
        sections.append(
            "## Liquidations (last 5 min)\n"
            "⚠️ Liquidation data unavailable in backtest mode"
        )
        
        if not sections:
            return "⚠️ NO MARKET DATA AVAILABLE — all data sources failed"
        
        return "\n\n".join(sections)
    
    def get_candle_at(self, timestamp: datetime) -> Optional[pd.Series]:
        """Get the candle that closes at or just before the given timestamp."""
        if not self._loaded or self.ohlcv_df is None:
            return None
        
        candles = self.ohlcv_df[self.ohlcv_df["close_time"] <= timestamp]
        if candles.empty:
            return None
        return candles.iloc[-1]
    
    def get_price_at(self, timestamp: datetime) -> Optional[float]:
        """Get BTC close price at the given timestamp."""
        candle = self.get_candle_at(timestamp)
        return float(candle["close"]) if candle is not None else None
    
    def iterate_windows(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        interval_minutes: int = 5,
    ):
        """
        Yield (timestamp, market_context) for each window in the date range.
        
        This is the main iterator for backtest engine — each iteration
        represents one cycle the orchestrator would run in live trading.
        
        Args:
            start_time: Start of backtest period (default: first candle)
            end_time: End of backtest period (default: last candle)
            interval_minutes: Time between cycles (default: 5 = every candle)
        
        Yields:
            (timestamp, market_context) tuples
        """
        if not self._loaded:
            raise RuntimeError("Call load_data() first")
        
        if start_time is None:
            start_time = self.ohlcv_df.iloc[50]["close_time"]  # Skip first 50 for lookback
        if end_time is None:
            end_time = self.ohlcv_df.iloc[-1]["close_time"]
        
        current = start_time
        interval = timedelta(minutes=interval_minutes)
        
        logger.info(f"Iterating from {start_time} to {end_time} (interval: {interval_minutes}m)")
        
        count = 0
        while current <= end_time:
            # Check if we have data for this timestamp
            candle = self.get_candle_at(current)
            if candle is None:
                logger.debug(f"No candle at {current}, skipping")
                current += interval
                continue
            
            market_context = self.get_market_context(current)
            
            # Skip if insufficient data
            if "INSUFFICIENT DATA" in market_context or "NO MARKET DATA" in market_context:
                current += interval
                continue
            
            yield (current, market_context)
            count += 1
            
            current += interval
        
        logger.info(f"Generated {count} market contexts for backtest")


if __name__ == "__main__":
    # Test the simulator
    import sys
    from pathlib import Path
    
    logging.basicConfig(level=logging.INFO)
    
    data_dir = Path(__file__).parent.parent / "data"
    sim = MarketSimulator(data_dir)
    
    # Load 2-day test data
    sim.load_data("2026-06-28", "2026-06-30")
    
    # Test getting market context at a specific time
    test_time = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    context = sim.get_market_context(test_time)
    
    print("=" * 70)
    print(f"MARKET CONTEXT @ {test_time}")
    print("=" * 70)
    print(context)
    print("=" * 70)
    
    # Test iteration
    print("\nTesting window iteration (first 5 windows):")
    for i, (ts, ctx) in enumerate(sim.iterate_windows()):
        if i >= 5:
            break
        price = sim.get_price_at(ts)
        print(f"  {i+1}. {ts} | BTC: ${price:,.2f} | Context length: {len(ctx)} chars")
    
    print(f"\n✅ MarketSimulator test complete")
