# Meridian-Style Bot Enhancement Plan

## Goal
Transform btc-agent-system bot dari command-only menjadi **conversational agent** yang bisa:
1. Chat naturally tentang trading decisions
2. Explain reasoning ("why did you skip?", "why UP?")
3. Self-correct dari mistake (learn from losses)
4. Remember context across conversations

---

## Key Patterns from Meridian

### 1. **Decision Log** (`decision-log.json`)
Setiap keputusan trading disimpan dengan:
- `id`, `timestamp`, `type` (deploy/close/skip)
- `actor` (which agent made decision)
- `pool/position` identifiers
- `summary` (1-line what happened)
- `reason` (detailed why)
- `risks` (what could go wrong)
- `metrics` (confluence, confidence, etc.)
- `rejected` (alternative options considered)

**Implementation for BTC:**
```python
# core/decision_log.py
{
  "id": "dec_1719792345_a3f2",
  "timestamp": "2026-06-30T23:45:00Z",
  "type": "skip",  # or "up", "down", "lean_up", "lean_down"
  "actor": "MARKET_ANALYST",
  "cycle_id": "535f3c12",
  "summary": "Forced SKIP due to low confluence",
  "reason": "Confluence 2/10 below threshold 6. Technical signals mixed, no clear directional bias.",
  "risks": ["No position taken", "Missed potential move if market shifts"],
  "metrics": {
    "confluence_technical": 1,
    "confluence_positioning": 0,
    "confluence_microstructure": 1,
    "confluence_total": 2,
    "setup_match": "none",
    "btc_price": 59956.05
  },
  "rejected": [
    "UP (confluence too low)",
    "DOWN (confluence too low)"
  ]
}
```

### 2. **Conversational Handler**
Bot respond ke natural language:
- "why did you skip?" → Load decision log + explain
- "what was your last trade?" → Query recent decisions
- "why are you bullish?" → Explain current market read
- "show me your mistakes" → Filter losses + show patterns

**Implementation:**
```python
# telegram_bot/conversational.py
async def handle_natural_message(message: str, context: dict):
    """Route natural language queries to appropriate handler."""
    msg_lower = message.lower()
    
    if "why" in msg_lower and ("skip" in msg_lower or "pass" in msg_lower):
        return await explain_last_skip()
    
    elif "why" in msg_lower and ("up" in msg_lower or "bullish" in msg_lower):
        return await explain_last_up()
    
    elif "mistake" in msg_lower or "loss" in msg_lower:
        return await show_losses()
    
    elif "learn" in msg_lower or "improve" in msg_lower:
        return await show_lessons()
    
    else:
        # Fallback: LLM-powered general chat
        return await llm_chat(message, context)
```

### 3. **Memory Injection**
Recent decisions masuk ke agent system prompt:
```
RECENT DECISIONS (last 5):
1. [MARKET_ANALYST] SKIP | summary: Low confluence (2/10) | reason: Mixed signals, no setup...
2. [TRADER] UP | summary: Momentum breakout (Setup A) | reason: Strong uptrend + funding neutral...
3. [MARKET_ANALYST] SKIP | summary: Disqualifier active (scheduled_macro_event) | reason: FOMC...
```

Agent bisa refer back ke decisions sebelumnya untuk consistency.

### 4. **Self-Correction (Lessons)**
Setiap posisi yang closed (win or loss) generate lesson:
```python
# core/lessons.py
{
  "id": "lesson_001",
  "timestamp": "2026-06-30T15:30:00Z",
  "outcome": "loss",  # or "win"
  "entry": {
    "decision": "UP",
    "confidence": 7,
    "confluence": 6,
    "setup": "A",
    "entry_price": 60000,
    "reasoning": "Momentum breakout, volume spike"
  },
  "exit": {
    "exit_price": 59500,
    "pnl_usd": -100,
    "actual_move_pct": -0.83
  },
  "analysis": "Momentum setup failed. Volume spike was temporary, no follow-through. Consider requiring 3+ consecutive strong candles instead of 1.",
  "adjustment": "Tighten Setup A criteria: require sustained volume (3x avg) for 3+ candles, not just 1."
}
```

Lessons di-inject ke system prompt untuk improve future decisions.

---

## Implementation Plan

### Phase 1: Decision Log (1-2 hours)
1. Create `core/decision_log.py` — save every cycle decision
2. Modify `orchestrator.py` — call `append_decision()` after each cycle
3. Add `get_recent_decisions()` tool for agents
4. Update cycle broadcast to include decision summary

### Phase 2: Conversational Handler (2-3 hours)
1. Create `telegram_bot/conversational.py`
2. Pattern matching for common queries:
   - "why skip?" → explain_last_skip()
   - "why up/down?" → explain_last_trade()
   - "show mistakes" → show_losses()
   - "what did you learn?" → show_lessons()
3. Add LLM-powered fallback for general chat
4. Update bot.py to route non-command messages to conversational handler

### Phase 3: Memory Injection (1 hour)
1. Modify `orchestrator.py` — inject recent decisions into system prompt
2. Format: "RECENT DECISIONS (last 5): ..." before market_context
3. Agents can refer back untuk consistency

### Phase 4: Self-Correction (2-3 hours)
1. Create `core/lessons.py` — generate lessons from closed positions
2. After each resolved cycle (5min window passed):
   - Compare decision (UP/DOWN) vs actual outcome (price moved up/down)
   - If loss: analyze why prediction failed
   - Generate structured lesson
3. Inject top 3 recent lessons into system prompt
4. Track improvement over time (win rate trend)

### Phase 5: Testing (1 hour)
1. Test conversational queries with real bot
2. Verify decision log populates correctly
3. Check lessons generation from backtest results
4. Validate memory injection doesn't break existing flow

---

## Benefits

**User Experience:**
- ✅ Natural chat instead of just commands
- ✅ Bot explains its reasoning transparently
- ✅ Users can review decision history easily
- ✅ Bot improves over time (visible learning)

**System Quality:**
- ✅ Auditability (every decision logged)
- ✅ Consistency (agents see past decisions)
- ✅ Self-improvement (lessons from mistakes)
- ✅ Debugging (clear why bot made each choice)

**Alignment with Meridian:**
- ✅ Decision log pattern (proven in production)
- ✅ Conversational interface (user-friendly)
- ✅ Memory persistence (stateful agent)
- ✅ Learning loop (continuous improvement)

---

## Next Steps

1. Start with **Phase 1 (Decision Log)** — foundation for everything else
2. Test decision log dengan current bot (manual cycles)
3. Add **Phase 2 (Conversational)** — immediate UX improvement
4. Phase 3-4 can follow after validation

**Estimated Total:** 7-10 hours untuk full implementation
**Priority:** Phase 1+2 first (decision log + conversational) = ~3-5 hours

---

Gas lanjut implement? Mulai dari Decision Log dulu? 🚀
