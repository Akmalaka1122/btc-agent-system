# Backtest Framework

Framework untuk validate Trading Playbook strategy dengan historical BTC data.

## Goals

1. **Validate setup performance** — Win rate per setup (A/B/C/D) secara terpisah
2. **Tune confluence threshold** — Cek apakah threshold=6 optimal atau perlu adjustment
3. **Measure EV accuracy** — Compare predicted EV vs actual PnL
4. **Test circuit breakers** — Verify daily loss limit & consecutive loss protection works

## Architecture

```
backtest/
├── data_loader.py       — Fetch historical BTC 1m/5m OHLCV from Binance
├── market_simulator.py  — Simulate market conditions per timeframe
├── backtest_engine.py   — Run orchestrator on historical windows
├── results_analyzer.py  — Compute metrics (win rate, EV, Sharpe, drawdown)
└── config.yaml          — Backtest parameters (date range, setups, threshold)
```

## Data Requirements

- **Timeframe:** 5-minute candles
- **Period:** 3-6 months recommended (Playbook §9)
- **Features needed:**
  - OHLCV (open, high, low, close, volume)
  - Funding rate snapshots (8h intervals)
  - Open interest deltas
  - Orderbook snapshots (top 20 levels) — optional, bisa skip untuk backtest awal

## Workflow

1. **Load historical data** → `data_loader.py` fetches from Binance REST API
2. **Iterate timeframes** → For each 5-min window:
   - Build `market_context` string (mimic orchestrator input)
   - Run Market Analyst → get confluence scores
   - Apply gates (confluence ≥6, disqualifiers)
   - If not SKIP: run full pipeline → get decision
3. **Simulate outcome** → For each decision:
   - UP → track if BTC price increased by end of window
   - DOWN → track if BTC price decreased
   - Compute PnL based on position size & implied odds
4. **Aggregate results** → Group by setup type, compute:
   - Win rate per setup
   - Average PnL per trade
   - Sharpe ratio
   - Max drawdown
   - Circuit breaker activations

## Limitations

- **No real orderbook liquidity** — assumes position can be filled at implied odds
- **No slippage modeling** — actual execution will be worse
- **LLM variability** — same market context might produce different outputs (temperature=0.3)
- **Data availability** — Binance API only has ~6 months historical data for some endpoints

## Usage

```bash
# 1. Download historical data
python backtest/data_loader.py --start 2026-04-01 --end 2026-06-30 --interval 5m

# 2. Run backtest
python backtest/backtest_engine.py --data data/btc_5m.parquet --setup A

# 3. Analyze results
python backtest/results_analyzer.py --results backtest_results.json
```

## Output

```
=== Backtest Results (2026-04-01 to 2026-06-30) ===
Total cycles: 17,856 (3 months × 288 cycles/day)
SKIP rate: 82.3% (14,694 skipped — confluence <6 or disqualifiers)
Traded cycles: 3,162

Per-Setup Performance:
  Setup A (Momentum Breakout):
    Trades: 1,234 | Win rate: 54.2% | Avg PnL: +$2.34 | EV: +0.087
  Setup B (Mean Reversion):
    Trades: 892 | Win rate: 51.8% | Avg PnL: +$1.12 | EV: +0.034
  Setup C (Liquidation Cascade):
    Trades: 567 | Win rate: 48.1% | Avg PnL: -$0.89 | EV: -0.021 ⚠️
  Setup D (Contrarian Positioning):
    Trades: 469 | Win rate: 56.7% | Avg PnL: +$3.45 | EV: +0.112

Overall:
  Total PnL: +$4,582.50
  Sharpe Ratio: 1.34
  Max Drawdown: -$1,245.00 (12.4%)
  Circuit breaker trips: 3 (daily loss limit)
  
Recommendation: Setup C underperforming — pause or retune.
```

## Next Steps

1. Implement `data_loader.py` — fetch Binance historical data
2. Implement `market_simulator.py` — convert raw data → market_context format
3. Implement `backtest_engine.py` — run orchestrator in simulation mode
4. Implement `results_analyzer.py` — compute metrics & generate report
5. Run on 3-6 months data, validate each setup independently
