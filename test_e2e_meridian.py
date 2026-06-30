"""
test_e2e_meridian.py — End-to-end test for Meridian Phases 1-4.

Tests the full pipeline:
1. Decision Log (Phase 1) — append + query
2. Conversational Handler (Phase 2) — natural language queries
3. Memory Injection (Phase 3) — inject into market context
4. Self-Correction (Phase 4) — outcomes + lessons

Run:
    cd ~/btc-agent-system && python test_e2e_meridian.py
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────
# Test harness
# ─────────────────────────────────────────────
PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


# ─────────────────────────────────────────────
# Phase 1: Decision Log
# ─────────────────────────────────────────────
def test_decision_log():
    print("\n" + "=" * 60)
    print("PHASE 1: Decision Log")
    print("=" * 60)
    
    from core.decision_log import DecisionLog
    from core.schemas import CycleLog, PortfolioDecision, PortfolioRating
    
    # Use temp file to avoid polluting real data
    tmp = Path(tempfile.mktemp(suffix=".json"))
    log = DecisionLog(log_file=tmp)
    
    # Test 1: Empty state
    recent = log.get_recent()
    check("Empty log returns empty list", len(recent) == 0)
    
    summary = log.get_summary()
    check("Empty summary returns 'No recent'", "No recent" in summary)
    
    # Test 2: Append a SKIP decision
    cycle_log = CycleLog(
        cycle_id="test_skip_001",
        timestamp=datetime.now(timezone.utc),
        step_status={"step1_market": "complete"},
        latency_seconds={"total": 30.0},
        verification_flags=["PLAYBOOK GATE: Confluence 2/10 below threshold 6"],
        final_decision=None,
        error="FORCED SKIP: Confluence score 2/10 insufficient (threshold: 6)",
    )
    
    decision = log.append(
        cycle_log,
        summary="Forced SKIP due to low confluence",
        reason="Confluence 2/10 below threshold 6",
        risks=["Missed potential move"],
        rejected=["UP (too low)", "DOWN (too low)"],
    )
    check("SKIP decision has correct type", decision["type"] == "skip")
    check("SKIP decision has cycle_id", decision["cycle_id"] == "test_skip_001")
    check("SKIP decision has reason", "threshold" in decision["reason"])
    check("SKIP decision has risks", len(decision["risks"]) == 1)
    check("SKIP decision has rejected", len(decision["rejected"]) == 2)
    
    # Test 3: Append a UP decision
    cycle_log2 = CycleLog(
        cycle_id="test_up_001",
        timestamp=datetime.now(timezone.utc),
        step_status={"step1_market": "complete", "step2_research": "complete"},
        latency_seconds={"total": 90.0},
        verification_flags=[],
        final_decision=PortfolioDecision(
            rating=PortfolioRating.UP,
            confidence=7,
            position_size_usd=200.0,
            expected_value=0.15,
            risk_reward_ratio=2.5,
            aggressive_case="Breakout to $61,500",
            conservative_case="Pullback to $59,500 first",
            neutral_sizing_case="$200 position on $10k account",
            reasoning="Strong momentum with volume confirmation",
            warnings=["Funding rate slightly elevated"],
        ),
        error=None,
    )
    
    decision2 = log.append(
        cycle_log2,
        summary="UP with 7/10 confidence",
        reason="Position: $200.00, EV: 0.1500",
    )
    check("UP decision has correct type", decision2["type"] == "up")
    check("UP decision has confidence", decision2["metrics"]["confidence"] == 7)
    check("UP decision has position size", decision2["metrics"]["position_size_usd"] == 200.0)
    
    # Test 4: Get recent
    recent = log.get_recent(limit=5)
    check("Recent returns 2 decisions", len(recent) == 2)
    check("Recent is newest first", recent[0]["type"] == "up")
    
    # Test 5: Filter by type
    skips = log.get_by_type("skip")
    check("Filter by type 'skip' returns 1", len(skips) == 1)
    ups = log.get_by_type("up")
    check("Filter by type 'up' returns 1", len(ups) == 1)
    
    # Test 6: Summary format
    summary = log.get_summary(limit=2)
    check("Summary contains RECENT DECISIONS", "RECENT DECISIONS" in summary)
    check("Summary contains decision info", "UP" in summary and "SKIP" in summary)
    
    # Test 7: Sanitization
    check("Sanitize works", log._sanitize("  hello   world  ") == "hello world")
    check("Sanitize handles None", log._sanitize(None) is None)
    check("Sanitize caps length", len(log._sanitize("x" * 500, max_len=100)) == 100)
    
    # Cleanup
    tmp.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Phase 3: Memory Injection
# ─────────────────────────────────────────────
def test_memory_injection():
    print("\n" + "=" * 60)
    print("PHASE 3: Memory Injection")
    print("=" * 60)
    
    from core.memory_injection import build_decision_context, inject_into_market_context
    
    # Test 1: Build context (may have data from previous tests)
    ctx = build_decision_context(limit=3)
    check("Build context returns string", isinstance(ctx, str))
    
    # Test 2: Inject into market context
    market = "## BTC Price Data\nCurrent price: $60,000"
    enhanced = inject_into_market_context(market, limit=3)
    check("Inject returns string", isinstance(enhanced, str))
    check("Inject preserves market data", "$60,000" in enhanced)
    
    # Test 3: With decisions (use the decision log from Phase 1 test)
    from core.decision_log import DecisionLog
    from core.schemas import CycleLog
    
    tmp = Path(tempfile.mktemp(suffix=".json"))
    dl = DecisionLog(log_file=tmp)
    dl.append(
        CycleLog(
            cycle_id="mem_001",
            timestamp=datetime.now(timezone.utc),
            step_status={},
            latency_seconds={},
            verification_flags=[],
            final_decision=None,
            error="FORCED SKIP",
        ),
        summary="Forced SKIP",
        reason="Low confluence",
    )
    
    # Need to mock the global instance — or just test the local instance
    # For E2E, test the function directly
    # We'll test with the local log
    summary = dl.get_summary(limit=3)
    check("Summary has content", len(summary) > 20)
    check("Summary has SKIP info", "SKIP" in summary)
    
    tmp.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Phase 4: Self-Correction
# ─────────────────────────────────────────────
def test_self_correction():
    print("\n" + "=" * 60)
    print("PHASE 4: Self-Correction")
    print("=" * 60)
    
    from core.self_correction import OutcomeTracker, LessonGenerator
    
    # Use temp files
    tmp_outcomes = Path(tempfile.mktemp(suffix=".json"))
    tmp_lessons = Path(tempfile.mktemp(suffix=".json"))
    
    tracker = OutcomeTracker(outcomes_file=tmp_outcomes)
    generator = LessonGenerator(lessons_file=tmp_lessons)
    
    # Test 1: Record entry
    entry = tracker.record_entry(
        cycle_id="sc_001",
        decision="UP",
        confidence=7,
        entry_price=60000.0,
        confluence=7,
        setup_match="A",
        reasoning="Momentum breakout",
        position_size_usd=200.0,
    )
    check("Entry recorded", entry["cycle_id"] == "sc_001")
    check("Entry is unresolved", entry["resolved"] is False)
    
    # Test 2: Resolve as WIN
    outcome = tracker.resolve_outcome("sc_001", exit_price=60200.0)
    check("Outcome resolved", outcome["resolved"] is True)
    check("Win detected", outcome["win"] is True)
    check("Positive PnL", outcome["pnl_usd"] > 0)
    check("Move calculated", outcome["actual_move_pct"] > 0)
    
    # Test 3: Record + resolve LOSS
    entry2 = tracker.record_entry(
        cycle_id="sc_002",
        decision="DOWN",
        confidence=8,
        entry_price=60000.0,
        confluence=8,
        setup_match="B",
        reasoning="Bearish divergence",
        position_size_usd=200.0,
    )
    outcome2 = tracker.resolve_outcome("sc_002", exit_price=60100.0)
    check("Loss detected", outcome2["win"] is False)
    check("Negative PnL", outcome2["pnl_usd"] < 0)
    
    # Test 4: Record + resolve whipsaw (<0.1% move, DOWN + tiny UP = loss)
    entry3 = tracker.record_entry(
        cycle_id="sc_003",
        decision="DOWN",
        confidence=6,
        entry_price=60000.0,
        confluence=6,
        setup_match="C",
        reasoning="Weak bearish signal",
        position_size_usd=100.0,
    )
    outcome3 = tracker.resolve_outcome("sc_003", exit_price=60030.0)  # 0.05% move UP = loss for DOWN
    check("Whipsaw detected", abs(outcome3["actual_move_pct"]) < 0.1)
    check("Whipsaw is a loss", outcome3["win"] is False)
    
    # Test 5: Get unresolved
    entry4 = tracker.record_entry(
        cycle_id="sc_004",
        decision="UP",
        confidence=5,
        entry_price=60000.0,
        confluence=5,
        setup_match="A",
        reasoning="Test pending",
        position_size_usd=100.0,
    )
    unresolved = tracker.get_unresolved()
    check("1 unresolved outcome", len(unresolved) == 1)
    check("Unresolved is sc_004", unresolved[0]["cycle_id"] == "sc_004")
    
    # Test 6: Stats (1 win + 2 losses from sc_001..sc_003)
    stats = tracker.get_stats()
    check("Stats: 3 resolved", stats["total_trades"] == 3)
    check("Stats: 1 win", stats["wins"] == 1)
    check("Stats: 2 losses", stats["losses"] == 2)
    check("Stats: win rate ~33.3%", abs(stats["win_rate"] - 1/3) < 0.01)
    check("Stats: 1 unresolved", stats["unresolved"] == 1)
    
    # Test 7: Generate lessons
    lesson1 = generator.generate_lesson(outcome)
    check("Win lesson generated", lesson1["outcome"] == "win")
    check("Win lesson has category", len(lesson1["category"]) > 0)
    check("Win lesson has analysis", len(lesson1["analysis"]) > 20)
    check("Win lesson has adjustment", len(lesson1["adjustment"]) > 10)
    
    lesson2 = generator.generate_lesson(outcome2)
    check("Loss lesson generated", lesson2["outcome"] == "loss")
    check("Loss lesson has category", len(lesson2["category"]) > 0)
    
    lesson3 = generator.generate_lesson(outcome3)
    check("Whipsaw lesson generated", lesson3["category"] == "whipsaw_loss")
    
    # Test 8: Lessons summary
    summary = generator.get_lessons_summary(limit=3)
    check("Summary contains LESSONS", "LESSONS" in summary)
    check("Summary has win emoji", "✅" in summary)
    check("Summary has loss emoji", "❌" in summary)
    check("Summary has adjustment", "→" in summary)
    
    # Test 9: Loss patterns
    patterns = generator.get_loss_patterns()
    check("Loss patterns has entries", len(patterns) > 0)
    check("Whipsaw pattern present", "whipsaw_loss" in patterns)
    
    # Cleanup
    tmp_outcomes.unlink(missing_ok=True)
    tmp_lessons.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Phase 2: Conversational Handler
# ─────────────────────────────────────────────
async def test_conversational():
    print("\n" + "=" * 60)
    print("PHASE 2: Conversational Handler")
    print("=" * 60)
    
    from telegram_bot.conversational import ConversationalHandler
    from core.decision_log import DecisionLog
    from core.schemas import CycleLog
    
    # Create handler with temp data
    handler = ConversationalHandler()
    
    # Test 1: Help command
    response = handler.show_help()
    check("Help has commands listed", "/help" in response)
    check("Help has query examples", "why skip" in response)
    
    # Test 2: Not understood
    response = handler.not_understood("xyzzy foobar")
    check("Not understood has fallback", "🤔" in response or "sorry" in response.lower())
    
    # Test 3: Handle "help" query
    response = await handler.handle("help")
    check("Handle 'help' returns help", "Conversational" in response)
    
    # Test 4: Handle "summary" query
    response = await handler.handle("summary")
    check("Handle 'summary' returns something", len(response) > 10)
    
    # Test 5: Handle "show recent"
    response = await handler.handle("show recent")
    check("Handle 'show recent' returns something", len(response) > 10)
    
    # Test 6: Handle "why skip?"
    response = await handler.handle("why skip?")
    check("Handle 'why skip?' returns something", len(response) > 10)
    
    # Test 7: Handle "show losses"
    response = await handler.handle("show losses")
    check("Handle 'show losses' returns something", len(response) > 10)
    
    # Test 8: Handle "show wins"
    response = await handler.handle("show wins")
    check("Handle 'show wins' returns something", len(response) > 10)
    
    # Test 9: Indonesian queries
    response = await handler.handle("kenapa skip?")
    check("Indonesian 'kenapa skip?' works", len(response) > 10)
    
    response = await handler.handle("tampilkan terakhir")
    check("Indonesian 'tampilkan terakhir' works", len(response) > 10)
    
    # Test 10: Unknown query
    response = await handler.handle("foobar baz qux")
    check("Unknown query returns fallback", "🤔" in response or "sorry" in response.lower())


# ─────────────────────────────────────────────
# Orchestrator Integration
# ─────────────────────────────────────────────
def test_orchestrator_integration():
    print("\n" + "=" * 60)
    print("ORCHESTRATOR INTEGRATION")
    print("=" * 60)
    
    # Test that orchestrator.py compiles and imports work
    try:
        from core.orchestrator import Orchestrator
        check("Orchestrator imports OK", True)
    except Exception as e:
        check("Orchestrator imports OK", False, str(e))
    
    # Test that all modules import cleanly
    modules = [
        "core.decision_log",
        "core.memory_injection",
        "core.self_correction",
        "telegram_bot.conversational",
    ]
    for mod in modules:
        try:
            __import__(mod)
            check(f"Import {mod}", True)
        except Exception as e:
            check(f"Import {mod}", False, str(e))
    
    # Test orchestrator has the new steps
    import inspect
    source = inspect.getsource(Orchestrator.run_cycle)
    check("STEP 0.6 in run_cycle", "STEP 0.6" in source)
    check("STEP 0.7 in run_cycle", "STEP 0.7" in source)
    check("STEP 6 in run_cycle", "STEP 6" in source)
    check("STEP 7 in run_cycle", "STEP 7" in source)
    check("memory_injection import", "memory_injection" in source)
    check("self_correction import", "self_correction" in source)
    check("decision_log import", "decision_log" in source)


# ─────────────────────────────────────────────
# File System Validation
# ─────────────────────────────────────────────
def test_file_structure():
    print("\n" + "=" * 60)
    print("FILE STRUCTURE VALIDATION")
    print("=" * 60)
    
    base = Path.home() / "btc-agent-system"
    
    required_files = [
        "core/decision_log.py",
        "core/memory_injection.py",
        "core/self_correction.py",
        "core/orchestrator.py",
        "telegram_bot/bot.py",
        "telegram_bot/conversational.py",
        "backtest/data_loader.py",
        "backtest/market_simulator.py",
        "backtest/backtest_engine.py",
        "backtest/results_analyzer.py",
        "docs/MERIDIAN_ADAPTATION_PLAN.md",
    ]
    
    for f in required_files:
        path = base / f
        check(f"File exists: {f}", path.exists())
    
    # Check line counts
    line_counts = {
        "core/decision_log.py": 150,
        "core/memory_injection.py": 40,
        "core/self_correction.py": 350,
        "telegram_bot/conversational.py": 250,
    }
    
    for f, min_lines in line_counts.items():
        path = base / f
        if path.exists():
            lines = len(path.read_text().splitlines())
            check(f"{f} >= {min_lines} lines", lines >= min_lines, f"got {lines}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    global PASS, FAIL
    
    print("=" * 60)
    print("MERIDIAN PHASES 1-4: END-TO-END TEST")
    print("=" * 60)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    
    # File structure
    test_file_structure()
    
    # Phase 1: Decision Log
    test_decision_log()
    
    # Phase 3: Memory Injection
    test_memory_injection()
    
    # Phase 4: Self-Correction
    test_self_correction()
    
    # Phase 2: Conversational (async)
    asyncio.run(test_conversational())
    
    # Orchestrator integration
    test_orchestrator_integration()
    
    # Summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    total = PASS + FAIL
    print(f"  ✅ Passed: {PASS}")
    print(f"  ❌ Failed: {FAIL}")
    print(f"  📊 Total:  {total}")
    print(f"  📈 Rate:   {PASS/total*100:.1f}%" if total > 0 else "  📈 Rate:   N/A")
    
    if FAIL == 0:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Phase 1: Decision Log — VERIFIED")
        print("✅ Phase 2: Conversational — VERIFIED")
        print("✅ Phase 3: Memory Injection — VERIFIED")
        print("✅ Phase 4: Self-Correction — VERIFIED")
        print("✅ Orchestrator Integration — VERIFIED")
        print("✅ File Structure — VERIFIED")
    else:
        print(f"\n⚠️  {FAIL} TESTS FAILED — review above")
    
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
