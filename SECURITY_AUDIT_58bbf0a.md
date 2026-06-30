# Security Audit Report — btc-agent-system

**Date:** 2026-06-30  
**Commit:** 58bbf0a  
**Branch:** master  
**Scope:** Full security audit after `/model` command + zyloo provider addition  
**Previous Audit:** 93d980e (0 security issues)

---

## Executive Summary

**STATUS: 🟡 1 MEDIUM-RISK ISSUE FOUND**

New code added since last audit (93d980e → 58bbf0a) introduces **1 security vulnerability**:
- **PATH TRAVERSAL RISK** in `/model` command (telegram_bot/bot.py:151-159)

All other security checks pass. No hardcoded secrets, SQL injection, shell injection, or dangerous code execution patterns found.

---

## Security Findings

### 🟡 MEDIUM: Path Traversal in .env File Write

**File:** `telegram_bot/bot.py`  
**Lines:** 151-159  
**Severity:** MEDIUM  
**CWE:** CWE-73 (External Control of File Name or Path)

#### Vulnerable Code:
```python
# Update .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    content = env_path.read_text()
    if "LLM_PROVIDER=" in content:
        import re
        content = re.sub(r"LLM_PROVIDER=.*", f"LLM_PROVIDER={target}", content)
    else:
        content += f"\nLLM_PROVIDER={target}\n"
    env_path.write_text(content)
```

#### Issue:
The `/model` command writes user-controlled input (`target`) directly into the `.env` file without sanitization. While `target` is validated against the `PROVIDERS` dictionary (line 143), this validation only checks if the provider name exists—it does not prevent injection attacks.

#### Attack Scenario:
If a malicious provider name is added to `PROVIDERS` dictionary (e.g., through a supply chain attack or compromised config), an attacker with admin Telegram access could potentially inject:
- Newlines to add arbitrary environment variables
- Special characters to corrupt the .env file
- Path traversal sequences (though mitigated by Path() normalization)

#### Risk Assessment:
- **Likelihood:** LOW (requires admin Telegram access + compromised PROVIDERS dict)
- **Impact:** MEDIUM (could corrupt .env file, inject environment variables)
- **Overall Risk:** MEDIUM

#### Recommended Fix:
```python
# Validate target is alphanumeric + safe chars only
import re
if not re.match(r'^[a-z0-9_-]+$', target):
    await update.message.reply_text("❌ Invalid provider name format")
    return

# Validate against whitelist
if target not in PROVIDERS:
    await update.message.reply_text(...)
    return

# Safe write with backup
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    # Create backup before modifying
    backup_path = env_path.with_suffix(".env.backup")
    shutil.copy2(env_path, backup_path)
    
    content = env_path.read_text()
    # Use more restrictive regex with word boundaries
    if "LLM_PROVIDER=" in content:
        content = re.sub(r'^LLM_PROVIDER=.*$', f'LLM_PROVIDER={target}', content, flags=re.MULTILINE)
    else:
        content += f"\nLLM_PROVIDER={target}\n"
    env_path.write_text(content)
```

---

## Security Checks — All Files

### ✅ Hardcoded Secrets/Tokens
**Status:** PASS  
**Files Scanned:** All .py files in core/, telegram_bot/, root  
**Patterns Checked:**
- API keys (sk-, xoxb-, ghp_, gho_, AKIA)
- Hardcoded passwords, secrets, tokens
- Bearer tokens, JWT tokens

**Result:** No hardcoded secrets found. All sensitive values loaded from environment variables via `os.getenv()`.

---

### ✅ SQL Injection
**Status:** PASS  
**Files:** core/data/db.py  
**Lines Checked:** 87, 102, 115, 120, 125, 138, 178, 225, 248, 282, 294

**Analysis:**
All SQL queries use **parameterized statements** with `?` placeholders:
```python
await db.execute(
    "INSERT INTO cycles (cycle_id, timestamp, rating, ...) VALUES (?,?,?,?,?,?,?)",
    (cycle_id, timestamp.isoformat(), rating, confidence, ...)
)
```

No string concatenation, f-strings, or .format() used in SQL queries. All user input properly escaped by aiosqlite.

**Result:** No SQL injection vulnerabilities.

---

### ✅ Shell Injection
**Status:** PASS  
**Patterns Checked:**
- `subprocess.call/run/Popen` with user input
- `os.system()`, `os.popen()`
- `shell=True` with unsanitized input

**Result:** No shell command execution found in codebase. All external API calls use httpx/websockets libraries with proper parameter handling.

---

### ✅ Dangerous Code Execution
**Status:** PASS  
**Patterns Checked:**
- `eval()` / `exec()`
- `pickle.loads()` / `pickle.load()`
- `__import__()` with user input
- Dynamic code generation

**Result:** No dangerous code execution patterns found.

---

### ✅ Path Traversal (Other Files)
**Status:** PASS (except telegram_bot/bot.py)  
**Files Checked:**
- core/agent.py: soul_path uses SOULS_DIR constant + file_safe name
- core/data/db.py: database path controlled by application (no user input)
- All file operations use Path() objects with safe concatenation

**Result:** No path traversal vulnerabilities except the .env write issue noted above.

---

## Code-Specific Analysis

### telegram_bot/bot.py (NEW CODE)
**Lines 121-171:** `/model` command implementation
- ✅ Admin-only access check (line 81-83, inherited pattern)
- 🟡 **MEDIUM RISK:** User input written to .env file without sanitization (line 156-159)
- ✅ Provider whitelist validation (line 143)
- ✅ Markdown injection mitigated by `_escape_md()` helper (line 18-23)

### core/agent.py (NEW CODE)
**Lines 28-64:** Provider registry
- ✅ Hardcoded provider configs (no user input)
- ✅ API keys from environment variables only
- ✅ Fallback logic safe

**Lines 67-101:** `_get_config()` refactor
- ✅ Provider selection from env var (controlled by .env file)
- ✅ No code injection risk
- ✅ Safe string formatting

---

## Dependency Security

**New Dependencies Since Last Audit:**
- None (58bbf0a only modifies existing code)

**Existing Dependencies:**
- aiosqlite: Safe parameterized queries
- httpx: Safe HTTP client (no shell execution)
- websockets: Safe WebSocket client
- openai SDK: Official SDK, no known vulnerabilities
- anthropic SDK: Official SDK, no known vulnerabilities
- python-telegram-bot: Well-maintained, no critical CVEs

---

## Admin Access Control Review

**Admin Commands:**
- `/pause` — admin only ✅
- `/resume` — admin only ✅
- `/run` — admin only ✅
- `/model` — admin only ✅ (but vulnerable to .env injection)

**Admin ID Validation:**
```python
ADMIN_IDS = set(int(x) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit())

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
```
✅ Secure: Admin IDs loaded from environment variable, integer validation prevents injection.

---

## Environment Variable Handling

**Sensitive Variables:**
- `LLM_API_KEY` — loaded via os.getenv() ✅
- `TELEGRAM_BOT_TOKEN` — loaded via os.getenv() ✅
- `TELEGRAM_ADMIN_IDS` — loaded via os.getenv() ✅
- Provider-specific keys (ZYLOO_API_KEY, etc.) — loaded via os.getenv() ✅

**Security Posture:** ✅ SECURE  
All secrets loaded from environment, never logged or echoed to users.

---

## Data Validation

### Input Validation
- ✅ Telegram user input: Type-checked (admin IDs, command args)
- ✅ API responses: JSON parsing with error handling
- ✅ Database queries: Parameterized (no injection risk)
- 🟡 .env file writes: **INSUFFICIENT** (main finding)

### Output Sanitization
- ✅ Telegram markdown: Escaped via `_escape_md()` (prevents markdown injection)
- ✅ Log output: No sensitive data in logs
- ✅ Error messages: No stack traces to non-admins

---

## Recommendations

### Priority 1: Fix Path Traversal (MEDIUM)
**Action:** Sanitize provider name input before writing to .env file  
**File:** telegram_bot/bot.py, cmd_model()  
**Timeline:** Before production deployment

### Priority 2: Add .env File Backup
**Action:** Create backup before modifying .env to allow recovery from corruption  
**File:** telegram_bot/bot.py, cmd_model()  
**Timeline:** Nice to have

### Priority 3: Rate Limiting
**Action:** Add rate limiting to admin commands to prevent abuse  
**File:** telegram_bot/bot.py  
**Timeline:** Future enhancement

### Priority 4: Audit Logging
**Action:** Log all admin command usage (who, when, what changed)  
**File:** telegram_bot/bot.py  
**Timeline:** Future enhancement

---

## Comparison with Previous Audit (93d980e)

| Category | 93d980e | 58bbf0a | Change |
|----------|---------|---------|--------|
| Hardcoded Secrets | 0 | 0 | ✅ No change |
| SQL Injection | 0 | 0 | ✅ No change |
| Shell Injection | 0 | 0 | ✅ No change |
| eval/exec | 0 | 0 | ✅ No change |
| pickle.loads | 0 | 0 | ✅ No change |
| Path Traversal | 0 | 1 | 🟡 +1 issue |
| **Total Issues** | **0** | **1** | **+1** |

---

## Conclusion

The codebase is generally **secure** with good security practices:
- ✅ No hardcoded secrets
- ✅ Parameterized SQL queries
- ✅ No shell command execution
- ✅ Input validation on most surfaces
- ✅ Admin access controls in place

**One medium-risk issue** introduced in commit 58bbf0a:
- 🟡 Path traversal risk in `/model` command .env file write

**Recommendation:** Apply input sanitization fix before production deployment. The risk is mitigated by admin-only access, but defense-in-depth is recommended.

**Overall Security Rating:** 🟡 MEDIUM (was ✅ HIGH at 93d980e)

---

**Auditor:** Hermes Agent (Security Subagent)  
**Audit Completed:** 2026-06-30
