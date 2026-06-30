"""test_orchestrator.py — pipeline tests with mocked agents and data clients."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.agent import AgentTimeoutError, AgentAPIError, AgentVerificationError
from core.orchestrator import Orchestrator
from core.schemas import (
    MarketReport, MarketBias, ResearchPlan, PortfolioRating,
    TraderProposal, TraderAction, PortfolioDecision,
)


def _mock_market_report():
    return MarketReport(
        net_market_bias=MarketBias.BULLISH, confidence=7,
        technical_summary="BTC above 100k, strong momentum",
        positioning_summary="Funding slightly positive, OI rising",
        fast_filter_flags=["FOMC in 2 days"],
        confluence_technical=3, confluence_positioning=2,
        confluence_microstructure=2, confluence_total=7,
        setup_match="A",
    )


def _mock_research_plan():
    return ResearchPlan(
        rating=PortfolioRating.UP, confidence=8,
        bull_case=["Breakout confirmed"], bear_case=["Overbought RSI"],
        strongest_counter_point="RSI divergence on 15m",
        why_it_doesnt_change_call="Higher timeframe trend intact",
        reasoning="Bullish bias with strong confluence",
    )


def _mock_trader_proposal():
    return TraderProposal(
        action=TraderAction.UP, confidence=7,
        reasoning="Good entry at pullback",
        entry_price=100000.0, expected_move_pct=0.5,
        position_size_usd=500.0, max_loss_usd=100.0,
        market_odds=0.55, expected_value=0.12,
    )


def _mock_portfolio_decision():
    return PortfolioDecision(
        rating=PortfolioRating.LEAN_UP, confidence=6,
        position_size_usd=200.0, expected_value=0.08,
        risk_reward_ratio=2.5,
        aggressive_case="Full 2% risk",
        conservative_case="Half size",
        neutral_sizing_case="Standard",
        reasoning="Moderate conviction",
        warnings=[],
    )


def _make_orchestrator():
    """Create orchestrator with all agents mocked."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.binance = None
    orch.polymarket = None
    orch.liq_tracker = None
    orch.db = None

    # Mock all 4 agents
    orch.market_analyst = MagicMock()
    orch.research_agent = MagicMock()
    orch.trader = MagicMock()
    orch.risk_pm = MagicMock()

    return orch


class TestOrchestratorPipeline:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """All agents return valid output — should complete with PortfolioDecision."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(return_value={
            "raw": "market report", "parsed": _mock_market_report()
        })
        orch.research_agent.run = AsyncMock(return_value={
            "raw": "research plan", "parsed": _mock_research_plan()
        })
        orch.trader.run = AsyncMock(return_value={
            "raw": "trader proposal", "parsed": _mock_trader_proposal()
        })
        orch.risk_pm.run = AsyncMock(return_value={
            "raw": "portfolio decision", "parsed": _mock_portfolio_decision()
        })

        log = await orch.run_cycle("test market context")
        assert log.error is None
        assert log.final_decision is not None
        assert log.final_decision.rating == PortfolioRating.LEAN_UP
        assert log.step_status["step1_market"] == "complete"
        assert log.step_status["step2_research"] == "complete"
        assert log.step_status["step3_trader"] == "complete"
        assert log.step_status["step4_risk_pm"] == "complete"

    @pytest.mark.asyncio
    async def test_market_analyst_fails(self):
        """Step 1 fails — pipeline should short-circuit with error."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(
            side_effect=AgentTimeoutError("timeout")
        )
        orch.research_agent.run = AsyncMock()
        orch.trader.run = AsyncMock()
        orch.risk_pm.run = AsyncMock()

        log = await orch.run_cycle("test context")
        assert log.final_decision is None
        assert log.error is not None
        assert "Market analyst" in log.error
        # Subsequent agents should NOT have been called
        orch.research_agent.run.assert_not_called()
        orch.trader.run.assert_not_called()
        orch.risk_pm.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_research_agent_fails(self):
        """Step 2 fails — pipeline should stop, not continue to trader."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(return_value={
            "raw": "market", "parsed": _mock_market_report()
        })
        orch.research_agent.run = AsyncMock(side_effect=AgentAPIError("API error"))
        orch.trader.run = AsyncMock()
        orch.risk_pm.run = AsyncMock()

        log = await orch.run_cycle("test context")
        assert log.final_decision is None
        assert "Research agent" in log.error
        orch.trader.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_trader_fails(self):
        """Step 3 fails — pipeline should stop at trader."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(return_value={
            "raw": "market", "parsed": _mock_market_report()
        })
        orch.research_agent.run = AsyncMock(return_value={
            "raw": "research", "parsed": _mock_research_plan()
        })
        orch.trader.run = AsyncMock(side_effect=AgentTimeoutError("timeout"))
        orch.risk_pm.run = AsyncMock()

        log = await orch.run_cycle("test context")
        assert log.final_decision is None
        assert "Trader" in log.error
        orch.risk_pm.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_risk_pm_fails(self):
        """Step 4 fails — should return degraded log with error."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(return_value={
            "raw": "market", "parsed": _mock_market_report()
        })
        orch.research_agent.run = AsyncMock(return_value={
            "raw": "research", "parsed": _mock_research_plan()
        })
        orch.trader.run = AsyncMock(return_value={
            "raw": "trader", "parsed": _mock_trader_proposal()
        })
        orch.risk_pm.run = AsyncMock(side_effect=AgentVerificationError("verification failed"))

        log = await orch.run_cycle("test context")
        assert log.final_decision is None
        assert log.error is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks(self):
        """Circuit breaker active — should skip entire pipeline."""
        orch = _make_orchestrator()
        mock_db = AsyncMock()
        mock_db.check_circuit_breaker.return_value = {
            "trading_allowed": False,
            "reason": "daily_loss_limit_hit",
            "details": "Loss $700 >= limit $600",
        }
        orch.db = mock_db

        log = await orch.run_cycle("test context")
        assert log.final_decision is None
        assert "circuit breaker" in log.error.lower()
        orch.market_analyst.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_cycle_recorded_to_db(self):
        """Completed cycle should be recorded to database."""
        orch = _make_orchestrator()
        orch.market_analyst.run = AsyncMock(return_value={
            "raw": "market", "parsed": _mock_market_report()
        })
        orch.research_agent.run = AsyncMock(return_value={
            "raw": "research", "parsed": _mock_research_plan()
        })
        orch.trader.run = AsyncMock(return_value={
            "raw": "trader", "parsed": _mock_trader_proposal()
        })
        orch.risk_pm.run = AsyncMock(return_value={
            "raw": "pm", "parsed": _mock_portfolio_decision()
        })

        mock_db = AsyncMock()
        mock_db.check_circuit_breaker.return_value = {"trading_allowed": True}
        mock_db.record_cycle = AsyncMock()
        orch.db = mock_db

        log = await orch.run_cycle("test context")
        assert log.final_decision is not None
        mock_db.record_cycle.assert_called_once()
        call_kwargs = mock_db.record_cycle.call_args[1]
        assert call_kwargs["rating"] == "LEAN_UP"
        assert call_kwargs["setup_match"] == "A"
        assert call_kwargs["confluence_total"] == 7
