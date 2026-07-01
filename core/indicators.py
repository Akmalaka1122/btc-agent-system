"""
indicators.py — Pre-compute technical indicators from OHLCV data.

Offloads indicator math from LLM (which is bad at calculation) to code.
Results are injected into market_context so Market Analyst can focus on
interpretation rather than computation.
"""
import logging
from typing import Optional

logger = logging.getLogger("indicators")


def calc_sma(closes: list[float], period: int) -> Optional[float]:
    """Simple Moving Average."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_ema(closes: list[float], period: int) -> Optional[float]:
    """Exponential Moving Average."""
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period  # seed with SMA
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(closes: list[float]) -> Optional[dict]:
    """MACD (12, 26, 9)."""
    if len(closes) < 26:
        return None
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None
    macd_line = ema12 - ema26

    # Calculate signal line (EMA9 of MACD line) — simplified
    # For full accuracy we'd need MACD history, but for a single-point read this is sufficient
    return {
        "macd_line": round(macd_line, 2),
        "signal": "bullish" if macd_line > 0 else "bearish",
    }


def calc_bollinger(closes: list[float], period: int = 20, std_mult: float = 2.0) -> Optional[dict]:
    """Bollinger Bands."""
    if len(closes) < period:
        return None
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std = variance ** 0.5
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    current = closes[-1]
    pct_b = (current - lower) / (upper - lower) if (upper - lower) > 0 else 0.5

    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 3),
        "signal": "overbought" if pct_b > 0.8 else "oversold" if pct_b < 0.2 else "neutral",
    }


def calc_vwap_deviation(candles: list[dict]) -> Optional[dict]:
    """VWAP deviation from last 20 candles."""
    if len(candles) < 10:
        return None
    recent = candles[-20:]
    total_pv = sum(c["close"] * c["volume"] for c in recent)
    total_vol = sum(c["volume"] for c in recent)
    if total_vol == 0:
        return None
    vwap = total_pv / total_vol
    current = candles[-1]["close"]
    deviation_pct = (current - vwap) / vwap * 100

    return {
        "vwap": round(vwap, 2),
        "deviation_pct": round(deviation_pct, 4),
        "signal": "above VWAP" if deviation_pct > 0.1 else "below VWAP" if deviation_pct < -0.1 else "at VWAP",
    }


def calc_adx(candles: list[dict], period: int = 14) -> Optional[dict]:
    """Simplified ADX — trend strength indicator."""
    if len(candles) < period + 1:
        return None

    true_ranges = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_high = candles[i - 1]["high"]
        prev_close = candles[i - 1]["close"]
        prev_low = candles[i - 1]["low"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

        up = high - prev_high
        down = prev_low - low
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)

    if len(true_ranges) < period:
        return None

    # Smoothed averages
    atr = sum(true_ranges[-period:]) / period
    plus_di = (sum(plus_dm[-period:]) / period / atr * 100) if atr > 0 else 0
    minus_di = (sum(minus_dm[-period:]) / period / atr * 100) if atr > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0

    return {
        "adx": round(dx, 1),
        "plus_di": round(plus_di, 1),
        "minus_di": round(minus_di, 1),
        "trend_strength": "strong" if dx > 25 else "weak/ranging",
        "direction": "bullish" if plus_di > minus_di else "bearish",
    }


def compute_all_indicators(candles: list[dict]) -> str:
    """Compute all indicators from OHLCV candles and return formatted string."""
    if not candles or len(candles) < 5:
        return "## Technical Indicators: INSUFFICIENT DATA"

    closes = [c["close"] for c in candles]
    sections = []

    # RSI
    rsi = calc_rsi(closes, 14)
    if rsi is not None:
        rsi_signal = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
        sections.append(f"RSI(14): {rsi:.1f} ({rsi_signal})")

    # MACD
    macd = calc_macd(closes)
    if macd:
        sections.append(f"MACD: {macd['macd_line']:+.2f} ({macd['signal']})")

    # Bollinger
    bb = calc_bollinger(closes, 20)
    if bb:
        sections.append(
            f"Bollinger(20,2): Upper={bb['upper']:,.2f} Mid={bb['middle']:,.2f} Lower={bb['lower']:,.2f} "
            f"%B={bb['pct_b']:.3f} ({bb['signal']})"
        )

    # EMA alignment
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    if ema9 and ema21:
        ema_signal = "bullish (EMA9 > EMA21)" if ema9 > ema21 else "bearish (EMA9 < EMA21)"
        sections.append(f"EMA9: {ema9:,.2f} | EMA21: {ema21:,.2f} ({ema_signal})")

    # VWAP
    vwap = calc_vwap_deviation(candles)
    if vwap:
        sections.append(f"VWAP: {vwap['vwap']:,.2f} | Deviation: {vwap['deviation_pct']:+.4f}% ({vwap['signal']})")

    # ADX
    adx = calc_adx(candles, 14)
    if adx:
        sections.append(f"ADX: {adx['adx']} | +DI: {adx['plus_di']} | -DI: {adx['minus_di']} ({adx['trend_strength']}, {adx['direction']})")

    if not sections:
        return "## Technical Indicators: CALCULATION FAILED"

    return "## Technical Indicators (pre-computed)\n" + "\n".join(sections)
