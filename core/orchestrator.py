"""
orchestrator.py — implementasi "Hale" (00-orchestrator.soul.md) secara teknis.
Decompose -> Dispatch -> Execute (w/ timeout) -> Verify -> Refine/Re-run -> Handoff
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from core.agent import Agent, AgentTimeoutError, AgentVerificationError
from core.schemas import (
    SentimentReport, TraderProposal, ResearchPlan, PortfolioDecision, CycleLog
)

logger = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self):
        # Wave 1 — parallel analysts
        self.price_analyst = Agent("BTC Price Analyst", "01-btc-price-analyst.soul.md", timeout_s=30)
        self.sentiment_analyst = Agent("Sentiment Analyst", "02-sentiment-analyst.soul.md",
                                        output_schema=SentimentReport, timeout_s=30)
        self.news_analyst = Agent("News Analyst", "03-news-analyst.soul.md", timeout_s=30)
        self.onchain_analyst = Agent("On-Chain Analyst", "04-onchain-analyst.soul.md", timeout_s=30)

        # Wave 2 — debate
        self.bull = Agent("Bull Researcher", "05-bull-researcher.soul.md", timeout_s=30)
        self.bear = Agent("Bear Researcher", "06-bear-researcher.soul.md", timeout_s=30)

        # Wave 3-4
        self.research_manager = Agent("Research Manager", "07-research-manager.soul.md",
                                       output_schema=ResearchPlan, timeout_s=30)
        self.trader = Agent("Trader Agent", "08-trader-agent.soul.md",
                             output_schema=TraderProposal, timeout_s=30)

        # Wave 5 — risk debate
        self.risk_aggressive = Agent("Aggressive Risk", "09-aggressive-risk-analyst.soul.md", timeout_s=30)
        self.risk_conservative = Agent("Conservative Risk", "10-conservative-risk-analyst.soul.md", timeout_s=30)
        self.risk_neutral = Agent("Neutral Risk", "11-neutral-risk-analyst.soul.md", timeout_s=30)

        # Wave 6
        self.portfolio_manager = Agent("Portfolio Manager", "12-portfolio-manager.soul.md",
                                        output_schema=PortfolioDecision, timeout_s=30)

    async def _safe_run(self, agent: Agent, prompt: str, flags: list, max_retries: int = 1):
        """Wrapper verify-gate: retry sekali kalau timeout/verification fail, else flag degraded."""
        for attempt in range(max_retries + 1):
            try:
                return await agent.run(prompt)
            except (AgentTimeoutError, AgentVerificationError) as e:
                logger.warning(f"{agent.name} attempt {attempt+1} failed: {e}")
                if attempt == max_retries:
                    flags.append(f"DEGRADED: {agent.name} — {e}")
                    return {"raw": f"[MISSING/STALE: {agent.name} failed after {max_retries+1} attempts]",
                            "parsed": None}
                await asyncio.sleep(1)

    async def run_cycle(self, market_context: str) -> CycleLog:
        cycle_id = str(uuid.uuid4())[:8]
        t0 = datetime.now(timezone.utc)
        # Note: dq_flags/verify_flags are safe to .append() from parallel coroutines
        # because asyncio is single-threaded — list.append() is atomic in this context.
        wave_status, latency, verify_flags, dq_flags = {}, {}, [], []

        # ---- WAVE 1: parallel analysts ----
        w1_start = asyncio.get_running_loop().time()
        price_r, sent_r, news_r, chain_r = await asyncio.gather(
            self._safe_run(self.price_analyst, market_context, dq_flags),
            self._safe_run(self.sentiment_analyst, market_context, dq_flags),
            self._safe_run(self.news_analyst, market_context, dq_flags),
            self._safe_run(self.onchain_analyst, market_context, dq_flags),
        )
        latency["wave1"] = asyncio.get_running_loop().time() - w1_start
        wave_status["wave1"] = "degraded" if any("DEGRADED" in f for f in dq_flags) else "complete"

        analyst_bundle = (
            f"Price Report:\n{price_r['raw']}\n\n"
            f"Sentiment Report:\n{sent_r['raw']}\n\n"
            f"News Report:\n{news_r['raw']}\n\n"
            f"On-Chain Report:\n{chain_r['raw']}"
        )

        # ---- WAVE 2: bull/bear debate (2 rounds) ----
        w2_start = asyncio.get_running_loop().time()
        debate_history = ""
        for round_n in range(2):
            bull_r = await self._safe_run(
                self.bull, f"{analyst_bundle}\n\nDebate history:\n{debate_history}", dq_flags)
            debate_history += f"\n[Round {round_n+1}] BULL: {bull_r['raw']}"
            bear_r = await self._safe_run(
                self.bear, f"{analyst_bundle}\n\nDebate history:\n{debate_history}", dq_flags)
            debate_history += f"\n[Round {round_n+1}] BEAR: {bear_r['raw']}"
        latency["wave2"] = asyncio.get_running_loop().time() - w2_start
        wave_status["wave2"] = "complete"

        # ---- WAVE 3: research manager ----
        w3_start = asyncio.get_running_loop().time()
        rm_result = await self._safe_run(
            self.research_manager, f"Debate history:\n{debate_history}", verify_flags)
        latency["wave3"] = asyncio.get_running_loop().time() - w3_start
        wave_status["wave3"] = "complete" if rm_result["parsed"] else "degraded"

        # ---- WAVE 4: trader ----
        w4_start = asyncio.get_running_loop().time()
        trader_result = await self._safe_run(
            self.trader,
            f"Research plan:\n{rm_result['raw']}\n\nAnalyst reports:\n{analyst_bundle}",
            verify_flags
        )
        latency["wave4"] = asyncio.get_running_loop().time() - w4_start
        wave_status["wave4"] = "complete" if trader_result["parsed"] else "degraded"

        # ---- WAVE 5: risk debate (2 rounds, 3-way) ----
        w5_start = asyncio.get_running_loop().time()
        risk_history = ""
        for round_n in range(2):
            agg_r = await self._safe_run(
                self.risk_aggressive, f"Trader decision:\n{trader_result['raw']}\n\nHistory:\n{risk_history}", dq_flags)
            risk_history += f"\n[R{round_n+1}] AGGRESSIVE: {agg_r['raw']}"
            con_r = await self._safe_run(
                self.risk_conservative, f"Trader decision:\n{trader_result['raw']}\n\nHistory:\n{risk_history}", dq_flags)
            risk_history += f"\n[R{round_n+1}] CONSERVATIVE: {con_r['raw']}"
            neu_r = await self._safe_run(
                self.risk_neutral, f"Trader decision:\n{trader_result['raw']}\n\nHistory:\n{risk_history}", dq_flags)
            risk_history += f"\n[R{round_n+1}] NEUTRAL: {neu_r['raw']}"
        latency["wave5"] = asyncio.get_running_loop().time() - w5_start
        wave_status["wave5"] = "complete"

        # ---- WAVE 6: portfolio manager (final decision) ----
        w6_start = asyncio.get_running_loop().time()
        pm_result = await self._safe_run(
            self.portfolio_manager,
            f"Research plan:\n{rm_result['raw']}\n\nTrader plan:\n{trader_result['raw']}\n\n"
            f"Risk debate history:\n{risk_history}",
            verify_flags
        )
        latency["wave6"] = asyncio.get_running_loop().time() - w6_start
        wave_status["wave6"] = "complete" if pm_result["parsed"] else "degraded"

        total_latency = (datetime.now(timezone.utc) - t0).total_seconds()
        latency["total"] = total_latency

        return CycleLog(
            cycle_id=cycle_id,
            timestamp=t0,
            wave_status=wave_status,
            latency_seconds=latency,
            verification_flags=verify_flags,
            data_quality_flags=dq_flags,
            final_decision=pm_result["parsed"],
            error=None if pm_result["parsed"] else "Portfolio Manager output failed verification",
        )
