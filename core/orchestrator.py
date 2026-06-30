"""
orchestrator.py — 4-agent linear pipeline with real data integration.

Pipeline: Market&Sentiment -> Research -> Trader -> Risk&Portfolio Manager

Before each cycle:
  1. Fetch real BTC data from Binance (OHLCV, orderbook, funding, OI)
  2. Fetch liquidation data from WebSocket buffer
  3. Check circuit breaker (daily loss limit, consecutive losses)
  4. Build market_context string for Market Analyst

After each cycle:
  1. Record to database (cycle history, setup stats)
  2. Return CycleLog for Telegram broadcast
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from core.agent import Agent, AgentTimeoutError, AgentAPIError, AgentVerificationError
from core.schemas import MarketReport, ResearchPlan, TraderProposal, PortfolioDecision, CycleLog

logger = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self, binance_client=None, polymarket_client=None,
                 liquidation_tracker=None, database=None):
        # Data clients (injected, optional for backward compat)
        self.binance = binance_client
        self.polymarket = polymarket_client
        self.liq_tracker = liquidation_tracker
        self.db = database

        # LLM agents
        self.market_analyst = Agent(
            "Market & Sentiment Analyst", "01-market-sentiment-analyst.soul.md",
            output_schema=MarketReport, timeout_s=120
        )
        self.research_agent = Agent(
            "Research Agent", "02-research-agent.soul.md",
            output_schema=ResearchPlan, timeout_s=120
        )
        self.trader = Agent(
            "Trader Agent", "03-trader-agent.soul.md",
            output_schema=TraderProposal, timeout_s=120
        )
        self.risk_pm = Agent(
            "Risk & Portfolio Manager", "04-risk-portfolio-manager.soul.md",
            output_schema=PortfolioDecision, timeout_s=120
        )

    # ------------------------------------------------------------------
    # Data fetching — build market_context from real data
    # ------------------------------------------------------------------
    async def _fetch_market_data(self) -> str:
        """Fetch real BTC data from Binance + liquidation tracker.
        Returns formatted string for Market Analyst soul."""
        sections = []

        # --- Binance data ---
        if self.binance:
            try:
                # OHLCV (last 50 5m candles)
                candles = await self.binance.get_ohlcv(interval="5m", limit=50)
                if candles:
                    last = candles[-1]
                    prev = candles[-2] if len(candles) > 1 else last
                    sections.append(
                        f"## BTC Price Data (5m candles, last 50)\n"
                        f"Current price: ${last['close']:,.2f}\n"
                        f"Last candle: O=${last['open']:,.2f} H=${last['high']:,.2f} "
                        f"L=${last['low']:,.2f} C=${last['close']:,.2f} V={last['volume']:,.2f}\n"
                        f"Previous candle: O=${prev['open']:,.2f} H=${prev['high']:,.2f} "
                        f"L=${prev['low']:,.2f} C=${prev['close']:,.2f}\n"
                        f"Price change last 2 candles: "
                        f"{((last['close'] - prev['close']) / prev['close'] * 100):+.3f}%"
                    )
            except Exception as e:
                logger.warning(f"Binance OHLCV fetch failed: {e}")
                sections.append("## BTC Price Data: UNAVAILABLE (Binance API error)")

            try:
                # Orderbook
                book = await self.binance.get_orderbook_snapshot(limit=20)
                sections.append(
                    f"## Orderbook Snapshot (top 20)\n"
                    f"Best bid: ${book['best_bid']:,.2f} | Best ask: ${book['best_ask']:,.2f}\n"
                    f"Spread: ${book['spread']:,.2f}\n"
                    f"Bid volume: {book['bid_volume']:.3f} BTC | Ask volume: {book['ask_volume']:.3f} BTC\n"
                    f"Bid/Ask imbalance: {book['bid_ask_imbalance']:.3f} "
                    f"({'bid-heavy' if book['bid_ask_imbalance'] > 0.55 else 'ask-heavy' if book['bid_ask_imbalance'] < 0.45 else 'balanced'})"
                )
            except Exception as e:
                logger.warning(f"Binance orderbook fetch failed: {e}")
                sections.append("## Orderbook: UNAVAILABLE")

            try:
                # Funding rate
                funding = await self.binance.get_funding_rate()
                fr_pct = funding['funding_rate'] * 100
                sections.append(
                    f"## Funding Rate & Mark Price\n"
                    f"Funding rate: {fr_pct:+.4f}% "
                    f"({'longs pay shorts — bullish crowding' if fr_pct > 0.01 else 'shorts pay longs — bearish crowding' if fr_pct < -0.01 else 'neutral'})\n"
                    f"Mark price: ${funding['mark_price']:,.2f}\n"
                    f"Index price: ${funding.get('index_price', 0):,.2f}"
                )
            except Exception as e:
                logger.warning(f"Binance funding rate fetch failed: {e}")
                sections.append("## Funding Rate: UNAVAILABLE")

            try:
                # Open interest
                oi = await self.binance.get_open_interest()
                sections.append(
                    f"## Open Interest\n"
                    f"Current OI: {oi['open_interest']:.3f} BTC "
                    f"(${oi['open_interest'] * (candles[-1]['close'] if candles else 0):,.0f})"
                )
            except Exception as e:
                logger.warning(f"Binance OI fetch failed: {e}")
                sections.append("## Open Interest: UNAVAILABLE")

            try:
                # 24h ticker
                ticker = await self.binance.get_ticker_24h()
                sections.append(
                    f"## 24h Stats\n"
                    f"24h change: {ticker['price_change_pct']:+.2f}%\n"
                    f"24h high: ${ticker['high_24h']:,.2f} | 24h low: ${ticker['low_24h']:,.2f}\n"
                    f"24h volume: {ticker['volume_24h']:,.2f} BTC "
                    f"(${ticker['quote_volume_24h']:,.0f})"
                )
            except Exception as e:
                logger.warning(f"Binance ticker fetch failed: {e}")

        # --- Liquidation data ---
        if self.liq_tracker:
            try:
                liq = self.liq_tracker.get_recent(minutes=5)
                if liq["count"] > 0:
                    sections.append(
                        f"## Liquidations (last 5 min)\n"
                        f"Long liquidations: ${liq['long_liquidations_usd']:,.0f}\n"
                        f"Short liquidations: ${liq['short_liquidations_usd']:,.0f}\n"
                        f"Total: ${liq['total_liquidations_usd']:,.0f} ({liq['count']} events)\n"
                        f"{'⚠️ HEAVY LIQUIDATIONS — potential cascade risk' if liq['total_liquidations_usd'] > 5_000_000 else ''}"
                    )
                else:
                    sections.append("## Liquidations (last 5 min)\nNo significant liquidation events.")
            except Exception as e:
                logger.warning(f"Liquidation data fetch failed: {e}")

        if not sections:
            return "⚠️ NO MARKET DATA AVAILABLE — all data sources failed. Recommend SKIP."

        return "\n\n".join(sections)

    async def _check_circuit_breaker(self) -> dict | None:
        """Check circuit breaker before running cycle.
        Returns breaker status dict if trading is blocked, None if OK."""
        if not self.db:
            return None
        try:
            status = await self.db.check_circuit_breaker()
            if not status["trading_allowed"]:
                logger.warning(f"Circuit breaker active: {status['reason']} — {status['details']}")
                return status
            return None
        except Exception as e:
            logger.error(f"Circuit breaker check failed: {e}")
            return None  # fail-open: don't block trading if DB is down

    # ------------------------------------------------------------------
    # Safe agent runner with retry
    # ------------------------------------------------------------------
    async def _safe_run(self, agent: Agent, prompt: str, flags: list, max_retries: int = 1):
        for attempt in range(max_retries + 1):
            try:
                return await agent.run(prompt)
            except (AgentTimeoutError, AgentAPIError, AgentVerificationError) as e:
                logger.warning(f"{agent.name} attempt {attempt+1} failed: {e}")
                if attempt == max_retries:
                    flags.append(f"DEGRADED: {agent.name} — {e}")
                    return {"raw": f"[DEGRADED: {agent.name} failed after {max_retries+1} attempts]",
                            "parsed": None}
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------
    async def run_cycle(self, market_context: str = None) -> CycleLog:
        cycle_id = str(uuid.uuid4())[:8]
        t0 = datetime.now(timezone.utc)
        step_status, latency, flags = {}, {}, []

        # STEP 0: Circuit breaker check
        breaker = await self._check_circuit_breaker()
        if breaker:
            return CycleLog(
                cycle_id=cycle_id, timestamp=t0,
                step_status={"circuit_breaker": "blocked"},
                latency_seconds={"total": 0},
                verification_flags=[f"CIRCUIT BREAKER: {breaker['reason']} — {breaker['details']}"],
                final_decision=None,
                error=f"Trading blocked by circuit breaker: {breaker['reason']}",
            )

        # STEP 0.5: Fetch real market data if no context provided
        if market_context is None:
            market_context = await self._fetch_market_data()

        # STEP 1: Market & Sentiment Analyst
        s1 = asyncio.get_running_loop().time()
        market_result = await self._safe_run(self.market_analyst, market_context, flags)
        latency["step1_market"] = asyncio.get_running_loop().time() - s1
        step_status["step1_market"] = "complete" if market_result["parsed"] else "degraded"

        if not market_result["parsed"]:
            return self._degraded_log(cycle_id, t0, step_status, latency, flags,
                                       "Market analyst failed — cannot proceed safely")

        # STEP 2: Research Agent
        s2 = asyncio.get_running_loop().time()
        research_result = await self._safe_run(
            self.research_agent, f"Market & Sentiment Report:\n{market_result['raw']}", flags)
        latency["step2_research"] = asyncio.get_running_loop().time() - s2
        step_status["step2_research"] = "complete" if research_result["parsed"] else "degraded"

        if not research_result["parsed"]:
            return self._degraded_log(cycle_id, t0, step_status, latency, flags,
                                       "Research agent failed — routing to SKIP")

        # STEP 3: Trader Agent
        s3 = asyncio.get_running_loop().time()
        trader_result = await self._safe_run(
            self.trader,
            f"Research Plan:\n{research_result['raw']}\n\nMarket Report:\n{market_result['raw']}",
            flags
        )
        latency["step3_trader"] = asyncio.get_running_loop().time() - s3
        step_status["step3_trader"] = "complete" if trader_result["parsed"] else "degraded"

        if not trader_result["parsed"]:
            return self._degraded_log(cycle_id, t0, step_status, latency, flags,
                                       "Trader agent failed — routing to SKIP")

        # STEP 4: Risk & Portfolio Manager
        s4 = asyncio.get_running_loop().time()
        pm_result = await self._safe_run(
            self.risk_pm,
            f"Market & Sentiment Report:\n{market_result['raw']}\n\n"
            f"Research Plan:\n{research_result['raw']}\n\n"
            f"Trader Proposal:\n{trader_result['raw']}",
            flags
        )
        latency["step4_risk_pm"] = asyncio.get_running_loop().time() - s4
        step_status["step4_risk_pm"] = "complete" if pm_result["parsed"] else "degraded"

        total = (datetime.now(timezone.utc) - t0).total_seconds()
        latency["total"] = total

        log = CycleLog(
            cycle_id=cycle_id,
            timestamp=t0,
            step_status=step_status,
            latency_seconds=latency,
            verification_flags=flags,
            final_decision=pm_result["parsed"],
            error=None if pm_result["parsed"] else "Risk & Portfolio Manager output failed verification",
        )

        # STEP 5: Record to database
        if self.db and log.final_decision:
            try:
                d = log.final_decision
                market = market_result["parsed"]
                await self.db.record_cycle(
                    cycle_id=cycle_id,
                    timestamp=t0,
                    rating=d.rating.value,
                    confidence=d.confidence,
                    position_size_usd=d.position_size_usd,
                    setup_match=(market.setup_match or "none") if market else "none",
                    confluence_total=market.confluence_total if market else 0,
                )
            except Exception as e:
                logger.error(f"Failed to record cycle to DB: {e}")

        return log

    def _degraded_log(self, cycle_id, t0, step_status, latency, flags, error_msg) -> CycleLog:
        total = (datetime.now(timezone.utc) - t0).total_seconds()
        latency["total"] = total
        return CycleLog(
            cycle_id=cycle_id, timestamp=t0, step_status=step_status,
            latency_seconds=latency, verification_flags=flags,
            final_decision=None, error=error_msg,
        )
