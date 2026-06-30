# Trading Playbook Integration Audit Report

**Date:** 2026-06-30  
**Auditor:** Subagent (Hermes)  
**Scope:** Verify souls (01-04) correctly implement confluence scoring (§1), setup criteria (§2-5), disqualifiers (§6), and sizing rules (§7). Check MarketReport schema fields match playbook requirements. Verify Research Agent enforces confluence ≥6 threshold before non-SKIP rating.

---

## Executive Summary

✅ **Schema Alignment: PASS** — All required fields present and correctly bounded  
⚠️ **Soul Integration: PARTIAL** — Documentation present but no programmatic enforcement  
❌ **Threshold Enforcement: MISSING** — Confluence ≥6 rule is documented in souls but not enforced in code

---

## 1. Schema → Playbook Mapping ✅

**File:** `core/schemas.py`

| Playbook §1 Field | Schema Field | Type | Range | Status |
|---|---|---|---|---|
| A. Technical Confluence | `confluence_technical` | int | 0-4 | ✅ Field(ge=0, le=4) |
| B. Positioning Confluence | `confluence_positioning` | int | 0-3 | ✅ Field(ge=0, le=3) |
| C. Microstructure Confluence | `confluence_microstructure` | int | 0-3 | ✅ Field(ge=0, le=3) |
| Total Confluence | `confluence_total` | int | 0-10 | ✅ Field(ge=0, le=10) + auto-validator |
| §6 Disqualifiers | `disqualifiers_active` | list[str] | — | ✅ default_factory=list |
| §2-5 Setup Match | `setup_match` | Optional[str] | A/B/C/D/none | ✅ Optional[str] |

**Validation Logic:**
```python
@model_validator(mode="after")
def validate_confluence_total(self):
    expected = self.confluence_technical + self.confluence_positioning + self.confluence_microstructure
    if self.confluence_total != expected:
        self.confluence_total = expected  # auto-correct
    return self
```
✅ **Verdict:** Schema correctly implements all playbook-required fields with proper bounds and auto-correction.

---

## 2. Soul Integration — Market & Sentiment Analyst ✅

**File:** `souls/01-market-sentiment-analyst.soul.md`

### Confluence Scoring (Lines 19-23)
```markdown
6. **Calculate Confluence Score (from Trading Playbook):**
   - **A. Technical (0-4):** +1 each for RSI alignment, MACD cross momentum, Bollinger breakout, EMA9/EMA21 alignment
   - **B. Positioning (0-3):** +1 each for funding rate alignment, OI change >2%/15min, no opposing liquidation cascade
   - **C. Microstructure (0-3):** +1 each for orderbook imbalance >60:40, VWAP deviation >0.1%, volume spike >1.5x/20min avg
7. Synthesize into ONE net read with confluence score explicit.
```

### Output Discipline (Lines 26-36)
```markdown
CONFLUENCE SCORE: A=[X/4] B=[X/3] C=[X/3] TOTAL=[X/10]
DISQUALIFIERS: [any active from Playbook §6 — or "none"]
NET MARKET BIAS: [BULLISH/BEARISH/NEUTRAL] (confidence X/10)
SETUP MATCH: [A/B/C/D/none — which playbook setup, if any, matches current conditions]
```

✅ **Verdict:** Soul explicitly instructs calculation of all confluence components and setup identification.

---

## 3. Soul Integration — Research Agent ⚠️

**File:** `souls/02-research-agent.soul.md`

### Setup Validation (Lines 14-18)
```markdown
2. **If a Setup (A/B/C/D) was flagged by the Market Analyst**, validate it against the Trading Playbook criteria:
   - Setup A (Momentum Continuation): technical ≥3/4, volume spike, no near resistance, funding not extreme opposing
   - Setup B (Mean Reversion): RSI <20/>80, Bollinger 2σ touch, volume declining (exhaustion), no active news
   - Setup C (Liquidation Cascade Fade): >$5-10M cascade, >0.3-0.5% forced move, orderbook replenishing
   - Setup D (Crowded Trade Unwind): funding >1.5σ extreme, OI rising, momentum stalling
```

### Critical Threshold Rule (Line 22)
```markdown
6. Commit to a rating. If confluence <6 or any disqualifier active → forced SKIP regardless of bull/bear strength.
```

⚠️ **Issue Found:** This rule is **documented in the soul but not enforced programmatically**.

**Evidence:**
- No validation in `core/orchestrator.py` checks `market.confluence_total < 6` before calling Research Agent
- No schema constraint prevents Research Agent from returning non-SKIP rating when confluence < 6
- Research Agent relies on LLM to follow instructions, not code enforcement

**Gap:** The system depends on the LLM correctly reading and applying the threshold rule. If the LLM:
- Misreads the confluence score
- Decides to "override" the rule based on other factors
- Has a prompt injection attack

...then a non-SKIP rating could be issued despite confluence < 6.

---

## 4. Soul Integration — Trader Agent ✅

**File:** `souls/03-trader-agent.soul.md`

### Key Responsibilities (Lines 6-18)
```markdown
- The Research Agent's plan is your starting point, not your final answer. You add the one critical layer they don't have: **execution reality**
- Expected value, not just direction, is your real north star.
- Compare current Polymarket implied odds against your directional conviction
```

✅ **Verdict:** Trader soul correctly positioned as execution specialist, references EV gate from Playbook §6.

---

## 5. Soul Integration — Risk & Portfolio Manager ✅

**File:** `souls/04-risk-portfolio-manager.soul.md`

### Position Sizing per Playbook §7 (Lines 17-21)
```markdown
2. **Apply Playbook Position Sizing (§7) based on confluence score:**
   - Score 0-5: 0% → forced SKIP (no validated edge)
   - Score 6-7: 25-40% of daily sizing unit (LEAN)
   - Score 8-10: 60-100% of daily sizing unit (FULL, capped at 2% account)
```

### EV Gate (Line 23)
```markdown
4. **Check EV gate:** At current Polymarket implied odds, does this trade require a win rate that the confluence score actually supports? If implied prob ≥ confluence-implied prob → SKIP even with high score.
```

✅ **Verdict:** Risk & PM soul correctly documents sizing rules and references confluence scores for decision-making.

---

## 6. Orchestrator Data Flow ✅

**File:** `core/orchestrator.py`

### Pipeline Structure (Lines 215-260)
```python
# STEP 1: Market & Sentiment Analyst
market_result = await self._safe_run(self.market_analyst, market_context, flags)

# STEP 2: Research Agent
research_result = await self._safe_run(
    self.research_agent, f"Market & Sentiment Report:\n{market_result['raw']}", flags)

# STEP 3: Trader Agent
trader_result = await self._safe_run(
    self.trader,
    f"Research Plan:\n{research_result['raw']}\n\nMarket Report:\n{market_result['raw']}",
    flags
)

# STEP 4: Risk & Portfolio Manager
pm_result = await self._safe_run(
    self.risk_pm,
    f"Market & Sentiment Report:\n{market_result['raw']}\n\n"
    f"Research Plan:\n{research_result['raw']}\n\n"
    f"Trader Proposal:\n{trader_result['raw']}",
    flags
)
```

✅ **Correct:** Risk & PM receives MarketReport (fixed in commit 93d980e per AUDIT_REPORT.md).

### Database Recording (Lines 276-290)
```python
if self.db and log.final_decision:
    market = market_result["parsed"]
    await self.db.record_cycle(
        cycle_id=cycle_id,
        timestamp=t0,
        rating=d.rating.value,
        confidence=d.confidence,
        position_size_usd=d.position_size_usd,
        setup_match=(market.setup_match or "none") if market else "none",
        confluence_total=market.confluence_total if market else 0,
    )
```

✅ **Correct:** Confluence and setup metadata are persisted for backtest analysis.

---

## 7. Critical Gap: No Programmatic Enforcement of Confluence ≥6 Rule ❌

### What the Playbook Says (§1, Line 18)
> Threshold trading: **skor ≥ 6 untuk LEAN, ≥ 8 untuk full-size.**

### What Research Agent Soul Says (Line 22)
> If confluence <6 or any disqualifier active → **forced SKIP** regardless of bull/bear strength.

### What the Code Does
**Nothing.** The orchestrator passes MarketReport to Research Agent but does not validate:
```python
# This check does NOT exist anywhere:
if market_result["parsed"].confluence_total < 6:
    return forced_SKIP_log(...)
```

### Risk Assessment
| Risk | Severity | Likelihood |
|---|---|---|
| LLM ignores threshold rule | Medium | Low (well-prompted) |
| LLM misreads confluence score | Medium | Low (schema validates it) |
| Prompt injection override | High | Very Low (no external input) |
| Developer confusion about where rule lives | Low | Medium (documentation vs enforcement split) |

### Recommendation
Add guard clause in `orchestrator.py` after Market Analyst step:

```python
# After STEP 1: Market & Sentiment Analyst
market = market_result["parsed"]
if market and market.confluence_total < 6:
    logger.info(f"Confluence {market.confluence_total} < 6 threshold — forcing SKIP")
    return self._forced_skip_log(
        cycle_id, t0, step_status, latency, flags,
        f"Confluence score {market.confluence_total} below threshold 6 (Playbook §1)"
    )
if market and market.disqualifiers_active:
    logger.info(f"Disqualifiers active: {market.disqualifiers_active} — forcing SKIP")
    return self._forced_skip_log(
        cycle_id, t0, step_status, latency, flags,
        f"Disqualifiers active: {', '.join(market.disqualifiers_active)} (Playbook §6)"
    )
```

This moves the enforcement from "LLM should follow instructions" to "code enforces the rule before LLM sees it."

---

## 8. Setup Criteria Validation (§2-5) ⚠️

**Playbook Requirements:**

### Setup A — Momentum Continuation (§2)
- Technical confluence ≥ 3/4
- Volume spike >1.5x
- No near resistance/support
- Funding not extreme opposing

### Setup B — Mean Reversion (§3)
- RSI(1m) <20 or >80
- Bollinger Band 2σ touch
- Volume declining (exhaustion)
- No active news

### Setup C — Liquidation Cascade Fade (§4)
- Cascade >$5-10M in <5min
- Price move >0.3-0.5% in <2min
- Orderbook replenishing

### Setup D — Crowded Trade Unwind (§5)
- Funding >1.5σ extreme
- OI rising
- Momentum stalling

**Current Implementation:**
- ✅ Market Analyst soul lists setup criteria (lines 14-18)
- ✅ Research Agent soul references setup validation (lines 14-18)
- ❌ No programmatic validation that setup criteria are met before assigning `setup_match`

**Risk:** Market Analyst might label a setup incorrectly (e.g., "Setup A" without checking technical ≥3/4). Research Agent is instructed to validate but has no enforcement mechanism.

**Status:** Low risk if Market Analyst prompt is followed correctly, but no safety net.

---

## 9. Disqualifier Rules (§6) ⚠️

**Playbook §6 Disqualifiers:**
1. Scheduled macro event ±10min
2. Spread/liquidity widened significantly
3. HIGH impact news active
4. Cascade without replenishment (unless Setup C)
5. Implied prob ≥ internal estimate

**Current Implementation:**
- ✅ Schema field: `disqualifiers_active: list[str]`
- ✅ Market Analyst soul instructs reporting disqualifiers (line 33)
- ❌ No programmatic check that stops pipeline when disqualifiers are present

**Gap:** Same as confluence threshold — relies on LLM reading `disqualifiers_active` field and choosing SKIP.

---

## 10. Position Sizing Rules (§7) ✅

**Playbook §7:**
| Confluence | Sizing | Cap |
|---|---|---|
| 0-5 | 0% (SKIP) | — |
| 6-7 | 25-40% (LEAN) | 2% account |
| 8-10 | 60-100% (FULL) | 2% account |

**Soul Implementation:**
- ✅ Risk & PM soul (lines 17-21) explicitly lists this table
- ✅ Hard cap 2% mentioned (line 22)

**Code Enforcement:** None. Sizing is determined by Risk & PM agent's LLM output. However, this is acceptable because:
- Sizing is a continuous decision with judgment required (not a binary gate)
- 2% hard cap can be enforced post-decision if needed (not currently implemented)

**Status:** Acceptable for LLM-based discretion, but consider adding post-hoc validation:
```python
if log.final_decision and log.final_decision.position_size_usd > account_balance * 0.02:
    log.verification_flags.append("WARNING: Position size exceeds 2% cap, capping to max")
    log.final_decision.position_size_usd = account_balance * 0.02
```

---

## 11. Test Coverage Analysis

**File:** `tests/test_orchestrator.py`

### Coverage Status
- ✅ Happy path: all agents complete successfully (lines 76-99)
- ✅ Agent failure handling: each step's failure tested (lines 102-173)
- ✅ Circuit breaker blocking (lines 175-189)
- ✅ Database recording (lines 192-219)
- ❌ **No test for confluence < 6 threshold enforcement**
- ❌ **No test for disqualifier enforcement**
- ❌ **No test for setup criteria validation**

**Recommendation:** Add test cases:
```python
async def test_confluence_below_threshold_forces_skip(self):
    """Confluence < 6 should force SKIP regardless of other signals."""
    market = _mock_market_report()
    market.confluence_total = 4  # below threshold
    # Assert pipeline returns SKIP
    
async def test_disqualifiers_force_skip(self):
    """Active disqualifiers should force SKIP."""
    market = _mock_market_report()
    market.disqualifiers_active = ["FOMC in 5 minutes"]
    # Assert pipeline returns SKIP
```

---

## 12. Summary of Findings

| Component | Requirement | Status | Notes |
|---|---|---|---|
| Schema fields | All playbook fields present | ✅ PASS | Correct bounds, auto-validation |
| Market Analyst soul | Calculate confluence A/B/C | ✅ PASS | Explicit instructions |
| Market Analyst soul | Identify setup A/B/C/D | ✅ PASS | Criteria listed |
| Market Analyst soul | Report disqualifiers | ✅ PASS | Explicit output format |
| Research Agent soul | Validate setup criteria | ⚠️ PARTIAL | Documented, not enforced |
| Research Agent soul | Enforce confluence ≥6 | ❌ **MISSING** | Documented, not enforced |
| Research Agent soul | Enforce disqualifiers | ❌ **MISSING** | Documented, not enforced |
| Trader Agent soul | EV gate check | ✅ PASS | Instructions present |
| Risk & PM soul | Confluence-based sizing | ✅ PASS | §7 table documented |
| Risk & PM soul | 2% hard cap | ⚠️ PARTIAL | Documented, not enforced |
| Orchestrator | Passes MarketReport to PM | ✅ PASS | Fixed in 93d980e |
| Orchestrator | Confluence threshold gate | ❌ **MISSING** | No code enforcement |
| Database | Records confluence/setup | ✅ PASS | Metadata persisted |
| Tests | Threshold enforcement | ❌ **MISSING** | No test coverage |

---

## 13. Recommendations

### Priority 1 (High): Add Programmatic Enforcement
1. **Confluence ≥6 gate** in orchestrator after Market Analyst step
2. **Disqualifier gate** in orchestrator after Market Analyst step
3. **Unit tests** for both gates

### Priority 2 (Medium): Add Safety Checks
1. **2% position size cap** enforcement after Risk & PM decision
2. **Setup criteria validation** helper function that Market Analyst can call

### Priority 3 (Low): Documentation
1. Update AUDIT_REPORT.md with this gap
2. Add comment in orchestrator explaining why gates exist

---

## 14. Conclusion

**Schema implementation: ✅ Excellent** — All required fields present with correct bounds and validation.

**Soul documentation: ✅ Strong** — All four souls correctly reference playbook sections and document expected behavior.

**Code enforcement: ❌ Incomplete** — Critical threshold and disqualifier rules exist only as LLM instructions, not code guards. This creates risk if:
- LLM misinterprets instructions
- Future prompt changes weaken enforcement
- Developer assumes rule is enforced in code

**Recommended action:** Add programmatic gates in orchestrator for confluence threshold and disqualifiers. Current implementation is ~85% complete — the missing 15% is moving rule enforcement from "LLM should do this" to "code enforces this."

---

**Audit completed:** 2026-06-30  
**Files reviewed:** 8 (schemas.py, orchestrator.py, 4 soul files, test_orchestrator.py, AUDIT_REPORT.md)  
**Lines analyzed:** ~1,200
