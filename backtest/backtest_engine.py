"""
backtest_engine.py — Run orchestrator on historical market windows.

Simulates live trading by:
1. Loading historical data via MarketSimulator
2. Running orchestrator.run_cycle() for each window
3. Recording decisions (UP/DOWN/SKIP)
4. Simulating outcomes based on actual price movement
5. Saving results to JSON for analysis

Usage:
    python backtest/backtest_engine.py --start 2026-04-01 --end 2026-06-30
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from backtest.market_simulator import MarketSimulator
from core.orchestrator import Orchestrator
from core.schemas import PortfolioRating, CycleLog

# Suppress verbose logs from orchestrator during backtest
logging.getLogger("orchestrator").setLevel(logging.WARNING)
logging.getLogger("agent").setLevel(logging.WARNING)

logger = logging.getLogger("backtest_engine")


class BacktestResult:
    """Single cycle result in backtest."""
    
    def __init__(
        self,
        cycle_id: str,
        timestamp: datetime,
        decision: Optional[PortfolioRating],
        confidence: Optional[int],
        position_size_usd: float,
        entry_price: float,
        confluence_score: int,
        setup_match: Optional[str],
        disqualifiers: List[str],
        verification_flags: List[str],
        latency_seconds: float,
        error: Optional[str] = None,
    ):
        self.cycle_id = cycle_id
        self.timestamp = timestamp.isoformat()
        self.decision = decision.value if decision else "SKIP"
        self.confidence = confidence or 0
        self.position_size_usd = position_size_usd
        self.entry_price = entry_price
        self.confluence_score = confluence_score
        self.setup_match = setup_match or "none"
        self.disqualifiers = disqualifiers
        self.verification_flags = verification_flags
        self.latency_seconds = latency_seconds
        self.error = error
        
        # Will be filled after outcome simulation
        self.exit_price: Optional[float] = None
        self.actual_move_pct: Optional[float] = None
        self.win: Optional[bool] = None
        self.pnl_usd: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "confidence": self.confidence,
            "position_size_usd": self.position_size_usd,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "actual_move_pct": self.actual_move_pct,
            "confluence_score": self.confluence_score,
            "setup_match": self.setup_match,
            "disqualifiers": self.disqualifiers,
            "verification_flags": self.verification_flags,
            "win": self.win,
            "pnl_usd": self.pnl_usd,
            "latency_seconds": self.latency_seconds,
            "error": self.error,
        }


class BacktestEngine:
    """
    Backtest engine for btc-agent-system.
    
    Runs orchestrator on historical data and simulates trading outcomes.
    """
    
    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        dry_run: bool = True,
    ):
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.dry_run = dry_run
        
        self.simulator = MarketSimulator(data_dir)
        self.orchestrator: Optional[Orchestrator] = None
        self.results: List[BacktestResult] = []
        
        output_dir.mkdir(exist_ok=True, parents=True)
    
    def setup_orchestrator(self):
        """Initialize orchestrator without live data clients (backtest mode)."""
        # Orchestrator with no data clients (we provide market_context directly)
        self.orchestrator = Orchestrator(
            binance_client=None,
            polymarket_client=None,
            liquidation_tracker=None,
            database=None,  # No DB persistence in backtest
        )
        logger.info("Orchestrator initialized for backtest mode")
    
    async def simulate_outcome(
        self,
        result: BacktestResult,
        entry_time: datetime,
        window_minutes: int = 5,
    ):
        """
        Simulate trade outcome based on actual price movement.
        
        For a 5-minute prediction:
        - Entry: price at entry_time
        - Exit: price at entry_time + window_minutes
        - Win: UP decision and price increased, or DOWN decision and price decreased
        """
        if result.decision == "SKIP":
            result.win = None
            result.pnl_usd = 0.0
            return
        
        exit_time = entry_time + timedelta(minutes=window_minutes)
        exit_price = self.simulator.get_price_at(exit_time)
        
        if exit_price is None:
            logger.warning(f"No exit price at {exit_time} for cycle {result.cycle_id}")
            result.win = None
            result.pnl_usd = 0.0
            return
        
        result.exit_price = exit_price
        result.actual_move_pct = ((exit_price - result.entry_price) / result.entry_price) * 100
        
        # Determine win/loss
        if result.decision in ["UP", "LEAN_UP"]:
            result.win = exit_price > result.entry_price
        elif result.decision in ["DOWN", "LEAN_DOWN"]:
            result.win = exit_price < result.entry_price
        else:
            result.win = None  # Should not happen
        
        # Simulate PnL (simplified: assume 1:1 odds, no fees/slippage for now)
        if result.win:
            result.pnl_usd = result.position_size_usd  # Win = double position
        else:
            result.pnl_usd = -result.position_size_usd  # Loss = lose position
    
    async def run_backtest(
        self,
        start_date: str,
        end_date: str,
        symbol: str = "BTCUSDT",
        max_cycles: Optional[int] = None,
    ):
        """
        Run full backtest on historical data.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            symbol: Trading symbol (default BTCUSDT)
            max_cycles: Max cycles to run (None = all available)
        """
        logger.info("=" * 70)
        logger.info("BACKTEST ENGINE STARTING")
        logger.info("=" * 70)
        logger.info(f"Period: {start_date} to {end_date}")
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Max cycles: {max_cycles or 'unlimited'}")
        logger.info(f"Dry run: {self.dry_run}")
        
        # Load data
        self.simulator.load_data(start_date, end_date, symbol)
        self.setup_orchestrator()
        
        # Iterate windows
        cycle_count = 0
        skip_count = 0
        error_count = 0
        
        start_time_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end_time_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
        
        logger.info("=" * 70)
        logger.info("RUNNING CYCLES")
        logger.info("=" * 70)
        
        for timestamp, market_context in self.simulator.iterate_windows(start_time_dt, end_time_dt):
            if max_cycles and cycle_count >= max_cycles:
                logger.info(f"Reached max cycles ({max_cycles}), stopping")
                break
            
            cycle_count += 1
            
            # Progress logging
            if cycle_count % 50 == 0:
                logger.info(f"Progress: {cycle_count} cycles processed...")
            
            try:
                # Run orchestrator cycle
                cycle_log: CycleLog = await self.orchestrator.run_cycle(market_context)
                
                # Extract market data (confluence, setup, disqualifiers)
                confluence_score = 0
                setup_match = None
                disqualifiers = []
                
                # Parse market_context to extract confluence (hacky but works for backtest)
                # In real backtest we'd capture Market Analyst output directly
                if "Confluence" in market_context or "CONFLUENCE" in market_context:
                    # For now, we'll set placeholder values
                    # TODO: Capture actual Market Analyst output
                    confluence_score = 6  # Placeholder
                
                # Extract from cycle_log
                entry_price = self.simulator.get_price_at(timestamp)
                
                if cycle_log.final_decision:
                    decision = cycle_log.final_decision.rating
                    confidence = cycle_log.final_decision.confidence
                    position_size = cycle_log.final_decision.position_size_usd
                else:
                    decision = None
                    confidence = 0
                    position_size = 0.0
                
                result = BacktestResult(
                    cycle_id=cycle_log.cycle_id,
                    timestamp=timestamp,
                    decision=decision,
                    confidence=confidence,
                    position_size_usd=position_size,
                    entry_price=entry_price or 0.0,
                    confluence_score=confluence_score,
                    setup_match=setup_match,
                    disqualifiers=disqualifiers,
                    verification_flags=cycle_log.verification_flags,
                    latency_seconds=cycle_log.latency_seconds.get("total", 0.0),
                    error=cycle_log.error,
                )
                
                # Simulate outcome
                await self.simulate_outcome(result, timestamp)
                
                self.results.append(result)
                
                if result.decision == "SKIP":
                    skip_count += 1
                
            except Exception as e:
                logger.error(f"Cycle {cycle_count} failed: {e}")
                error_count += 1
                continue
        
        logger.info("=" * 70)
        logger.info("BACKTEST COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Total cycles: {cycle_count}")
        logger.info(f"Skipped: {skip_count} ({skip_count/cycle_count*100:.1f}%)")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Traded: {cycle_count - skip_count - error_count}")
        
        # Save results
        self.save_results(start_date, end_date)
    
    def save_results(self, start_date: str, end_date: str):
        """Save backtest results to JSON."""
        output_file = self.output_dir / f"backtest_{start_date}_{end_date}.json"
        
        results_dict = {
            "metadata": {
                "start_date": start_date,
                "end_date": end_date,
                "total_cycles": len(self.results),
                "skip_count": sum(1 for r in self.results if r.decision == "SKIP"),
                "traded_count": sum(1 for r in self.results if r.decision != "SKIP"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "results": [r.to_dict() for r in self.results],
        }
        
        output_file.write_text(json.dumps(results_dict, indent=2))
        logger.info(f"Results saved to {output_file}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Run backtest on historical BTC data")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading symbol")
    parser.add_argument("--max-cycles", type=int, help="Max cycles to run (for testing)")
    parser.add_argument("--output-dir", default="backtest_results", help="Output directory")
    
    args = parser.parse_args()
    
    # Load env vars for LLM config
    load_dotenv()
    
    # Verify LLM_API_KEY is set
    if not os.getenv("LLM_API_KEY"):
        logger.error("LLM_API_KEY not set in .env — cannot run backtest")
        return
    
    data_dir = Path(__file__).parent.parent / "data"
    output_dir = Path(__file__).parent.parent / args.output_dir
    
    engine = BacktestEngine(data_dir, output_dir)
    
    await engine.run_backtest(
        start_date=args.start,
        end_date=args.end,
        symbol=args.symbol,
        max_cycles=args.max_cycles,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    asyncio.run(main())
