"""test_live.py — test real LLM connection with Binance data."""
import asyncio
import os
import json
from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("LLM_API_KEY", os.getenv("LLM_API_KEY", ""))

async def test_live():
    from core.data.binance_client import BinanceClient
    from core.data.db import Database
    from core.orchestrator import Orchestrator

    print("=" * 60)
    print("LIVE TEST — Real LLM + Real Binance Data")
    print("=" * 60)

    # 1. Fetch real data
    print("\n📊 Fetching Binance data...")
    binance = BinanceClient(timeout=15.0)
    candles = await binance.get_ohlcv(interval="5m", limit=50)
    book = await binance.get_orderbook_snapshot(limit=20)
    funding = await binance.get_funding_rate()
    oi = await binance.get_open_interest()
    ticker = await binance.get_ticker_24h()
    await binance.close()

    last = candles[-1]
    prev = candles[-2]
    market_context = f"""## BTC Price Data (5m candles, last 50)
Current price: ${last['close']:,.2f}
Last candle: O=${last['open']:,.2f} H=${last['high']:,.2f} L=${last['low']:,.2f} C=${last['close']:,.2f} Vol={last['volume']:.2f}
Previous candle: O=${prev['open']:,.2f} H=${prev['high']:,.2f} L=${prev['low']:,.2f} C=${prev['close']:,.2f}
Change: {((last['close'] - prev['close']) / prev['close'] * 100):+.3f}%

## Orderbook (top 20)
Bid: ${book['best_bid']:,.2f} | Ask: ${book['best_ask']:,.2f}
Spread: ${book['spread']:.2f}
Bid vol: {book['bid_volume']:.3f} BTC | Ask vol: {book['ask_volume']:.3f} BTC
Imbalance: {book['bid_ask_imbalance']:.3f} ({'bid-heavy' if book['bid_ask_imbalance'] > 0.55 else 'ask-heavy' if book['bid_ask_imbalance'] < 0.45 else 'balanced'})

## Funding Rate
Rate: {funding['funding_rate']*100:+.4f}% | Mark: ${funding['mark_price']:,.2f}

## Open Interest
{oi['open_interest']:.3f} BTC

## 24h Stats
Change: {ticker['price_change_pct']:+.2f}%
High: ${ticker['high_24h']:,.2f} | Low: ${ticker['low_24h']:,.2f}
Volume: ${ticker['quote_volume_24h']:,.0f}"""

    print(f"Price: ${last['close']:,.2f}")
    print(f"Funding: {funding['funding_rate']*100:+.4f}%")
    print(f"OI: {oi['open_interest']:.3f} BTC")

    # 2. Run full pipeline with real LLM
    print("\n🤖 Running pipeline with real LLM (Xiaomi MiMo v2.5 Pro via OpenRouter)...")
    
    db = Database("test_live.db")
    await db.init()
    
    orch = Orchestrator(database=db)
    
    log = await orch.run_cycle(market_context)
    
    print(f"\n{'='*60}")
    print(f"Cycle ID: {log.cycle_id}")
    print(f"Latency: {log.latency_seconds.get('total', 0):.1f}s")
    print(f"Steps: {' → '.join(f'{k}:{v}' for k, v in log.step_status.items())}")
    
    if log.final_decision:
        d = log.final_decision
        print(f"\n✅ DECISION: {d.rating.value}")
        print(f"   Confidence: {d.confidence}/10")
        print(f"   Position size: ${d.position_size_usd:,.2f}")
        print(f"   EV: {d.expected_value:.4f}")
        print(f"   Risk/Reward: {d.risk_reward_ratio:.2f}")
        print(f"   Aggressive: {d.aggressive_case[:80]}")
        print(f"   Conservative: {d.conservative_case[:80]}")
        print(f"   Reasoning: {d.reasoning[:200]}")
        if d.warnings:
            print(f"   Warnings: {d.warnings}")
    else:
        print(f"\n❌ ERROR: {log.error}")
    
    if log.verification_flags:
        print(f"\n⚠️ Flags:")
        for f in log.verification_flags:
            print(f"   - {f}")
    
    await db.close()
    print(f"\n{'='*60}")
    print("LIVE TEST COMPLETE")

asyncio.run(test_live())
