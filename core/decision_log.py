"""
decision_log.py — Structured decision logging for every cycle.

Inspired by Meridian's decision log pattern. Every trading decision
(UP/DOWN/SKIP) is logged with full reasoning, metrics, risks, and
rejected alternatives for auditability and learning.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.schemas import CycleLog, PortfolioRating

logger = logging.getLogger("decision_log")

DECISION_LOG_FILE = Path.home() / ".hermes" / "btc-agent-system" / "decision-log.json"
MAX_DECISIONS = 100


class DecisionLog:
    """
    Structured decision log for trading cycles.
    
    Each entry captures:
    - What decision was made (UP/DOWN/SKIP)
    - Why (reasoning from agents)
    - Metrics (confluence, confidence, setup)
    - Risks considered
    - Alternatives rejected
    """
    
    def __init__(self, log_file: Optional[Path] = None):
        self.log_file = log_file or DECISION_LOG_FILE
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.log_file.exists():
            self._save({"decisions": []})
    
    def _load(self) -> Dict:
        """Load decision log from disk."""
        try:
            with open(self.log_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load decision log: {e}")
            return {"decisions": []}
    
    def _save(self, data: Dict):
        """Save decision log to disk."""
        try:
            with open(self.log_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save decision log: {e}")
    
    @staticmethod
    def _sanitize(value: Optional[str], max_len: int = 280) -> Optional[str]:
        """Sanitize string value (trim, dedupe whitespace, cap length)."""
        if value is None:
            return None
        sanitized = " ".join(str(value).split()).strip()
        return sanitized[:max_len] if sanitized else None
    
    def append(
        self,
        cycle_log: CycleLog,
        summary: str,
        reason: str,
        risks: Optional[List[str]] = None,
        rejected: Optional[List[str]] = None,
    ) -> Dict:
        """
        Append a decision to the log.
        
        Args:
            cycle_log: CycleLog from orchestrator
            summary: One-line summary (e.g., "Forced SKIP due to low confluence")
            reason: Detailed reasoning (e.g., "Confluence 2/10 below threshold...")
            risks: List of risks considered (e.g., ["Missed potential move"])
            rejected: Alternatives rejected (e.g., ["UP (confluence too low)"])
        
        Returns:
            The created decision entry
        """
        data = self._load()
        
        # Extract decision type
        if cycle_log.final_decision:
            decision_type = cycle_log.final_decision.rating.value.lower()
            confidence = cycle_log.final_decision.confidence
            position_size = cycle_log.final_decision.position_size_usd
            expected_value = cycle_log.final_decision.expected_value
        else:
            decision_type = "skip"
            confidence = 0
            position_size = 0.0
            expected_value = 0.0
        
        # Build decision entry
        decision = {
            "id": f"dec_{int(datetime.now(timezone.utc).timestamp())}_{cycle_log.cycle_id[:6]}",
            "timestamp": cycle_log.timestamp.isoformat(),
            "type": decision_type,
            "actor": "ORCHESTRATOR",  # Could be more granular (which agent decided)
            "cycle_id": cycle_log.cycle_id,
            "summary": self._sanitize(summary),
            "reason": self._sanitize(reason, max_len=500),
            "risks": [self._sanitize(r, max_len=140) for r in (risks or [])][:6],
            "metrics": {
                "confidence": confidence,
                "position_size_usd": position_size,
                "expected_value": expected_value,
                "latency_seconds": cycle_log.latency_seconds.get("total", 0.0),
                "step_status": cycle_log.step_status,
            },
            "rejected": [self._sanitize(r, max_len=180) for r in (rejected or [])][:8],
            "error": cycle_log.error,
        }
        
        # Prepend (newest first)
        data["decisions"].insert(0, decision)
        
        # Cap at MAX_DECISIONS
        data["decisions"] = data["decisions"][:MAX_DECISIONS]
        
        self._save(data)
        logger.info(f"Logged decision: {decision['id']} ({decision_type.upper()})")
        
        return decision
    
    def get_recent(self, limit: int = 10) -> List[Dict]:
        """Get N most recent decisions."""
        data = self._load()
        return data.get("decisions", [])[:limit]
    
    def get_summary(self, limit: int = 5) -> str:
        """
        Get human-readable summary of recent decisions.
        
        Returns formatted string suitable for injection into agent prompts
        or displaying to users.
        """
        decisions = self.get_recent(limit)
        
        if not decisions:
            return "No recent decisions yet."
        
        lines = ["RECENT DECISIONS:"]
        for i, d in enumerate(decisions, 1):
            parts = [
                f"{i}. [{d['actor']}] {d['type'].upper()}",
                f"summary: {d['summary']}" if d.get('summary') else None,
                f"reason: {d['reason']}" if d.get('reason') else None,
                f"confidence: {d['metrics'].get('confidence', 0)}/10" if d['type'] != 'skip' else None,
            ]
            line = " | ".join(p for p in parts if p)
            lines.append(line)
        
        return "\n".join(lines)
    
    def get_by_type(self, decision_type: str, limit: int = 10) -> List[Dict]:
        """Filter decisions by type (up/down/skip)."""
        data = self._load()
        filtered = [d for d in data.get("decisions", []) if d["type"] == decision_type.lower()]
        return filtered[:limit]
    
    def get_losses(self, limit: int = 10) -> List[Dict]:
        """
        Get decisions that resulted in losses.
        
        Note: This requires outcome tracking (Phase 4). For now returns empty.
        Will be populated once we add outcome resolution.
        """
        # TODO: Implement after Phase 4 (self-correction)
        return []
    
    def get_wins(self, limit: int = 10) -> List[Dict]:
        """Get decisions that resulted in wins."""
        # TODO: Implement after Phase 4
        return []


# Global instance
_decision_log: Optional[DecisionLog] = None


def get_decision_log() -> DecisionLog:
    """Get or create global DecisionLog instance."""
    global _decision_log
    if _decision_log is None:
        _decision_log = DecisionLog()
    return _decision_log


def append_decision(
    cycle_log: CycleLog,
    summary: str,
    reason: str,
    risks: Optional[List[str]] = None,
    rejected: Optional[List[str]] = None,
) -> Dict:
    """Convenience function to append to global log."""
    return get_decision_log().append(cycle_log, summary, reason, risks, rejected)


def get_recent_decisions(limit: int = 10) -> List[Dict]:
    """Convenience function to get recent decisions."""
    return get_decision_log().get_recent(limit)


def get_decision_summary(limit: int = 5) -> str:
    """Convenience function to get summary."""
    return get_decision_log().get_summary(limit)
