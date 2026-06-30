"""
chat_agent.py — LLM-powered conversational chat for Telegram bot.

Unlike pattern-matching in conversational.py, this uses the LLM to handle
ANY user question with full context about the trading system.

Context injected:
- Recent decisions from decision log
- System state (running/paused, last cycle)
- Current market conditions (from last cycle)
- Lessons from past trades
"""
import logging
import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # Ensure .env is loaded

from openai import AsyncOpenAI

from core.agent import _get_config
from core.decision_log import get_decision_log
from core.self_correction import get_lesson_generator, get_outcome_tracker

logger = logging.getLogger("chat_agent")

SYSTEM_PROMPT = """You are the BTC Trading Agent — a conversational AI that manages a 5-agent trading system for Bitcoin on Polymarket.

## Your Capabilities
- You analyze BTC market data every 5 minutes using 5 specialized agents
- You make trading decisions: UP, DOWN, LEAN_UP, LEAN_DOWN, or SKIP
- You enforce strict rules: confluence threshold ≥6, 2% position cap, disqualifier checks
- You learn from past trades (wins and losses)

## Your Personality
- Direct and concise (like a experienced trader)
- Honest about uncertainty — if the market is unclear, say so
- Use emoji sparingly but effectively (🟢🔴⚪📊)
- Mix English and Indonesian naturally (the user is Indonesian)
- Never make up data — if you don't have recent market data, say so

## Rules
- You are a PAPER TRADING system — no real money at risk
- You cannot execute real trades
- You explain your reasoning transparently
- You reference specific decisions from the log when relevant
- If asked about something outside your knowledge, say you don't know

## Response Format
- Keep responses under 500 words
- Use markdown formatting for readability
- Use bullet points for lists
- Bold key numbers and decisions"""


def _build_context() -> str:
    """Build trading context for the LLM."""
    parts = []
    
    # Decision history
    dl = get_decision_log()
    summary = dl.get_summary(limit=5)
    if "No recent" not in summary:
        parts.append(f"## Recent Decisions\n{summary}")
    
    # Outcome stats
    tracker = get_outcome_tracker()
    stats = tracker.get_stats()
    if stats["total_trades"] > 0:
        parts.append(
            f"## Trading Stats\n"
            f"- Total trades: {stats['total_trades']}\n"
            f"- Win rate: {stats['win_rate']:.1%}\n"
            f"- Total PnL: ${stats['total_pnl']:+,.2f}\n"
            f"- Unresolved: {stats['unresolved']}"
        )
    
    # Lessons
    gen = get_lesson_generator()
    lessons = gen.get_lessons_summary(limit=3)
    if lessons:
        parts.append(f"## Lessons\n{lessons}")
    
    if not parts:
        return "No trading history yet — the system just started or has no decisions."
    
    return "\n\n".join(parts)


async def chat(user_message: str) -> str:
    """
    Send a message to the LLM with trading context.
    
    This is the main entry point for general conversation.
    Called by conversational.py when no pattern matches.
    """
    cfg = _get_config()
    
    # Build context
    context = _build_context()
    
    # Build messages
    system = f"{SYSTEM_PROMPT}\n\n---\n## Current Trading Context\n\n{context}"
    
    try:
        if cfg.get("sdk") == "anthropic":
            return await _call_anthropic(cfg, system, user_message)
        else:
            return await _call_openai(cfg, system, user_message)
    except Exception as e:
        logger.error(f"Chat LLM call failed: {e}")
        return f"❌ LLM error: {str(e)[:100]}\n\nCoba lagi nanti atau gunakan commands: /status /history /run"


async def _call_openai(cfg: dict, system: str, user: str) -> str:
    """Call OpenAI-compatible API."""
    client = AsyncOpenAI(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        timeout=30.0,
    )
    
    response = await client.chat.completions.create(
        model=cfg["model"],
        max_tokens=1000,
        temperature=0.5,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    
    return response.choices[0].message.content.strip()


async def _call_anthropic(cfg: dict, system: str, user: str) -> str:
    """Call Anthropic native API."""
    try:
        import anthropic
    except ImportError:
        return "❌ Anthropic SDK not installed. Use an OpenAI-compatible provider."
    
    client = anthropic.AsyncAnthropic(api_key=cfg["api_key"])
    
    response = await client.messages.create(
        model=cfg["model"],
        max_tokens=1000,
        temperature=0.5,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    
    return response.content[0].text.strip()
