# 🤖 Bot Testing Guide — @Akmalhermes_bot

**Bot:** `@Akmalhermes_bot`  
**Status:** ✅ Connected & Ready  
**Mode:** Testing (manual cycles only, no scheduler yet)

---

## 📋 Test Commands

### 1. `/status` — Check System Status
```
Expected output:
- System: 🟢 RUNNING / 🔴 PAUSED
- Last cycle: <cycle_id> at <time>
- History: <count>
```

### 2. `/model` — Show Available Providers
```
Expected output:
- Current provider (xiaomi)
- List of available providers with models
- Usage instructions
```

### 3. `/model zyloo` — Switch Provider
```
Expected output:
- ✅ Switched to zyloo (claude-opus-4-7)
- Berlaku mulai cycle berikutnya
```

### 4. `/history` — Show Last 5 Cycles
```
Expected output:
- List of last 5 cycle IDs with timestamps and decisions
- Or: "Belum ada history" if no cycles yet
```

### 5. `/run` — Manual Cycle (Admin Only)
```
Expected output:
- ⏳ Menjalankan 1 cycle manual...
- Then: Cycle result with decision/SKIP + reasoning
- Format:
  🟢/🔴/⚪ Cycle <id> — <time>
  Decision: UP/DOWN/SKIP
  Confidence: X/10
  Position size: $X.XX
  Reasoning: ...
  Latency: X.Xs
```

### 6. `/pause` — Pause Scheduler (Admin Only)
```
Expected output:
- ⏸ Paused. /resume untuk lanjut.
```

### 7. `/resume` — Resume Scheduler (Admin Only)
```
Expected output:
- ▶️ Resumed.
```

---

## ✅ Test Checklist

**Basic Connectivity:**
- [ ] `/status` returns system status
- [ ] `/model` shows current provider (xiaomi)
- [ ] `/history` shows empty or existing cycles

**Admin Commands:**
- [ ] `/run` executes one cycle (takes ~60-90s)
- [ ] Cycle result shows decision or FORCED SKIP
- [ ] Confluence gate enforcement visible in output
- [ ] `/pause` pauses system
- [ ] `/resume` resumes system

**Provider Switching:**
- [ ] `/model` lists available providers
- [ ] `/model zyloo` switches to Zyloo (Opus 4-7)
- [ ] `/model xiaomi` switches back to Xiaomi (MiMo v2.5)

**Enforcement Gates (Expected in `/run` output):**
- [ ] If confluence <6 → FORCED SKIP with reason
- [ ] If disqualifiers active → FORCED SKIP with reason
- [ ] If position >2% account → Position capped with flag

---

## 🧪 Test Scenarios

### Scenario 1: Basic Functionality Test
1. Send `/status` → verify system running
2. Send `/model` → verify xiaomi active
3. Send `/history` → verify empty or has data

### Scenario 2: Manual Cycle Test
1. Send `/run` → wait 60-90s
2. Verify output format correct
3. Check if confluence gate activated (likely SKIP due to low confluence)
4. Check verification flags displayed

### Scenario 3: Provider Switch Test
1. Send `/model` → note current provider
2. Send `/model zyloo` → verify switch confirmation
3. Send `/model` again → verify zyloo now current
4. Send `/model xiaomi` → switch back

### Scenario 4: Admin Controls Test
1. Send `/pause` → verify paused message
2. Send `/status` → verify shows PAUSED
3. Send `/resume` → verify resumed message
4. Send `/status` → verify shows RUNNING

---

## 📊 Expected Behavior

**Confluence Gate (from test):**
- ✅ Market Analyst runs successfully
- ✅ Outputs confluence score (0-10)
- ✅ If <6 → Pipeline stops immediately
- ✅ Returns: "FORCED SKIP: Confluence score X/10 insufficient (threshold: 6)"
- ✅ Verification flag: "PLAYBOOK GATE: Confluence X/10 below threshold 6 (§7)"

**Normal Flow (if confluence ≥6):**
- Market Analyst → Research Agent → Trader → Risk PM
- Final decision: UP/LEAN_UP/SKIP/LEAN_DOWN/DOWN
- Position size capped at 2% of account balance

**Latency:**
- Each LLM call: ~20-30s (MiMo v2.5 Pro)
- Total cycle: 60-120s (4 agents if all run)
- Forced SKIP: ~20-30s (only Market Analyst runs)

---

## 🔍 What to Look For

**✅ Good Signs:**
- Bot responds to all commands
- `/run` completes without errors
- Enforcement gates activate correctly
- Cycle results formatted properly
- Latency within expected range

**⚠️ Issues to Report:**
- Bot doesn't respond
- Commands return errors
- Cycle hangs or times out
- Formatting broken in output
- Gates not enforcing (allows confluence <6)

---

## 🚀 Next Steps After Testing

**If all tests pass:**
1. ✅ Enable scheduler (uncomment scheduler in main.py)
2. ✅ Set CYCLE_INTERVAL_SECONDS (default: 300 = 5 min)
3. ✅ Run with systemd service for 24/7 operation
4. ✅ Monitor first 10-20 cycles for issues

**If issues found:**
1. Document error messages
2. Check logs for stack traces
3. Report findings for debugging
4. Re-test after fixes

---

## 📝 Test Log Template

```
Date: 2026-06-30
Tester: <name>
Bot: @Akmalhermes_bot

Test 1: /status
- Result: ✅ PASS / ❌ FAIL
- Notes: 

Test 2: /model
- Result: ✅ PASS / ❌ FAIL
- Notes:

Test 3: /run
- Result: ✅ PASS / ❌ FAIL
- Cycle ID: 
- Decision: 
- Latency: 
- Notes:

Test 4: /model zyloo
- Result: ✅ PASS / ❌ FAIL
- Notes:

Test 5: /pause + /resume
- Result: ✅ PASS / ❌ FAIL
- Notes:

Overall: ✅ READY FOR DEPLOYMENT / ⚠️ NEEDS FIXES
```

---

**Bot Status:** 🟢 Ready for Testing  
**Admin ID:** 1124037834  
**Home Chat:** 1124037834  
**Commands:** 7 total (3 public, 4 admin-only)

Silakan test sesuai checklist di atas! 🚀
