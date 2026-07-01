"""
self_correction.py — Learn from trading outcomes (Phase 4: Meridian pattern).

Tracks cycle outcomes by comparing predicted direction vs actual price movement.
Generates structured lessons from wins and losses that get injected into
future agent prompts for continuous improvement.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("self_correction")

LESSONS_FILE = Path.home() / ".hermes" / "btc-agent-system" / "lessons.json"
OUTCOMES_FILE = Path.home() / ".hermes" / "btc-agent-system" / "outcomes.json"
MAX_LESSONS = 50
MAX_OUTCOMES = 200


class OutcomeTracker:
    """
    Track trading cycle outcomes.
    
    After each cycle that makes a decision (UP/DOWN), we record the entry price.
    After 5 minutes (or on next cycle), we check the exit price and determine
    if the prediction was correct.
    """
    
    def __init__(self, outcomes_file: Optional[Path] = None):
        self.outcomes_file = outcomes_file or OUTCOMES_FILE
        self.outcomes_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.outcomes_file.exists():
            self._save({"outcomes": []})
    
    def _load(self) -> Dict:
        try:
            with open(self.outcomes_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load outcomes: {e}")
            return {"outcomes": []}
    
    def _save(self, data: Dict):
        try:
            with open(self.outcomes_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save outcomes: {e}")
    
    def record_entry(
        self,
        cycle_id: str,
        decision: str,
        confidence: int,
        entry_price: float,
        confluence: int,
        setup_match: str,
        reasoning: str,
        position_size_usd: float,
    ) -> Dict:
        """
        Record a trade entry for outcome tracking.
        
        Called immediately after a cycle makes a non-SKIP decision.
        """
        data = self._load()
        
        outcome = {
            "cycle_id": cycle_id,
            "decision": decision.upper(),
            "confidence": confidence,
            "entry_price": entry_price,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "confluence": confluence,
            "setup_match": setup_match,
            "reasoning": reasoning[:300],
            "position_size_usd": position_size_usd,
            "exit_price": None,
            "exit_time": None,
            "actual_move_pct": None,
            "win": None,
            "pnl_usd": None,
            "resolved": False,
            "lesson_generated": False,
        }
        
        data["outcomes"].insert(0, outcome)
        data["outcomes"] = data["outcomes"][:MAX_OUTCOMES]
        self._save(data)
        
        logger.info(f"Recorded entry: {cycle_id} {decision} @ ${entry_price:,.2f}")
        return outcome
    
    def resolve_outcome(
        self,
        cycle_id: str,
        exit_price: float,
    ) -> Optional[Dict]:
        """
        Resolve a trade outcome with exit price.
        
        Called after the 5-minute window passes.
        Determines win/loss and generates lesson.
        """
        data = self._load()
        
        for outcome in data["outcomes"]:
            if outcome["cycle_id"] == cycle_id and not outcome["resolved"]:
                outcome["exit_price"] = exit_price
                outcome["exit_time"] = datetime.now(timezone.utc).isoformat()

                # Calculate actual move (guard against zero/None entry)
                entry = outcome.get("entry_price") or 0.0
                if entry <= 0:
                    logger.warning(
                        f"Cannot resolve {cycle_id}: invalid entry_price={entry}. "
                        f"Marking as resolved/invalid."
                    )
                    outcome["actual_move_pct"] = 0.0
                    outcome["win"] = None
                    outcome["pnl_usd"] = 0.0
                    outcome["resolved"] = True
                    outcome["invalid"] = True
                    self._save(data)
                    return outcome
                outcome["actual_move_pct"] = ((exit_price - entry) / entry) * 100
                
                # Determine win/loss
                decision = outcome["decision"]
                if decision in ["UP", "LEAN_UP"]:
                    outcome["win"] = exit_price > entry
                elif decision in ["DOWN", "LEAN_DOWN"]:
                    outcome["win"] = exit_price < entry
                else:
                    outcome["win"] = None
                
                # Calculate PnL (simplified: 1:1 odds, no fees)
                if outcome["win"]:
                    outcome["pnl_usd"] = outcome["position_size_usd"]
                else:
                    outcome["pnl_usd"] = -outcome["position_size_usd"]
                
                outcome["resolved"] = True
                self._save(data)
                
                logger.info(
                    f"Resolved {cycle_id}: {'WIN' if outcome['win'] else 'LOSS'} "
                    f"({outcome['actual_move_pct']:+.3f}%) "
                    f"PnL: ${outcome['pnl_usd']:+.2f}"
                )
                return outcome
        
        logger.warning(f"No unresolved outcome found for {cycle_id}")
        return None
    
    def get_unresolved(self) -> List[Dict]:
        """Get all unresolved entries (ready for outcome check)."""
        data = self._load()
        return [o for o in data["outcomes"] if not o["resolved"]]
    
    def get_resolved(self, limit: int = 20) -> List[Dict]:
        """Get resolved outcomes, newest first."""
        data = self._load()
        resolved = [o for o in data["outcomes"] if o["resolved"]]
        return resolved[:limit]
    
    def get_stats(self) -> Dict:
        """Get overall outcome statistics."""
        data = self._load()
        resolved = [o for o in data["outcomes"] if o["resolved"]]
        
        if not resolved:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "unresolved": len([o for o in data["outcomes"] if not o["resolved"]]),
            }
        
        wins = sum(1 for o in resolved if o.get("win"))
        losses = sum(1 for o in resolved if not o.get("win"))
        total_pnl = sum(o.get("pnl_usd", 0) for o in resolved)
        
        return {
            "total_trades": len(resolved),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(resolved) if resolved else 0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(resolved) if resolved else 0,
            "unresolved": len([o for o in data["outcomes"] if not o["resolved"]]),
        }


class LessonGenerator:
    """
    Generate lessons from resolved trading outcomes.
    
    Each lesson captures:
    - What happened (outcome details)
    - Why it happened (analysis)
    - What to adjust (recommendation)
    """
    
    def __init__(self, lessons_file: Optional[Path] = None):
        self.lessons_file = lessons_file or LESSONS_FILE
        self.lessons_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.lessons_file.exists():
            self._save({"lessons": []})
    
    def _load(self) -> Dict:
        try:
            with open(self.lessons_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load lessons: {e}")
            return {"lessons": []}
    
    def _save(self, data: Dict):
        try:
            with open(self.lessons_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save lessons: {e}")
    
    def generate_lesson(self, outcome: Dict) -> Dict:
        """
        Generate a structured lesson from a resolved outcome.
        
        This is a rule-based lesson generator. For more sophisticated
        analysis, an LLM could be called to generate insights.
        """
        data = self._load()
        
        decision = outcome["decision"]
        win = outcome.get("win", False)
        confidence = outcome.get("confidence", 0)
        confluence = outcome.get("confluence", 0)
        setup = outcome.get("setup_match", "none")
        move_pct = outcome.get("actual_move_pct", 0)
        reasoning = outcome.get("reasoning", "")
        
        # Generate lesson based on outcome pattern
        if win:
            lesson = self._analyze_win(outcome)
        else:
            lesson = self._analyze_loss(outcome)
        
        lesson_entry = {
            "id": f"lesson_{int(datetime.now(timezone.utc).timestamp())}_{outcome['cycle_id'][:6]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_id": outcome["cycle_id"],
            "outcome": "win" if win else "loss",
            "decision": decision,
            "confidence": confidence,
            "confluence": confluence,
            "setup": setup,
            "entry_price": outcome.get("entry_price", 0),
            "exit_price": outcome.get("exit_price", 0),
            "actual_move_pct": move_pct,
            "pnl_usd": outcome.get("pnl_usd", 0),
            "category": lesson["category"],
            "analysis": lesson["analysis"],
            "adjustment": lesson["adjustment"],
            "pattern": lesson.get("pattern", ""),
        }
        
        data["lessons"].insert(0, lesson_entry)
        data["lessons"] = data["lessons"][:MAX_LESSONS]
        self._save(data)
        
        logger.info(f"Generated lesson: {lesson_entry['id']} ({lesson['category']})")
        return lesson_entry
    
    def _analyze_win(self, outcome: Dict) -> Dict:
        """Analyze a winning trade."""
        confidence = outcome.get("confidence", 0)
        confluence = outcome.get("confluence", 0)
        setup = outcome.get("setup_match", "none")
        move_pct = abs(outcome.get("actual_move_pct", 0))
        
        if confidence >= 8 and confluence >= 8:
            return {
                "category": "high_conviction_win",
                "analysis": (
                    f"High conviction trade succeeded. {outcome['decision']} with "
                    f"{confidence}/10 confidence and {confluence}/10 confluence. "
                    f"Price moved {move_pct:+.3f}% as predicted. "
                    f"Setup {setup} confirmed strong."
                ),
                "adjustment": "Continue using high confluence threshold. Setup validated.",
                "pattern": f"confluence_{confluence}_setup_{setup}",
            }
        elif confidence <= 5:
            return {
                "category": "low_conviction_win",
                "analysis": (
                    f"Low conviction trade happened to win. {outcome['decision']} with "
                    f"only {confidence}/10 confidence. Move was {move_pct:+.3f}%. "
                    f"This may be luck rather than skill."
                ),
                "adjustment": "Don't lower confidence threshold just because this won.",
                "pattern": f"low_confidence_{confidence}",
            }
        else:
            return {
                "category": "standard_win",
                "analysis": (
                    f"Standard trade won. {outcome['decision']} with {confidence}/10 "
                    f"confidence, {confluence}/10 confluence. Setup: {setup}. "
                    f"Move: {move_pct:+.3f}%."
                ),
                "adjustment": "Strategy working as expected. Continue monitoring.",
                "pattern": f"standard_win_{setup}",
            }
    
    def _analyze_loss(self, outcome: Dict) -> Dict:
        """Analyze a losing trade."""
        confidence = outcome.get("confidence", 0)
        confluence = outcome.get("confluence", 0)
        setup = outcome.get("setup_match", "none")
        move_pct = abs(outcome.get("actual_move_pct", 0))
        reasoning = outcome.get("reasoning", "")
        
        if move_pct < 0.1:
            return {
                "category": "whipsaw_loss",
                "analysis": (
                    f"Trade lost on a tiny move ({move_pct:+.3f}%). "
                    f"This is a whipsaw — price barely moved. "
                    f"Confidence: {confidence}/10, Confluence: {confluence}/10."
                ),
                "adjustment": (
                    "Consider adding minimum move threshold. "
                    "If expected move <0.1%, treat as SKIP even with good confluence."
                ),
                "pattern": f"whipsaw_{setup}",
            }
        elif confidence >= 8:
            return {
                "category": "high_conviction_loss",
                "analysis": (
                    f"High conviction trade FAILED. {outcome['decision']} with "
                    f"{confidence}/10 confidence but lost {move_pct:+.3f}%. "
                    f"Setup: {setup}. The model was very confident but wrong."
                ),
                "adjustment": (
                    "High confidence losses indicate model calibration issue. "
                    "Review setup {setup} criteria — may be too permissive."
                ),
                "pattern": f"overconfident_{setup}",
            }
        elif confluence < 7:
            return {
                "category": "low_confluence_loss",
                "analysis": (
                    f"Trade with borderline confluence lost. {outcome['decision']} "
                    f"with {confluence}/10 confluence. Move: {move_pct:+.3f}%. "
                    f"Setup: {setup}."
                ),
                "adjustment": (
                    f"Consider raising confluence threshold for setup {setup} "
                    f"from 6 to 7 to filter borderline signals."
                ),
                "pattern": f"borderline_confluence_{confluence}",
            }
        else:
            return {
                "category": "standard_loss",
                "analysis": (
                    f"Standard trade lost. {outcome['decision']} with {confidence}/10 "
                    f"confidence, {confluence}/10 confluence. Setup: {setup}. "
                    f"Move: {move_pct:+.3f}%. Sometimes good trades lose."
                ),
                "adjustment": "Single losses within expected range. Monitor for patterns.",
                "pattern": f"standard_loss_{setup}",
            }
    
    def get_recent_lessons(self, limit: int = 5) -> List[Dict]:
        """Get most recent lessons."""
        data = self._load()
        return data.get("lessons", [])[:limit]
    
    def get_lessons_summary(self, limit: int = 3) -> str:
        """
        Get formatted lessons summary for prompt injection.
        
        This is injected into agent prompts so they can learn from past outcomes.
        """
        lessons = self.get_recent_lessons(limit)
        
        if not lessons:
            return ""
        
        lines = ["LESSONS FROM RECENT TRADES:"]
        for i, l in enumerate(lessons, 1):
            emoji = "✅" if l["outcome"] == "win" else "❌"
            lines.append(
                f"{i}. {emoji} [{l['category']}] {l['decision']} — {l['analysis'][:120]}"
            )
            lines.append(f"   → Adjustment: {l['adjustment'][:120]}")
        
        return "\n".join(lines)
    
    def get_loss_patterns(self) -> Dict[str, int]:
        """Aggregate loss patterns for analysis."""
        data = self._load()
        losses = [l for l in data["lessons"] if l["outcome"] == "loss"]
        
        patterns = {}
        for loss in losses:
            cat = loss["category"]
            patterns[cat] = patterns.get(cat, 0) + 1
        
        return dict(sorted(patterns.items(), key=lambda x: x[1], reverse=True))


# Global instances
_outcome_tracker: Optional[OutcomeTracker] = None
_lesson_generator: Optional[LessonGenerator] = None


def get_outcome_tracker() -> OutcomeTracker:
    global _outcome_tracker
    if _outcome_tracker is None:
        _outcome_tracker = OutcomeTracker()
    return _outcome_tracker


def get_lesson_generator() -> LessonGenerator:
    global _lesson_generator
    if _lesson_generator is None:
        _lesson_generator = LessonGenerator()
    return _lesson_generator


def get_lessons_summary(limit: int = 3) -> str:
    """Convenience: get lessons summary for prompt injection."""
    return get_lesson_generator().get_lessons_summary(limit)
