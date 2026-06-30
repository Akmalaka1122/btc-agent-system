"""
test_playbook_enforcement.py — Tests for Trading Playbook enforcement gates.

Tests the programmatic enforcement of:
- Confluence threshold (≥6 required)
- Disqualifiers (any active = forced SKIP)
- 2% position size cap
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from core.orchestrator import Orchestrator
from core.schemas import MarketReport, MarketBias, PortfolioDecision, PortfolioRating


@pytest.mark.asyncio
class TestPlaybookEnforcement:
    """Test that Trading Playbook rules are enforced programmatically."""

    @pytest.fixture
    def orchestrator(self):
        """Orchestrator with mocked agents."""
        orch = Orchestrator()
        # Mock _fetch_market_data to avoid real API calls
        orch._fetch_market_data = AsyncMock(return_value="Mock market data")
        return orch

    async def test_confluence_below_threshold_forces_skip(self, orchestrator):
        """Confluence <6 should force SKIP before Research Agent runs."""
        # Mock Market Analyst to return confluence=5 (below threshold)
        low_confluence_report = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=8,
            technical_summary="Strong uptrend",
            positioning_summary="Neutral funding",
            fast_filter_flags=[],
            confluence_technical=2,
            confluence_positioning=2,
            confluence_microstructure=1,
            confluence_total=5,  # Below threshold of 6
            disqualifiers_active=[],
            setup_match="A",
        )
        orchestrator.market_analyst.run = AsyncMock(
            return_value={"raw": "test", "parsed": low_confluence_report}
        )

        log = await orchestrator.run_cycle("test context")

        # Should return SKIP without calling Research Agent
        assert log.error is not None
        assert "confluence" in log.error.lower()
        assert "FORCED SKIP" in log.error or "insufficient" in log.error.lower()
        assert log.final_decision is None
        assert "PLAYBOOK GATE" in log.verification_flags[0]

    async def test_confluence_at_threshold_proceeds(self, orchestrator):
        """Confluence =6 should allow pipeline to proceed."""
        valid_report = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=7,
            technical_summary="Valid setup",
            positioning_summary="Aligned",
            fast_filter_flags=[],
            confluence_technical=3,
            confluence_positioning=2,
            confluence_microstructure=1,
            confluence_total=6,  # At threshold
            disqualifiers_active=[],
            setup_match="A",
        )
        orchestrator.market_analyst.run = AsyncMock(
            return_value={"raw": "test", "parsed": valid_report}
        )

        # Mock subsequent agents to return valid responses
        from core.schemas import ResearchPlan, TraderProposal, TraderAction
        
        orchestrator.research_agent.run = AsyncMock(
            return_value={
                "raw": "research",
                "parsed": ResearchPlan(
                    rating=PortfolioRating.UP,
                    confidence=7,
                    bull_case=["test"],
                    bear_case=["test"],
                    strongest_counter_point="test",
                    why_it_doesnt_change_call="test",
                    reasoning="test",
                ),
            }
        )
        orchestrator.trader.run = AsyncMock(
            return_value={
                "raw": "trader",
                "parsed": TraderProposal(
                    action=TraderAction.UP,
                    confidence=7,
                    reasoning="test",
                    entry_price=50000,
                    expected_move_pct=1.0,
                    position_size_usd=100,
                    max_loss_usd=50,
                    market_odds=0.5,
                    expected_value=0.1,
                ),
            }
        )
        orchestrator.risk_pm.run = AsyncMock(
            return_value={
                "raw": "pm",
                "parsed": PortfolioDecision(
                    rating=PortfolioRating.UP,
                    confidence=7,
                    position_size_usd=100,
                    expected_value=0.1,
                    risk_reward_ratio=2.0,
                    aggressive_case="test",
                    conservative_case="test",
                    neutral_sizing_case="test",
                    reasoning="test",
                    warnings=[],
                ),
            }
        )

        log = await orchestrator.run_cycle("test context")

        # Should complete successfully (not SKIP)
        assert log.error is None
        assert log.final_decision is not None
        assert log.final_decision.rating == PortfolioRating.UP

    async def test_disqualifiers_force_skip(self, orchestrator):
        """Any active disqualifier should force SKIP."""
        report_with_disqualifiers = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=8,
            technical_summary="Strong setup",
            positioning_summary="Aligned",
            fast_filter_flags=["HIGH_IMPACT_NEWS"],
            confluence_technical=3,
            confluence_positioning=3,
            confluence_microstructure=2,
            confluence_total=8,  # High confluence but disqualified
            disqualifiers_active=["scheduled_macro_event", "high_impact_news"],
            setup_match="A",
        )
        orchestrator.market_analyst.run = AsyncMock(
            return_value={"raw": "test", "parsed": report_with_disqualifiers}
        )

        log = await orchestrator.run_cycle("test context")

        # Should force SKIP due to disqualifiers
        assert log.error is not None
        assert "disqualifier" in log.error.lower()
        assert "scheduled_macro_event" in log.error or "high_impact_news" in log.error
        assert log.final_decision is None
        assert any("PLAYBOOK GATE" in flag for flag in log.verification_flags)

    async def test_position_size_cap_enforcement(self, orchestrator, monkeypatch):
        """Position size >2% account should be capped."""
        # Set account balance via env var
        monkeypatch.setenv("ACCOUNT_BALANCE_USD", "10000")

        valid_report = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=9,
            technical_summary="Very strong",
            positioning_summary="Aligned",
            fast_filter_flags=[],
            confluence_technical=4,
            confluence_positioning=3,
            confluence_microstructure=3,
            confluence_total=10,  # Max confluence
            disqualifiers_active=[],
            setup_match="A",
        )
        orchestrator.market_analyst.run = AsyncMock(
            return_value={"raw": "test", "parsed": valid_report}
        )

        from core.schemas import ResearchPlan, TraderProposal, TraderAction

        orchestrator.research_agent.run = AsyncMock(
            return_value={
                "raw": "research",
                "parsed": ResearchPlan(
                    rating=PortfolioRating.UP,
                    confidence=9,
                    bull_case=["test"],
                    bear_case=["test"],
                    strongest_counter_point="test",
                    why_it_doesnt_change_call="test",
                    reasoning="test",
                ),
            }
        )
        orchestrator.trader.run = AsyncMock(
            return_value={
                "raw": "trader",
                "parsed": TraderProposal(
                    action=TraderAction.UP,
                    confidence=9,
                    reasoning="test",
                    entry_price=50000,
                    expected_move_pct=2.0,
                    position_size_usd=500,  # Will be capped
                    max_loss_usd=250,
                    market_odds=0.45,
                    expected_value=0.2,
                ),
            }
        )
        
        # PM proposes $500 position (5% of $10k account — over 2% cap)
        orchestrator.risk_pm.run = AsyncMock(
            return_value={
                "raw": "pm",
                "parsed": PortfolioDecision(
                    rating=PortfolioRating.UP,
                    confidence=9,
                    position_size_usd=500.0,  # 5% — should be capped to $200 (2%)
                    expected_value=0.2,
                    risk_reward_ratio=2.5,
                    aggressive_case="test",
                    conservative_case="test",
                    neutral_sizing_case="test",
                    reasoning="test",
                    warnings=[],
                ),
            }
        )

        log = await orchestrator.run_cycle("test context")

        # Should complete but with position size capped
        assert log.error is None
        assert log.final_decision is not None
        assert log.final_decision.position_size_usd == 200.0  # 2% of $10k
        assert any("POSITION CAPPED" in flag for flag in log.verification_flags)
        assert "500" in log.verification_flags[-1]  # Original size mentioned
        assert "200" in log.verification_flags[-1]  # Capped size mentioned

    async def test_position_cap_not_applied_when_below_threshold(self, orchestrator, monkeypatch):
        """Position size ≤2% should not trigger cap."""
        monkeypatch.setenv("ACCOUNT_BALANCE_USD", "10000")

        valid_report = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=7,
            technical_summary="Valid",
            positioning_summary="Aligned",
            fast_filter_flags=[],
            confluence_technical=3,
            confluence_positioning=2,
            confluence_microstructure=1,
            confluence_total=6,
            disqualifiers_active=[],
            setup_match="B",
        )
        orchestrator.market_analyst.run = AsyncMock(
            return_value={"raw": "test", "parsed": valid_report}
        )

        from core.schemas import ResearchPlan, TraderProposal, TraderAction

        orchestrator.research_agent.run = AsyncMock(
            return_value={
                "raw": "research",
                "parsed": ResearchPlan(
                    rating=PortfolioRating.LEAN_UP,
                    confidence=6,
                    bull_case=["test"],
                    bear_case=["test"],
                    strongest_counter_point="test",
                    why_it_doesnt_change_call="test",
                    reasoning="test",
                ),
            }
        )
        orchestrator.trader.run = AsyncMock(
            return_value={
                "raw": "trader",
                "parsed": TraderProposal(
                    action=TraderAction.UP,
                    confidence=6,
                    reasoning="test",
                    entry_price=50000,
                    expected_move_pct=0.5,
                    position_size_usd=150,
                    max_loss_usd=75,
                    market_odds=0.5,
                    expected_value=0.05,
                ),
            }
        )
        
        # PM proposes $150 (1.5% of $10k — below 2% cap)
        orchestrator.risk_pm.run = AsyncMock(
            return_value={
                "raw": "pm",
                "parsed": PortfolioDecision(
                    rating=PortfolioRating.LEAN_UP,
                    confidence=6,
                    position_size_usd=150.0,  # 1.5% — should NOT be capped
                    expected_value=0.05,
                    risk_reward_ratio=1.5,
                    aggressive_case="test",
                    conservative_case="test",
                    neutral_sizing_case="test",
                    reasoning="test",
                    warnings=[],
                ),
            }
        )

        log = await orchestrator.run_cycle("test context")

        # Should complete with original position size (not capped)
        assert log.error is None
        assert log.final_decision is not None
        assert log.final_decision.position_size_usd == 150.0  # Original, not capped
        assert not any("POSITION CAPPED" in flag for flag in log.verification_flags)
