"""
results_analyzer.py — Analyze backtest results and compute metrics.

Reads backtest JSON output and computes:
- Win rate overall + per setup (A/B/C/D)
- Total PnL, average PnL per trade
- Sharpe ratio, max drawdown
- Confluence score distribution
- Gate activation rates (SKIP due to confluence/disqualifiers)
- Setup performance comparison

Usage:
    python backtest/results_analyzer.py --results backtest_results/backtest_2026-04-01_2026-06-30.json
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

import pandas as pd

logger = logging.getLogger("results_analyzer")


class BacktestAnalyzer:
    """Analyze backtest results and generate performance report."""
    
    def __init__(self, results_file: Path):
        self.results_file = results_file
        self.data: Optional[Dict] = None
        self.df: Optional[pd.DataFrame] = None
        
    def load_results(self):
        """Load backtest results JSON."""
        logger.info(f"Loading results from {self.results_file}")
        
        with open(self.results_file, "r") as f:
            self.data = json.load(f)
        
        # Convert to DataFrame for analysis
        self.df = pd.DataFrame(self.data["results"])
        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])
        
        logger.info(f"Loaded {len(self.df)} cycles")
    
    def compute_overall_metrics(self) -> Dict:
        """Compute overall backtest metrics."""
        if self.df is None:
            raise RuntimeError("Call load_results() first")
        
        total_cycles = len(self.df)
        skip_count = (self.df["decision"] == "SKIP").sum()
        traded_count = total_cycles - skip_count
        
        # Filter to traded cycles only
        traded = self.df[self.df["decision"] != "SKIP"].copy()
        
        if len(traded) == 0:
            logger.warning("No trades executed in backtest")
            return {
                "total_cycles": total_cycles,
                "skip_count": skip_count,
                "skip_rate": skip_count / total_cycles if total_cycles > 0 else 0,
                "traded_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl_per_trade": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
            }
        
        win_count = traded["win"].sum()
        loss_count = (~traded["win"]).sum()
        win_rate = win_count / len(traded) if len(traded) > 0 else 0
        
        total_pnl = traded["pnl_usd"].sum()
        avg_pnl = traded["pnl_usd"].mean()
        
        # Sharpe ratio (assume daily returns)
        returns = traded.groupby(traded["timestamp"].dt.date)["pnl_usd"].sum()
        sharpe = (returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0
        
        # Max drawdown
        cumulative_pnl = traded["pnl_usd"].cumsum()
        running_max = cumulative_pnl.cummax()
        drawdown = cumulative_pnl - running_max
        max_drawdown = drawdown.min()
        max_drawdown_pct = (max_drawdown / running_max.max() * 100) if running_max.max() > 0 else 0
        
        return {
            "total_cycles": total_cycles,
            "skip_count": skip_count,
            "skip_rate": skip_count / total_cycles if total_cycles > 0 else 0,
            "traded_count": traded_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl_per_trade": avg_pnl,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
        }
    
    def analyze_per_setup(self) -> Dict[str, Dict]:
        """Compute metrics per setup type (A/B/C/D)."""
        if self.df is None:
            raise RuntimeError("Call load_results() first")
        
        traded = self.df[self.df["decision"] != "SKIP"].copy()
        
        setup_stats = {}
        
        for setup in ["A", "B", "C", "D", "none"]:
            setup_trades = traded[traded["setup_match"] == setup]
            
            if len(setup_trades) == 0:
                continue
            
            win_count = setup_trades["win"].sum()
            loss_count = (~setup_trades["win"]).sum()
            win_rate = win_count / len(setup_trades) if len(setup_trades) > 0 else 0
            
            total_pnl = setup_trades["pnl_usd"].sum()
            avg_pnl = setup_trades["pnl_usd"].mean()
            
            # Expected value (avg win * win_rate - avg loss * loss_rate)
            avg_win = setup_trades[setup_trades["win"]]["pnl_usd"].mean() if win_count > 0 else 0
            avg_loss = abs(setup_trades[~setup_trades["win"]]["pnl_usd"].mean()) if loss_count > 0 else 0
            expected_value = (avg_win * win_rate) - (avg_loss * (1 - win_rate))
            
            setup_stats[setup] = {
                "trade_count": len(setup_trades),
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_pnl": avg_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "expected_value": expected_value,
            }
        
        return setup_stats
    
    def analyze_confluence_distribution(self) -> Dict:
        """Analyze confluence score distribution and gate activations."""
        if self.df is None:
            raise RuntimeError("Call load_results() first")
        
        confluence_dist = self.df["confluence_score"].value_counts().sort_index().to_dict()
        
        # Gate activations (SKIP reasons from verification_flags)
        confluence_gates = 0
        disqualifier_gates = 0
        
        for flags in self.df["verification_flags"]:
            flags_str = " ".join(flags) if isinstance(flags, list) else str(flags)
            if "Confluence" in flags_str or "confluence" in flags_str:
                confluence_gates += 1
            if "Disqualifier" in flags_str or "disqualifier" in flags_str:
                disqualifier_gates += 1
        
        return {
            "confluence_distribution": confluence_dist,
            "confluence_gate_activations": confluence_gates,
            "disqualifier_gate_activations": disqualifier_gates,
        }
    
    def generate_report(self) -> str:
        """Generate human-readable backtest report."""
        if self.df is None:
            raise RuntimeError("Call load_results() first")
        
        metadata = self.data["metadata"]
        overall = self.compute_overall_metrics()
        per_setup = self.analyze_per_setup()
        confluence = self.analyze_confluence_distribution()
        
        lines = []
        lines.append("=" * 80)
        lines.append("BACKTEST RESULTS")
        lines.append("=" * 80)
        lines.append(f"Period: {metadata['start_date']} to {metadata['end_date']}")
        lines.append(f"Generated: {metadata['generated_at']}")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append("OVERALL PERFORMANCE")
        lines.append("=" * 80)
        lines.append(f"Total cycles: {overall['total_cycles']:,}")
        lines.append(f"SKIP rate: {overall['skip_rate']:.1%} ({overall['skip_count']:,} skipped)")
        lines.append(f"Traded cycles: {overall['traded_count']:,}")
        lines.append("")
        lines.append(f"Win rate: {overall['win_rate']:.1%} ({overall['win_count']}/{overall['traded_count']} trades)")
        lines.append(f"Total PnL: ${overall['total_pnl']:,.2f}")
        lines.append(f"Avg PnL per trade: ${overall['avg_pnl_per_trade']:,.2f}")
        lines.append(f"Sharpe ratio: {overall['sharpe_ratio']:.2f}")
        lines.append(f"Max drawdown: ${overall['max_drawdown']:,.2f} ({overall['max_drawdown_pct']:.1f}%)")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append("PER-SETUP PERFORMANCE")
        lines.append("=" * 80)
        
        if not per_setup:
            lines.append("No setup data available (all trades marked as 'none')")
        else:
            for setup, stats in sorted(per_setup.items()):
                lines.append(f"\nSetup {setup}:")
                lines.append(f"  Trades: {stats['trade_count']:,}")
                lines.append(f"  Win rate: {stats['win_rate']:.1%} ({stats['win_count']}/{stats['trade_count']})")
                lines.append(f"  Total PnL: ${stats['total_pnl']:,.2f}")
                lines.append(f"  Avg PnL: ${stats['avg_pnl']:,.2f}")
                lines.append(f"  Avg win: ${stats['avg_win']:,.2f} | Avg loss: ${stats['avg_loss']:,.2f}")
                lines.append(f"  Expected value: {stats['expected_value']:+.4f}")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("CONFLUENCE ANALYSIS")
        lines.append("=" * 80)
        lines.append(f"Confluence gate activations: {confluence['confluence_gate_activations']:,}")
        lines.append(f"Disqualifier gate activations: {confluence['disqualifier_gate_activations']:,}")
        lines.append("")
        lines.append("Confluence score distribution:")
        for score, count in sorted(confluence["confluence_distribution"].items()):
            pct = count / len(self.df) * 100
            lines.append(f"  {score}/10: {count:,} cycles ({pct:.1f}%)")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("RECOMMENDATION")
        lines.append("=" * 80)
        
        # Generate recommendations based on results
        recommendations = []
        
        if overall["skip_rate"] > 0.9:
            recommendations.append("⚠️  SKIP rate >90% — consider lowering confluence threshold")
        
        if overall["win_rate"] < 0.52:
            recommendations.append("⚠️  Win rate <52% — below breakeven for binary markets with fees")
        
        if overall["sharpe_ratio"] < 1.0:
            recommendations.append("⚠️  Sharpe ratio <1.0 — risk-adjusted returns below target")
        
        for setup, stats in per_setup.items():
            if stats["expected_value"] < 0:
                recommendations.append(f"⚠️  Setup {setup} has negative EV — pause or retune")
        
        if not recommendations:
            recommendations.append("✅ All metrics within acceptable range — ready for paper trading")
        
        for rec in recommendations:
            lines.append(rec)
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_report(self, output_path: Optional[Path] = None):
        """Save report to text file."""
        if output_path is None:
            output_path = self.results_file.parent / f"{self.results_file.stem}_report.txt"
        
        report = self.generate_report()
        output_path.write_text(report)
        logger.info(f"Report saved to {output_path}")
        
        return output_path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze backtest results")
    parser.add_argument("--results", required=True, help="Path to backtest results JSON")
    parser.add_argument("--output", help="Output path for report (optional)")
    
    args = parser.parse_args()
    
    results_file = Path(args.results)
    if not results_file.exists():
        logger.error(f"Results file not found: {results_file}")
        return
    
    analyzer = BacktestAnalyzer(results_file)
    analyzer.load_results()
    
    # Print report to console
    report = analyzer.generate_report()
    print(report)
    
    # Save to file
    output_path = Path(args.output) if args.output else None
    saved_path = analyzer.save_report(output_path)
    print(f"\n📄 Report saved to: {saved_path}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    main()
