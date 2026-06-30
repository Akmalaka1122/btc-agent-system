"""test_schemas.py — pydantic schema boundary validation tests."""
import pytest
from pydantic import ValidationError
from core.schemas import (
    MarketReport, MarketBias, ResearchPlan, PortfolioRating,
    TraderProposal, TraderAction, PortfolioDecision, CycleLog,
)


class TestMarketReport:
    def test_valid_report(self):
        r = MarketReport(
            net_market_bias=MarketBias.BULLISH,
            confidence=7,
            technical_summary="BTC above 100k",
            positioning_summary="Funding positive",
            fast_filter_flags=["FOMC meeting"],
            confluence_technical=3,
            confluence_positioning=2,
            confluence_microstructure=2,
            confluence_total=7,
        )
        assert r.confluence_total == 7

    def test_confidence_zero_rejects(self):
        with pytest.raises(ValidationError):
            MarketReport(
                net_market_bias=MarketBias.NEUTRAL, confidence=0,
                technical_summary="test", positioning_summary="test",
                fast_filter_flags=[],
                confluence_technical=0, confluence_positioning=0,
                confluence_microstructure=0, confluence_total=0,
            )

    def test_confidence_eleven_rejects(self):
        with pytest.raises(ValidationError):
            MarketReport(
                net_market_bias=MarketBias.NEUTRAL, confidence=11,
                technical_summary="test", positioning_summary="test",
                fast_filter_flags=[],
                confluence_technical=0, confluence_positioning=0,
                confluence_microstructure=0, confluence_total=0,
            )

    def test_confluence_auto_correct(self):
        """LLM miscalculates total — validator auto-corrects."""
        r = MarketReport(
            net_market_bias=MarketBias.BULLISH, confidence=8,
            technical_summary="test", positioning_summary="test",
            fast_filter_flags=[],
            confluence_technical=3, confluence_positioning=2,
            confluence_microstructure=2, confluence_total=10,  # wrong!
        )
        assert r.confluence_total == 7  # auto-corrected to 3+2+2

    def test_confluence_technical_overflow(self):
        """Technical max is 4."""
        with pytest.raises(ValidationError):
            MarketReport(
                net_market_bias=MarketBias.NEUTRAL, confidence=5,
                technical_summary="test", positioning_summary="test",
                fast_filter_flags=[],
                confluence_technical=5,  # > 4, should reject
                confluence_positioning=0, confluence_microstructure=0,
                confluence_total=5,
            )

    def test_confluence_positioning_overflow(self):
        """Positioning max is 3."""
        with pytest.raises(ValidationError):
            MarketReport(
                net_market_bias=MarketBias.NEUTRAL, confidence=5,
                technical_summary="test", positioning_summary="test",
                fast_filter_flags=[],
                confluence_technical=0, confluence_positioning=4,  # > 3
                confluence_microstructure=0, confluence_total=4,
            )

    def test_disqualifiers_active_default(self):
        r = MarketReport(
            net_market_bias=MarketBias.NEUTRAL, confidence=5,
            technical_summary="test", positioning_summary="test",
            fast_filter_flags=[],
            confluence_technical=0, confluence_positioning=0,
            confluence_microstructure=0, confluence_total=0,
        )
        assert r.disqualifiers_active == []
        assert r.setup_match is None

    def test_all_bias_values(self):
        for bias in MarketBias:
            r = MarketReport(
                net_market_bias=bias, confidence=5,
                technical_summary="test", positioning_summary="test",
                fast_filter_flags=[],
                confluence_technical=0, confluence_positioning=0,
                confluence_microstructure=0, confluence_total=0,
            )
            assert r.net_market_bias == bias


class TestResearchPlan:
    def test_valid_plan(self):
        p = ResearchPlan(
            rating=PortfolioRating.UP, confidence=8,
            bull_case=["momentum strong"], bear_case=["overbought"],
            strongest_counter_point="RSI divergence",
            why_it_doesnt_change_call="Trend intact",
            reasoning="Bullish overall",
        )
        assert p.rating == PortfolioRating.UP

    def test_all_ratings(self):
        for rating in PortfolioRating:
            p = ResearchPlan(
                rating=rating, confidence=5,
                bull_case=["test"], bear_case=["test"],
                strongest_counter_point="test",
                why_it_doesnt_change_call="test",
                reasoning="test",
            )
            assert p.rating == rating


class TestTraderProposal:
    def test_valid_proposal(self):
        p = TraderProposal(
            action=TraderAction.UP, confidence=7,
            reasoning="Strong momentum",
            entry_price=100000.0,
            expected_move_pct=0.5,
            position_size_usd=500.0,
            max_loss_usd=100.0,
            market_odds=0.55,
            expected_value=0.12,
        )
        assert p.action == TraderAction.UP

    def test_skip_action(self):
        p = TraderProposal(
            action=TraderAction.SKIP, confidence=3,
            reasoning="No clear setup",
            entry_price=100000.0,
            expected_move_pct=0,
            position_size_usd=0,
            max_loss_usd=0,
            market_odds=0.5,
            expected_value=0,
        )
        assert p.action == TraderAction.SKIP


class TestPortfolioDecision:
    def test_valid_decision(self):
        d = PortfolioDecision(
            rating=PortfolioRating.LEAN_UP, confidence=6,
            position_size_usd=200.0,
            expected_value=0.08,
            risk_reward_ratio=2.5,
            aggressive_case="Full momentum play",
            conservative_case="Half size, tight stop",
            neutral_sizing_case="Standard 2% risk",
            reasoning="Moderate conviction",
            warnings=["High funding rate"],
        )
        assert d.position_size_usd == 200.0

    def test_warnings_default_empty(self):
        d = PortfolioDecision(
            rating=PortfolioRating.SKIP, confidence=1,
            position_size_usd=0, expected_value=0,
            risk_reward_ratio=0,
            aggressive_case="n/a", conservative_case="n/a",
            neutral_sizing_case="n/a",
            reasoning="No trade",
            warnings=[],
        )
        assert d.warnings == []


class TestCycleLog:
    def test_valid_log(self):
        from datetime import datetime, timezone
        log = CycleLog(
            cycle_id="abc123",
            timestamp=datetime.now(timezone.utc),
            step_status={"step1": "complete"},
            latency_seconds={"total": 15.5},
            verification_flags=[],
        )
        assert log.final_decision is None
        assert log.error is None
