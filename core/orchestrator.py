"""
orchestrator.py — versi minimal (4 agent, linear pipeline, no parallel wave needed).
Market&Sentiment -> Research -> Trader -> Risk&Portfolio Manager
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from core.agent import Agent, AgentTimeoutError, AgentVerificationError
from core.schemas import MarketReport, ResearchPlan, TraderProposal, PortfolioDecision, CycleLog

logger = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self):
        self.market_analyst = Agent(
            "Market & Sentiment Analyst", "01-market-sentiment-analyst.soul.md",
            output_schema=MarketReport, timeout_s=30
        )
        self.research_agent = Agent(
            "Research Agent", "02-research-agent.soul.md",
            output_schema=ResearchPlan, timeout_s=30
        )
        self.trader = Agent(
            "Trader Agent", "03-trader-agent.soul.md",
            output_schema=TraderProposal, timeout_s=30
        )
        self.risk_pm = Agent(
            "Risk & Portfolio Manager", "04-risk-portfolio-manager.soul.md",
            output_schema=PortfolioDecision, timeout_s=30
        )

    async def _safe_run(self, agent: Agent, prompt: str, flags: list, max_retries: int = 1):
        for attempt in range(max_retries + 1):
            try:
                return await agent.run(prompt)
            except (AgentTimeoutError, AgentVerificationError) as e:
                logger.warning(f"{agent.name} attempt {attempt+1} failed: {e}")
                if attempt == max_retries:
                    flags.append(f"DEGRADED: {agent.name} — {e}")
                    return {"raw": f"[DEGRADED: {agent.name} failed after {max_retries+1} attempts]",
                            "parsed": None}
                await asyncio.sleep(1)

    async def run_cycle(self, market_context: str) -> CycleLog:
        cycle_id = str(uuid.uuid4())[:8]
        t0 = datetime.now(timezone.utc)
        step_status, latency, flags = {}, {}, []

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

        return CycleLog(
            cycle_id=cycle_id,
            timestamp=t0,
            step_status=step_status,
            latency_seconds=latency,
            verification_flags=flags,
            final_decision=pm_result["parsed"],
            error=None if pm_result["parsed"] else "Risk & Portfolio Manager output failed verification",
        )

    def _degraded_log(self, cycle_id, t0, step_status, latency, flags, error_msg) -> CycleLog:
        total = (datetime.now(timezone.utc) - t0).total_seconds()
        latency["total"] = total
        return CycleLog(
            cycle_id=cycle_id, timestamp=t0, step_status=step_status,
            latency_seconds=latency, verification_flags=flags,
            final_decision=None, error=error_msg,
        )
