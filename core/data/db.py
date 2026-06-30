"""
db.py — SQLite persistence layer untuk circuit breakers dan cycle history.

Tables:
  - cycles: per-cycle record (rating, confluence, PnL, setup type)
  - daily_stats: aggregated daily stats (PnL, trade count, loss streak)
  - setup_stats: per-setup rolling win rate

Cukup untuk single-instance deployment.
Upgrade ke Postgres kalau nanti multi-instance.
"""
import aiosqlite
import logging
from datetime import datetime, timezone

logger = logging.getLogger("db")

DB_PATH = "btc_agent_system.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    rating TEXT,
    confidence INTEGER,
    position_size_usd REAL,
    setup_match TEXT,
    confluence_total INTEGER,
    pnl_usd REAL,
    resolved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    total_pnl_usd REAL DEFAULT 0,
    trade_count INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    circuit_breaker_active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS setup_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_match TEXT,
    timestamp TEXT NOT NULL,
    pnl_usd REAL,
    resolved INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cycles_timestamp ON cycles(timestamp);
CREATE INDEX IF NOT EXISTS idx_cycles_setup ON cycles(setup_match);
CREATE INDEX IF NOT EXISTS idx_setup_stats_match ON setup_stats(setup_match, resolved);
"""


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        """Initialize DB — create tables if not exist. Call once at startup."""
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info(f"Database initialized: {self.path}")

    async def close(self):
        """Close DB connection. Call at shutdown."""
        if self._db:
            await self._db.close()
            self._db = None

    async def record_cycle(
        self,
        cycle_id: str,
        timestamp: datetime,
        rating: str,
        confidence: int,
        position_size_usd: float,
        setup_match: str,
        confluence_total: int,
    ):
        """Record a new cycle. Called by orchestrator after each cycle."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO cycles "
                "(cycle_id, timestamp, rating, confidence, position_size_usd, "
                "setup_match, confluence_total) VALUES (?,?,?,?,?,?,?)",
                (
                    cycle_id,
                    timestamp.isoformat(),
                    rating,
                    confidence,
                    position_size_usd,
                    setup_match,
                    confluence_total,
                ),
            )
            # Also record to setup_stats for per-setup tracking
            await db.execute(
                "INSERT INTO setup_stats (setup_match, timestamp) VALUES (?,?)",
                (setup_match, timestamp.isoformat()),
            )
            await db.commit()

    async def resolve_cycle(self, cycle_id: str, pnl_usd: float):
        """
        Mark cycle as resolved with actual PnL.
        Called after 5-min window resolves (win/loss known).
        """
        async with aiosqlite.connect(self.path) as db:
            # Update cycle
            await db.execute(
                "UPDATE cycles SET pnl_usd=?, resolved=1 WHERE cycle_id=?",
                (pnl_usd, cycle_id),
            )
            # Update corresponding setup_stat
            cursor = await db.execute(
                "SELECT timestamp FROM cycles WHERE cycle_id=?", (cycle_id,)
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    "UPDATE setup_stats SET pnl_usd=?, resolved=1 "
                    "WHERE timestamp=? AND resolved=0",
                    (pnl_usd, row[0]),
                )
            await db.commit()
            await self._update_daily_stats(pnl_usd)

    async def _update_daily_stats(self, pnl_usd: float):
        """Update aggregated daily stats after a cycle resolves."""
        today = datetime.now(timezone.utc).date().isoformat()
        is_win = pnl_usd > 0
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO daily_stats "
                "(date, total_pnl_usd, trade_count, win_count, loss_count, consecutive_losses) "
                "VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET "
                "total_pnl_usd = total_pnl_usd + ?, "
                "trade_count = trade_count + 1, "
                "win_count = win_count + ?, "
                "loss_count = loss_count + ?, "
                "consecutive_losses = CASE WHEN ? < 0 THEN consecutive_losses + 1 ELSE 0 END",
                (
                    today,
                    pnl_usd,
                    1 if is_win else 0,
                    0 if is_win else 1,
                    1 if not is_win else 0,
                    pnl_usd,
                    1 if is_win else 0,
                    0 if is_win else 1,
                    pnl_usd,
                ),
            )
            await db.commit()

    async def check_circuit_breaker(
        self,
        account_balance: float = 10000.0,
        daily_loss_limit_pct: float = 6.0,
        max_consecutive_losses: int = 3,
    ) -> dict:
        """
        Playbook §8 Risk Circuit Breakers check.
        Returns {"trading_allowed": bool, "reason": str|None}

        Triggers:
          1. Daily loss >= 6% of account balance
          2. 3+ consecutive losses (cooldown)
        """
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT total_pnl_usd, consecutive_losses, circuit_breaker_active "
                "FROM daily_stats WHERE date=?",
                (today,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"trading_allowed": True, "reason": None, "details": "no trades today"}

            total_pnl, streak, cb_active = row

            # Check if manually activated
            if cb_active:
                return {
                    "trading_allowed": False,
                    "reason": "circuit_breaker_manually_activated",
                    "details": f"Daily PnL: ${total_pnl:.2f}, Streak: {streak}",
                }

            loss_limit_usd = -(account_balance * daily_loss_limit_pct / 100)

            if total_pnl <= loss_limit_usd:
                return {
                    "trading_allowed": False,
                    "reason": "daily_loss_limit_hit",
                    "details": f"Loss ${abs(total_pnl):.2f} >= limit ${abs(loss_limit_usd):.2f}",
                }

            if streak >= max_consecutive_losses:
                return {
                    "trading_allowed": False,
                    "reason": "consecutive_loss_cooldown",
                    "details": f"{streak} consecutive losses (max: {max_consecutive_losses})",
                }

            return {
                "trading_allowed": True,
                "reason": None,
                "details": f"Daily PnL: ${total_pnl:.2f}, Streak: {streak}",
            }

    async def get_setup_winrate(self, setup_match: str, lookback: int = 50) -> dict:
        """
        Rolling win-rate per setup type (A/B/C/D).
        Digunakan untuk auto-pause setup yang underperform (playbook §9).
        """
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT pnl_usd FROM setup_stats "
                "WHERE setup_match=? AND resolved=1 "
                "ORDER BY timestamp DESC LIMIT ?",
                (setup_match, lookback),
            )
            rows = await cursor.fetchall()
            if not rows:
                return {"setup": setup_match, "sample_size": 0, "win_rate": None}
            wins = sum(1 for (pnl,) in rows if pnl > 0)
            total = len(rows)
            return {
                "setup": setup_match,
                "sample_size": total,
                "win_rate": round(wins / total, 3),
                "wins": wins,
                "losses": total - wins,
            }

    async def get_daily_summary(self) -> dict:
        """Get today's trading summary."""
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT total_pnl_usd, trade_count, win_count, loss_count, "
                "consecutive_losses, circuit_breaker_active "
                "FROM daily_stats WHERE date=?",
                (today,),
            )
            row = await cursor.fetchone()
            if not row:
                return {
                    "date": today,
                    "total_pnl_usd": 0,
                    "trade_count": 0,
                    "win_count": 0,
                    "loss_count": 0,
                    "consecutive_losses": 0,
                    "circuit_breaker_active": False,
                    "win_rate": None,
                }
            pnl, trades, wins, losses, streak, cb = row
            return {
                "date": today,
                "total_pnl_usd": pnl,
                "trade_count": trades,
                "win_count": wins,
                "loss_count": losses,
                "consecutive_losses": streak,
                "circuit_breaker_active": bool(cb),
                "win_rate": round(wins / trades, 3) if trades > 0 else None,
            }

    async def activate_circuit_breaker(self, reason: str = "manual"):
        """Manually activate circuit breaker (e.g., from Telegram /pause)."""
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO daily_stats (date, circuit_breaker_active) VALUES (?, 1) "
                "ON CONFLICT(date) DO UPDATE SET circuit_breaker_active=1",
                (today,),
            )
            await db.commit()
        logger.warning(f"Circuit breaker activated: {reason}")

    async def deactivate_circuit_breaker(self):
        """Manually deactivate circuit breaker (e.g., from Telegram /resume)."""
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE daily_stats SET circuit_breaker_active=0 WHERE date=?",
                (today,),
            )
            await db.commit()
        logger.info("Circuit breaker deactivated")
