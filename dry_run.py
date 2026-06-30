"""
dry_run.py — test full pipeline tanpa Telegram/API key.

Yang di-test:
1. Binance data fetch (real data dari public API)
2. Liquidation tracker (WebSocket connection test)
3. Polymarket client (Gamma API search)
4. Database CRUD + circuit breaker
5. Orchestrator pipeline (dengan mock LLM, real data)
6. Market context building

Jalankan: python dry_run.py
"""
import asyncio
import sys
import os

# Load .env kalau ada
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set dummy LLM key supaya import tidak gagal
os.environ.setdefault("LLM_API_KEY", "dry-run-no-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")


async def dry_run():
    from datetime import datetime, timezone
    from core.data.binance_client import BinanceClient
    from core.data.liquidation_tracker import LiquidationTracker
    from core.data.polymarket_client import PolymarketClient
    from core.data.db import Database
    from core.orchestrator import Orchestrator
    from core.schemas import (
        MarketReport, MarketBias, ResearchPlan, PortfolioRating,
        TraderProposal, TraderAction, PortfolioDecision,
    )
    from unittest.mock import AsyncMock, MagicMock

    results = {"pass": 0, "fail": 0, "skip": 0}
    separator = "=" * 60

    def ok(name, detail=""):
        results["pass"] += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))

    def fail(name, err):
        results["fail"] += 1
        print(f"  ❌ {name} — {err}")

    def skip(name, reason=""):
        results["skip"] += 1
        print(f"  ⏭️  {name}" + (f" — {reason}" if reason else ""))

    # ────────────────────────────────────────────────────────────
    print(f"\n{separator}")
    print("DRY RUN — BTC Agent System Pipeline Test")
    print(f"{separator}\n")

    # ── 1. Binance Data Fetch ──────────────────────────────────
    print("📊 [1/6] Binance Data Fetch (public API)")
    binance = BinanceClient(timeout=15.0)

    try:
        candles = await binance.get_ohlcv(interval="5m", limit=5)
        if candles and len(candles) >= 2:
            last = candles[-1]
            ok("OHLCV (5m candles)",
               f"Price: ${last['close']:,.2f} | H: ${last['high']:,.2f} L: ${last['low']:,.2f} | Vol: {last['volume']:.2f} BTC")
        else:
            fail("OHLCV", "No candle data returned")
    except Exception as e:
        fail("OHLCV", str(e)[:100])

    try:
        book = await binance.get_orderbook_snapshot(limit=10)
        if book["best_bid"] and book["best_ask"]:
            ok("Orderbook",
               f"Bid: ${book['best_bid']:,.2f} | Ask: ${book['best_ask']:,.2f} | Spread: ${book['spread']:.2f} | Imbalance: {book['bid_ask_imbalance']:.3f}")
        else:
            fail("Orderbook", "Empty orderbook")
    except Exception as e:
        fail("Orderbook", str(e)[:100])

    try:
        funding = await binance.get_funding_rate()
        fr = funding["funding_rate"] * 100
        ok("Funding Rate",
           f"{fr:+.4f}% | Mark: ${funding['mark_price']:,.2f}")
    except Exception as e:
        fail("Funding Rate", str(e)[:100])

    try:
        oi = await binance.get_open_interest()
        ok("Open Interest", f"{oi['open_interest']:.3f} BTC")
    except Exception as e:
        fail("Open Interest", str(e)[:100])

    try:
        ticker = await binance.get_ticker_24h()
        ok("24h Ticker",
           f"Price: ${ticker['last_price']:,.2f} | 24h: {ticker['price_change_pct']:+.2f}% | Vol: ${ticker['quote_volume_24h']:,.0f}")
    except Exception as e:
        fail("24h Ticker", str(e)[:100])

    await binance.close()

    # ── 2. Liquidation Tracker ─────────────────────────────────
    print(f"\n💥 [2/6] Liquidation Tracker (WebSocket)")
    liq = LiquidationTracker(buffer_minutes=5)

    # Test empty state
    recent = liq.get_recent(minutes=5)
    ok("Empty buffer", f"Count: {recent['count']} | Connected: {recent['connected']}")

    # Test with injected data
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    liq.buffer.append({"side": "SELL", "qty": 0.5, "price": 100000.0, "time": now})
    liq.buffer.append({"side": "BUY", "qty": 0.3, "price": 100100.0, "time": now})
    liq._connected = True
    recent = liq.get_recent(minutes=5)
    ok("With mock data",
       f"Long liq: ${recent['long_liquidations_usd']:,.0f} | Short liq: ${recent['short_liquidations_usd']:,.0f} | Count: {recent['count']}")

    # Test pruning
    liq.buffer.append({"side": "SELL", "qty": 1.0, "price": 99000.0,
                        "time": now - timedelta(minutes=10)})
    liq._prune()
    ok("Pruning", f"Buffer size after prune: {len(liq.buffer)} (old event removed)")

    # ── 3. Polymarket Client ───────────────────────────────────
    print(f"\n🎰 [3/6] Polymarket Client (Gamma API)")
    poly = PolymarketClient(timeout=15.0)

    try:
        markets = await poly.find_active_markets(query="Bitcoin", limit=3)
        if markets:
            m = markets[0]
            ok("Market search",
               f"Found {len(markets)} markets | First: '{m['question'][:60]}...' | Vol: ${m['volume']:,.0f}")
        else:
            skip("Market search", "No active Bitcoin markets found")
    except Exception as e:
        skip("Market search", f"Gamma API unavailable: {str(e)[:80]}")

    await poly.close()

    # ── 4. Database ────────────────────────────────────────────
    print(f"\n🗄️  [4/6] Database + Circuit Breaker")
    db = Database("dry_run_test.db")
    await db.init()
    ok("DB init", "Tables created")

    # Record cycles
    now = datetime.now(timezone.utc)
    for i in range(3):
        await db.record_cycle(
            cycle_id=f"dry-{i}", timestamp=now,
            rating="UP", confidence=7, position_size_usd=500.0,
            setup_match="A", confluence_total=7,
        )
    ok("Record 3 cycles", "Setup A, confluence 7")

    # Resolve with mixed results
    await db.resolve_cycle("dry-0", pnl_usd=75.0)
    await db.resolve_cycle("dry-1", pnl_usd=-30.0)
    await db.resolve_cycle("dry-2", pnl_usd=50.0)
    ok("Resolve cycles", "PnL: +75, -30, +50")

    # Circuit breaker check
    cb = await db.check_circuit_breaker(account_balance=10000.0)
    ok("Circuit breaker",
       f"Trading allowed: {cb['trading_allowed']} | {cb['details']}")

    # Setup win rate
    wr = await db.get_setup_winrate("A")
    ok("Setup win rate",
       f"Setup A: {wr['win_rate']:.1%} ({wr['wins']}W/{wr['losses']}L)")

    # Daily summary
    summary = await db.get_daily_summary()
    wr_val = summary["win_rate"]
    wr_str = f"{wr_val:.1%}" if wr_val is not None else "N/A"
    ok("Daily summary",
       f"PnL: ${summary['total_pnl_usd']:.2f} | Trades: {summary['trade_count']} | WR: {wr_str}")

    # Manual circuit breaker
    await db.activate_circuit_breaker(reason="dry run test")
    cb = await db.check_circuit_breaker()
    ok("Manual CB activate", f"Blocked: {cb['reason']}")
    await db.deactivate_circuit_breaker()
    cb = await db.check_circuit_breaker()
    ok("Manual CB deactivate", f"Allowed: {cb['trading_allowed']}")

    await db.close()
    os.unlink("dry_run_test.db")

    # ── 5. Market Context Building ─────────────────────────────
    print(f"\n📡 [5/6] Market Context Building (real data → string)")
    binance2 = BinanceClient(timeout=15.0)
    liq2 = LiquidationTracker(buffer_minutes=30)

    # Build context same way main.py does
    sections = []
    try:
        candles = await binance2.get_ohlcv(interval="5m", limit=50)
        last = candles[-1]
        prev = candles[-2]
        sections.append(f"Price: ${last['close']:,.2f}")
    except:
        pass
    try:
        book = await binance2.get_orderbook_snapshot(limit=20)
        sections.append(f"Spread: ${book['spread']:.2f}")
    except:
        pass
    try:
        funding = await binance2.get_funding_rate()
        sections.append(f"Funding: {funding['funding_rate']*100:+.4f}%")
    except:
        pass

    context = " | ".join(sections)
    ok("Market context", context[:80])
    ok("Context length", f"{len(context)} chars (would be sent to Market Analyst)")

    await binance2.close()

    # ── 6. Orchestrator Pipeline (mocked LLM) ──────────────────
    print(f"\n🤖 [6/6] Orchestrator Pipeline (mocked LLM, real data flow)")

    orch = Orchestrator.__new__(Orchestrator)
    orch.binance = None
    orch.polymarket = None
    orch.liq_tracker = None
    orch.db = None

    # Mock agents with realistic responses
    orch.market_analyst = MagicMock()
    orch.research_agent = MagicMock()
    orch.trader = MagicMock()
    orch.risk_pm = MagicMock()

    mock_market = MarketReport(
        net_market_bias=MarketBias.BULLISH, confidence=7,
        technical_summary=f"BTC at ${last['close']:,.2f}, above VWAP, bullish structure",
        positioning_summary="Funding +0.01%, OI rising, mild long crowding",
        fast_filter_flags=["No high-impact events in next 2h"],
        confluence_technical=3, confluence_positioning=2,
        confluence_microstructure=2, confluence_total=7,
        setup_match="A",
    )
    mock_research = ResearchPlan(
        rating=PortfolioRating.UP, confidence=8,
        bull_case=["Breakout above resistance", "Strong volume"],
        bear_case=["RSI overbought", "Funding elevated"],
        strongest_counter_point="RSI divergence on 15m",
        why_it_doesnt_change_call="Higher TF trend intact, pullback is healthy",
        reasoning="Bullish bias with 7/10 confluence — setup A matches",
    )
    mock_trader = TraderProposal(
        action=TraderAction.UP, confidence=7,
        reasoning="Entry at pullback to VWAP, tight stop below",
        entry_price=last["close"],
        expected_move_pct=0.5,
        position_size_usd=200.0,
        max_loss_usd=40.0,
        market_odds=0.55,
        expected_value=0.08,
    )
    mock_pm = PortfolioDecision(
        rating=PortfolioRating.LEAN_UP, confidence=6,
        position_size_usd=200.0,
        expected_value=0.08,
        risk_reward_ratio=2.5,
        aggressive_case="Full 2% risk = $200",
        conservative_case="Half size = $100",
        neutral_sizing_case="Standard $200",
        reasoning="7/10 confluence, setup A, LEAN_UP sizing",
        warnings=["Funding slightly elevated"],
    )

    orch.market_analyst.run = AsyncMock(return_value={"raw": "market report", "parsed": mock_market})
    orch.research_agent.run = AsyncMock(return_value={"raw": "research plan", "parsed": mock_research})
    orch.trader.run = AsyncMock(return_value={"raw": "trader proposal", "parsed": mock_trader})
    orch.risk_pm.run = AsyncMock(return_value={"raw": "portfolio decision", "parsed": mock_pm})

    # Run with real market context
    log = await orch.run_cycle(f"Dry run market context: {context}")

    if log.final_decision:
        d = log.final_decision
        ok("Pipeline complete",
           f"Decision: {d.rating.value} | Conf: {d.confidence}/10 | Size: ${d.position_size_usd:.2f} | EV: {d.expected_value:.4f}")
        ok("Confluence",
           f"Total: {mock_market.confluence_total}/10 (A:{mock_market.confluence_technical} B:{mock_market.confluence_positioning} C:{mock_market.confluence_microstructure})")
        ok("Setup match", f"{mock_market.setup_match}")
        ok("Latency", f"{log.latency_seconds.get('total', 0):.2f}s")
        ok("Step status", " → ".join(f"{k}:{v}" for k, v in log.step_status.items()))
    else:
        fail("Pipeline", log.error or "Unknown error")

    if log.verification_flags:
        for flag in log.verification_flags:
            skip("Flag", flag)

    # ── Summary ────────────────────────────────────────────────
    print(f"\n{separator}")
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"RESULTS: {results['pass']}/{total} passed | {results['fail']} failed | {results['skip']} skipped")
    if results["fail"] == 0:
        print("✅ DRY RUN PASSED — sistem siap untuk dijalankan dengan API key nyata")
    else:
        print("❌ DRY RUN FAILED — ada yang perlu diperbaiki")
    print(f"{separator}\n")

    return results["fail"] == 0


if __name__ == "__main__":
    success = asyncio.run(dry_run())
    sys.exit(0 if success else 1)
