"""
schemas.py — semua schema output agent dalam satu tempat.
Dipakai orchestrator buat verify step (cek structural validity sebelum lanjut ke wave berikutnya).
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


class SentimentBand(str, Enum):
    VERY_BEARISH = "VERY_BEARISH"
    BEARISH = "BEARISH"
    MILDLY_BEARISH = "MILDLY_BEARISH"
    NEUTRAL = "NEUTRAL"
    MILDLY_BULLISH = "MILDLY_BULLISH"
    BULLISH = "BULLISH"
    VERY_BULLISH = "VERY_BULLISH"


class SentimentReport(BaseModel):
    overall_sentiment: SentimentBand
    confidence: int = Field(ge=1, le=10)
    key_catalysts: list[str]
    source_breakdown: dict[str, float]
    funding_rate_signal: str
    liquidation_risk: str


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


class ResearchPlan(BaseModel):
    rating: str  # UP / LEAN_UP / SKIP / LEAN_DOWN / DOWN
    confidence: int = Field(ge=1, le=10)
    reasoning: str
    key_factors: list[str]
    risk_warnings: list[str]
    recommended_size: str  # SMALL / MEDIUM / LARGE / SKIP


class PortfolioRating(str, Enum):
    UP = "UP"
    LEAN_UP = "LEAN_UP"
    SKIP = "SKIP"
    LEAN_DOWN = "LEAN_DOWN"
    DOWN = "DOWN"


class PortfolioDecision(BaseModel):
    rating: PortfolioRating
    confidence: int = Field(ge=1, le=10)
    position_size_usd: float
    expected_value: float
    risk_reward_ratio: float
    reasoning: str
    key_factors: list[str]
    warnings: list[str]


class CycleLog(BaseModel):
    """Output orchestrator per cycle — ini yang dikirim ke Telegram + disimpan ke DB."""
    cycle_id: str
    timestamp: datetime
    wave_status: dict[str, str]          # e.g. {"wave1": "complete", "wave2": "degraded"}
    latency_seconds: dict[str, float]
    verification_flags: list[str]        # output yg di-reject/re-dispatch
    data_quality_flags: list[str]        # MISSING/STALE inputs
    final_decision: Optional[PortfolioDecision] = None
    error: Optional[str] = None
