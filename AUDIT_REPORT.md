# ECC Audit Report — btc-agent-system

**Date:** 2026-06-30
**Commit:** 472fee4
**Branch:** feat/initial-pipeline
**Reviewer:** Hermes Agent (automated)

---

## Security Scan ✅ PASS

| Check | Result |
|-------|--------|
| Hardcoded secrets | ✅ None found |
| Shell injection | ✅ None found |
| eval()/exec() | ✅ None found |
| pickle.loads() | ✅ None found |
| SQL injection | ✅ None found |
| Path traversal | ✅ None found |

## Code Compilation ✅ PASS

All 5 Python files compile without syntax errors.

## Findings

### 🔴 Errors (Logic/Runtime)

| ID | File | Line | Issue | Severity |
|----|------|------|-------|----------|
| E1 | `core/agent.py` | 89 | All exceptions re-raised as `AgentTimeoutError` — masks real error type (could be `AgentVerificationError`, network error, auth error) | ERROR |
| E2 | `main.py` | 27 | No validation that `LLM_API_KEY` is non-empty before starting — will crash at runtime with unhelpful error | ERROR |

### 🟡 Warnings

| ID | File | Line | Issue | Severity |
|----|------|------|-------|----------|
| W1 | `core/orchestrator.py` | 21 | `timeout_s=15` is very aggressive for LLM calls with full soul.md + structured output — expect frequent timeouts | WARNING |
| W2 | `core/orchestrator.py` | 65 | `asyncio.get_event_loop().time()` deprecated in Python 3.12+ — use `asyncio.get_running_loop().time()` | WARNING |
| W3 | `core/agent.py` | 58-63 | 13 separate `AsyncOpenAI` clients created (one per agent) — could share one client | WARNING |

### 🟢 Suggestions (Non-blocking)

| ID | File | Issue | Priority |
|----|------|-------|----------|
| S1 | Project | No tests — `tests/` directory missing entirely | LOW |
| S2 | `core/orchestrator.py` | `run_cycle` doesn't handle the case where `pm_result` is `None` (if `_safe_run` returns None) | LOW |
| S3 | `telegram_bot/bot.py` | `STATE["history"]` is in-memory only — lost on restart | LOW |
| S4 | Project | No `config/` module — all config scattered across `.env` reads | LOW |

## Verdict

**PASS with 2 errors to fix (E1, E2)** — no security issues found.

The codebase is clean, well-structured, and follows good async patterns. The 13-agent pipeline architecture is sound. Main concerns are operational (timeout tuning, error handling, input validation) rather than security-related.

## Recommended Fixes

### E1: agent.py — Better error classification
```python
# BEFORE:
except Exception as e:
    raise AgentTimeoutError(f"{self.name} failed: {e}")

# AFTER:
except Exception as e:
    if "timeout" in str(e).lower() or "timed out" in str(e).lower():
        raise AgentTimeoutError(f"{self.name} timed out: {e}")
    raise AgentTimeoutError(f"{self.name} failed: {e}")
```

### E2: main.py — Validate API key on startup
```python
# Add before main():
if not os.getenv("LLM_API_KEY"):
    raise RuntimeError("LLM_API_KEY not set in .env — copy .env.example to .env and fill in your API key")
```

### W1: Increase timeout
```python
# In orchestrator.py, change timeout_s from 15 to 30-45
self.price_analyst = Agent("BTC Price Analyst", "01-btc-price-analyst.soul.md", timeout_s=30)
```
