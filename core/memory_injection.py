"""
memory_injection.py — Inject recent decisions into agent system prompts.

Phase 3 of Meridian pattern. Recent decisions are injected into the
system prompt so agents can maintain consistency and refer back to
past reasoning.
"""
import logging
from typing import Optional

from core.decision_log import get_decision_summary

logger = logging.getLogger("memory_injection")


def build_decision_context(limit: int = 5) -> str:
    """
    Build decision context for injection into agent prompts.
    
    Args:
        limit: Number of recent decisions to include
    
    Returns:
        Formatted string ready for prompt injection
    """
    summary = get_decision_summary(limit)
    
    if "No recent decisions" in summary:
        return ""
    
    context = f"""
═══════════════════════════════════════════════════════════
RECENT DECISION HISTORY (for consistency)
═══════════════════════════════════════════════════════════

{summary}

Note: Use this history to maintain consistency in your analysis. If recent
cycles showed similar market conditions, consider those outcomes. If you're
seeing conflicting signals vs previous decisions, explain the difference.

═══════════════════════════════════════════════════════════
"""
    
    return context.strip()


def inject_into_market_context(market_context: str, limit: int = 3) -> str:
    """
    Inject decision history into market context before sending to agents.
    
    This is called by orchestrator before running the pipeline. Agents will
    see recent decisions alongside current market data.
    
    Args:
        market_context: Current market data string
        limit: Number of recent decisions to inject (default 3 for brevity)
    
    Returns:
        Enhanced market context with decision history
    """
    decision_context = build_decision_context(limit)
    
    if not decision_context:
        return market_context
    
    # Prepend decision history before market data
    enhanced = f"{decision_context}\n\n{market_context}"
    
    logger.debug(f"Injected {limit} recent decisions into market context")
    
    return enhanced
