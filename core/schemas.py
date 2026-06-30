"""
schemas.py — schema untuk versi minimal (4 agent).
Lebih sedikit dari versi 12-agent karena Sentiment+News+OnChain sudah dilebur
jadi satu MarketReport, dan Risk debate + PM jadi satu PortfolioDecision.
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
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


class ResearchPlan(BaseModel):
    """Output Research Agent — internal bull/bear synthesis."""
    rating: str  # UP / LEAN_UP / SKIP / LEAN_DOWN / DOWN
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


class PortfolioRating(str, Enum):
    UP = "UP"
    LEAN_UP = "LEAN_UP"
    SKIP = "SKIP"
    LEAN_DOWN = "LEAN_DOWN"
    DOWN = "DOWN"


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
