"""
data_loader.py — Download historical BTC data from Binance for backtesting.

Fetches:
  - 5-minute OHLCV candles (spot market)
  - Funding rate snapshots (futures, 8h intervals)
  - Open interest snapshots (futures)
  
Saves to Parquet for fast loading during backtest runs.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_loader")

SPOT_URL = "https://api.binance.com"
FUTURES_URL = "https://fapi.binance.com"
OUTPUT_DIR = Path(__file__).parent.parent / "data"


async def fetch_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    start_time: datetime = None,
    end_time: datetime = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV klines from Binance spot API.
    
    Binance /klines limits:
      - Max 1000 candles per request
      - Need to paginate for date ranges >1000 intervals
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc) - timedelta(days=90)
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    logger.info(f"Fetching OHLCV for {symbol} from {start_time} to {end_time} ({interval})")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        all_candles = []
        current_start = start_time
        
        while current_start < end_time:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 1000,
            }
            
            resp = await client.get(f"{SPOT_URL}/api/v3/klines", params=params)
            resp.raise_for_status()
            candles = resp.json()
            
            if not candles:
                break
            
            all_candles.extend(candles)
            
            # Move to next batch (last candle's close time + 1ms)
            last_close_time = candles[-1][6]  # close_time
            current_start = datetime.fromtimestamp(last_close_time / 1000 + 0.001, tz=timezone.utc)
            
            logger.info(f"Fetched {len(candles)} candles, total: {len(all_candles)}")
            await asyncio.sleep(0.5)  # Rate limit respect
        
        # Convert to DataFrame
        df = pd.DataFrame(all_candles, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore"
        ])
        
        # Convert types
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        
        logger.info(f"Total candles fetched: {len(df)}")
        return df


async def fetch_funding_rate_history(
    symbol: str = "BTCUSDT",
    start_time: datetime = None,
    end_time: datetime = None,
) -> pd.DataFrame:
    """
    Fetch historical funding rate from Binance futures API.
    
    Funding rate settles every 8 hours (00:00, 08:00, 16:00 UTC).
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc) - timedelta(days=90)
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    logger.info(f"Fetching funding rate history for {symbol}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        all_rates = []
        current_start = start_time
        
        while current_start < end_time:
            params = {
                "symbol": symbol,
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 1000,
            }
            
            resp = await client.get(f"{FUTURES_URL}/fapi/v1/fundingRate", params=params)
            resp.raise_for_status()
            rates = resp.json()
            
            if not rates:
                break
            
            all_rates.extend(rates)
            
            # Move to next batch
            last_time = rates[-1]["fundingTime"]
            current_start = datetime.fromtimestamp(last_time / 1000 + 1, tz=timezone.utc)
            
            logger.info(f"Fetched {len(rates)} funding rates, total: {len(all_rates)}")
            await asyncio.sleep(0.5)
        
        df = pd.DataFrame(all_rates)
        df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df["fundingRate"] = df["fundingRate"].astype(float)
        
        logger.info(f"Total funding rates fetched: {len(df)}")
        return df


async def fetch_open_interest_history(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    start_time: datetime = None,
    end_time: datetime = None,
) -> pd.DataFrame:
    """
    Fetch historical open interest from Binance futures API.
    
    Note: Historical OI only available for limited period (~30 days).
    For older data, we'll forward-fill from nearest available timestamp.
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc) - timedelta(days=30)  # Max 30 days
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    logger.info(f"Fetching OI history for {symbol} (limited to 30 days)")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        all_oi = []
        current_start = start_time
        
        while current_start < end_time:
            params = {
                "symbol": symbol,
                "period": interval,
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 500,
            }
            
            try:
                resp = await client.get(f"{FUTURES_URL}/futures/data/openInterestHist", params=params)
                resp.raise_for_status()
                oi_data = resp.json()
                
                if not oi_data:
                    break
                
                all_oi.extend(oi_data)
                
                # Move to next batch
                last_time = oi_data[-1]["timestamp"]
                current_start = datetime.fromtimestamp(last_time / 1000 + 300, tz=timezone.utc)  # +5min
                
                logger.info(f"Fetched {len(oi_data)} OI records, total: {len(all_oi)}")
                await asyncio.sleep(0.5)
            except httpx.HTTPStatusError as e:
                logger.warning(f"OI fetch failed (likely older than 30 days): {e}")
                break
        
        if not all_oi:
            logger.warning("No OI data available for this period")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_oi)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["sumOpenInterest"] = df["sumOpenInterest"].astype(float)
        df["sumOpenInterestValue"] = df["sumOpenInterestValue"].astype(float)
        
        logger.info(f"Total OI records fetched: {len(df)}")
        return df


async def download_all(
    start_date: str = "2026-04-01",
    end_date: str = "2026-06-30",
    symbol: str = "BTCUSDT",
    interval: str = "5m",
):
    """Download all required data and save to parquet files."""
    start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_time = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # 1. OHLCV (spot)
    logger.info("=" * 60)
    logger.info("STEP 1: Downloading OHLCV data")
    logger.info("=" * 60)
    ohlcv_df = await fetch_ohlcv(symbol, interval, start_time, end_time)
    ohlcv_path = OUTPUT_DIR / f"{symbol}_{interval}_ohlcv_{start_date}_{end_date}.parquet"
    ohlcv_df.to_parquet(ohlcv_path, index=False)
    logger.info(f"Saved OHLCV to {ohlcv_path} ({len(ohlcv_df)} rows)")
    
    # 2. Funding rate
    logger.info("=" * 60)
    logger.info("STEP 2: Downloading funding rate history")
    logger.info("=" * 60)
    funding_df = await fetch_funding_rate_history(symbol, start_time, end_time)
    funding_path = OUTPUT_DIR / f"{symbol}_funding_{start_date}_{end_date}.parquet"
    funding_df.to_parquet(funding_path, index=False)
    logger.info(f"Saved funding rate to {funding_path} ({len(funding_df)} rows)")
    
    # 3. Open interest (only last 30 days available)
    logger.info("=" * 60)
    logger.info("STEP 3: Downloading open interest history (max 30 days)")
    logger.info("=" * 60)
    oi_start = max(start_time, datetime.now(timezone.utc) - timedelta(days=30))
    oi_df = await fetch_open_interest_history(symbol, interval, oi_start, end_time)
    if not oi_df.empty:
        oi_path = OUTPUT_DIR / f"{symbol}_oi_{interval}_{oi_start.date()}_{end_time.date()}.parquet"
        oi_df.to_parquet(oi_path, index=False)
        logger.info(f"Saved OI to {oi_path} ({len(oi_df)} rows)")
    else:
        logger.warning("No OI data saved (unavailable for this period)")
    
    # 4. Save metadata
    metadata = {
        "symbol": symbol,
        "interval": interval,
        "start_date": start_date,
        "end_date": end_date,
        "ohlcv_rows": len(ohlcv_df),
        "funding_rows": len(funding_df),
        "oi_rows": len(oi_df) if not oi_df.empty else 0,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = OUTPUT_DIR / f"metadata_{start_date}_{end_date}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Saved metadata to {metadata_path}")
    
    logger.info("=" * 60)
    logger.info("✅ DOWNLOAD COMPLETE")
    logger.info("=" * 60)
    logger.info(f"OHLCV: {len(ohlcv_df):,} candles")
    logger.info(f"Funding: {len(funding_df):,} snapshots")
    logger.info(f"OI: {len(oi_df):,} records" if not oi_df.empty else "OI: N/A")
    logger.info(f"Output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Download historical BTC data for backtesting")
    parser.add_argument("--start", default="2026-04-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-06-30", help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol to download")
    parser.add_argument("--interval", default="5m", help="Candle interval (1m, 5m, 15m)")
    
    args = parser.parse_args()
    
    asyncio.run(download_all(args.start, args.end, args.symbol, args.interval))
