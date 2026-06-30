"""
schemas.py — schema untuk versi minimal (4 agent).
Lebih sedikit dari versi 12-agent karena Sentiment+News+OnChain sudah dilebur
jadi satu MarketReport, dan Risk debate + PM jadi satu PortfolioDecision.
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from datetime import datetime


class MarketBias(str, Enum):
    BEARISH = "BEARISH"
    MILDLY_BEARISH = "MILDLY_BEARISH"
    NEUTRAL = "NEUTRAL"
    MILDLY_BULLISH = "MILDLY_BULLISH"
    BULLISH = "BULLISH"


class MarketReport(BaseModel):
    """Output Market & Sentiment Analyst — gabungan price + sentiment + fast-filter news/onchain."""
    net_market_bias: MarketBias
    confidence: int = Field(ge=1, le=10)
    technical_summary: str
    positioning_summary: str  # funding/OI/liquidation read
    fast_filter_flags: list[str]  # scheduled events / exchange flows / whale alerts
    sentiment_tiebreaker: Optional[str] = None
    # Confluence scoring (from Trading Playbook §1)
    confluence_technical: int = Field(ge=0, le=4, description="A. Technical confluence score")
    confluence_positioning: int = Field(ge=0, le=3, description="B. Positioning confluence score")
    confluence_microstructure: int = Field(ge=0, le=3, description="C. Microstructure confluence score")
    confluence_total: int = Field(ge=0, le=10, description="Total confluence score (A+B+C)")
    disqualifiers_active: list[str] = Field(default_factory=list, description="Active disqualifiers from Playbook §6")
    setup_match: Optional[str] = Field(default=None, description="Which playbook setup matches: A/B/C/D/none")

    @model_validator(mode="after")
    def validate_confluence_total(self):
        expected = self.confluence_technical + self.confluence_positioning + self.confluence_microstructure
        if self.confluence_total != expected:
            # Auto-correct instead of rejecting (LLM might miscalculate)
            self.confluence_total = expected
        return self


class PortfolioRating(str, Enum):
    UP = "UP"
    LEAN_UP = "LEAN_UP"
    SKIP = "SKIP"
    LEAN_DOWN = "LEAN_DOWN"
    DOWN = "DOWN"


class ResearchPlan(BaseModel):
    """Output Research Agent — internal bull/bear synthesis."""
    rating: PortfolioRating  # UP / LEAN_UP / SKIP / LEAN_DOWN / DOWN
    confidence: int = Field(ge=1, le=10)
    bull_case: list[str]
    bear_case: list[str]
    strongest_counter_point: str
    why_it_doesnt_change_call: str
    reasoning: str


class TraderAction(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    SKIP = "SKIP"


class TraderProposal(BaseModel):
    action: TraderAction
    confidence: int = Field(ge=1, le=10)
    reasoning: str
    entry_price: float
    expected_move_pct: float
    position_size_usd: float
    max_loss_usd: float
    time_horizon: str = "5m"
    market_odds: float
    expected_value: float


class PortfolioDecision(BaseModel):
    """Output Risk & Portfolio Manager — gabungan 3-way risk debate + final call."""
    rating: PortfolioRating
    confidence: int = Field(ge=1, le=10)
    position_size_usd: float
    expected_value: float
    risk_reward_ratio: float
    aggressive_case: str
    conservative_case: str
    neutral_sizing_case: str
    reasoning: str
    warnings: list[str]


class CycleLog(BaseModel):
    cycle_id: str
    timestamp: datetime
    step_status: dict[str, str]
    latency_seconds: dict[str, float]
    verification_flags: list[str]
    final_decision: Optional[PortfolioDecision] = None
    error: Optional[str] = None
