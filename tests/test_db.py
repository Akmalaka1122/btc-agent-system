"""test_db.py — database and circuit breaker logic tests."""
import pytest
import os
import asyncio
import tempfile
from datetime import datetime, timezone
from core.data.db import Database


def _run(coro):
    """Run async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db():
    """Create a temp database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database = Database(path)
    _run(database.init())
    yield database
    _run(database.close())
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestDatabase:
    def test_init_creates_tables(self, db):
        import aiosqlite
        async def _check():
            async with aiosqlite.connect(db.path) as conn:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                return [row[0] for row in await cursor.fetchall()]
        tables = _run(_check())
        assert "cycles" in tables
        assert "daily_stats" in tables
        assert "setup_stats" in tables

    def test_record_and_resolve_cycle(self, db):
        now = datetime.now(timezone.utc)
        _run(db.record_cycle(
            cycle_id="test-001", timestamp=now,
            rating="UP", confidence=7, position_size_usd=500.0,
            setup_match="A", confluence_total=7,
        ))
        _run(db.resolve_cycle("test-001", pnl_usd=50.0))

        async def _check():
            import aiosqlite
            async with aiosqlite.connect(db.path) as conn:
                cursor = await conn.execute(
                    "SELECT pnl_usd, resolved FROM cycles WHERE cycle_id='test-001'"
                )
                return await cursor.fetchone()
        row = _run(_check())
        assert row[0] == 50.0
        assert row[1] == 1

    def test_circuit_breaker_no_trades(self, db):
        result = _run(db.check_circuit_breaker())
        assert result["trading_allowed"] is True
        assert result["reason"] is None

    def test_circuit_breaker_daily_loss_limit(self, db):
        now = datetime.now(timezone.utc)
        for i in range(5):
            _run(db.record_cycle(
                cycle_id=f"loss-{i}", timestamp=now,
                rating="UP", confidence=5, position_size_usd=500.0,
                setup_match="A", confluence_total=5,
            ))
            _run(db.resolve_cycle(f"loss-{i}", pnl_usd=-150.0))

        result = _run(db.check_circuit_breaker(account_balance=10000.0))
        assert result["trading_allowed"] is False
        assert result["reason"] == "daily_loss_limit_hit"

    def test_circuit_breaker_consecutive_losses(self, db):
        now = datetime.now(timezone.utc)
        for i in range(3):
            _run(db.record_cycle(
                cycle_id=f"streak-{i}", timestamp=now,
                rating="UP", confidence=5, position_size_usd=100.0,
                setup_match="B", confluence_total=5,
            ))
            _run(db.resolve_cycle(f"streak-{i}", pnl_usd=-50.0))

        result = _run(db.check_circuit_breaker(account_balance=100000.0))
        assert result["trading_allowed"] is False
        assert result["reason"] == "consecutive_loss_cooldown"

    def test_circuit_breaker_resets_on_win(self, db):
        now = datetime.now(timezone.utc)
        for i in range(2):
            _run(db.record_cycle(
                cycle_id=f"loss-{i}", timestamp=now,
                rating="UP", confidence=5, position_size_usd=100.0,
                setup_match="A", confluence_total=5,
            ))
            _run(db.resolve_cycle(f"loss-{i}", pnl_usd=-50.0))

        _run(db.record_cycle(
            cycle_id="win-1", timestamp=now,
            rating="UP", confidence=7, position_size_usd=200.0,
            setup_match="A", confluence_total=7,
        ))
        _run(db.resolve_cycle("win-1", pnl_usd=100.0))

        result = _run(db.check_circuit_breaker(account_balance=100000.0))
        assert result["trading_allowed"] is True

    def test_manual_circuit_breaker(self, db):
        _run(db.activate_circuit_breaker(reason="manual test"))
        result = _run(db.check_circuit_breaker())
        assert result["trading_allowed"] is False
        assert result["reason"] == "circuit_breaker_manually_activated"

        _run(db.deactivate_circuit_breaker())
        result = _run(db.check_circuit_breaker())
        assert result["trading_allowed"] is True

    def test_setup_winrate(self, db):
        now = datetime.now(timezone.utc)
        for i in range(3):
            _run(db.record_cycle(
                cycle_id=f"a-win-{i}", timestamp=now,
                rating="UP", confidence=7, position_size_usd=200.0,
                setup_match="A", confluence_total=7,
            ))
            _run(db.resolve_cycle(f"a-win-{i}", pnl_usd=50.0))
        for i in range(2):
            _run(db.record_cycle(
                cycle_id=f"a-loss-{i}", timestamp=now,
                rating="UP", confidence=5, position_size_usd=200.0,
                setup_match="A", confluence_total=5,
            ))
            _run(db.resolve_cycle(f"a-loss-{i}", pnl_usd=-30.0))

        result = _run(db.get_setup_winrate("A"))
        assert result["sample_size"] == 5
        assert result["win_rate"] == 0.6
        assert result["wins"] == 3
        assert result["losses"] == 2

    def test_setup_winrate_empty(self, db):
        result = _run(db.get_setup_winrate("Z"))
        assert result["sample_size"] == 0
        assert result["win_rate"] is None

    def test_daily_summary(self, db):
        now = datetime.now(timezone.utc)
        _run(db.record_cycle(
            cycle_id="sum-1", timestamp=now,
            rating="UP", confidence=7, position_size_usd=300.0,
            setup_match="A", confluence_total=7,
        ))
        _run(db.resolve_cycle("sum-1", pnl_usd=100.0))
        _run(db.record_cycle(
            cycle_id="sum-2", timestamp=now,
            rating="DOWN", confidence=6, position_size_usd=200.0,
            setup_match="B", confluence_total=6,
        ))
        _run(db.resolve_cycle("sum-2", pnl_usd=-40.0))

        summary = _run(db.get_daily_summary())
        assert summary["trade_count"] == 2
        assert summary["win_count"] == 1
        assert summary["loss_count"] == 1
        assert summary["total_pnl_usd"] == 60.0
