# BTC Agent System — Minimal

> Multi-agent LLM system untuk Polymarket BTC 5-minute binary prediction markets
> **5 agents, linear pipeline, same rigor, lower latency**

## Arsitektur

```
STEP 1 → Market & Sentiment Analyst (Vance)    — price + orderbook + funding/OI + fast-filter
STEP 2 → Research Agent (Halvorsen)             — internal bull/bear synthesis
STEP 3 → Trader Agent (Petrova)                 — EV check + entry timing
STEP 4 → Risk & Portfolio Manager (Castellan)   — 3-lens sizing + final call, 2% hard cap
```

Lihat `architecture.mermaid` untuk diagram lengkap.

## Agent List

| # | Agent | Persona | Role |
|---|-------|---------|------|
| 0 | Orchestrator | Hale | Pipeline coordinator, timeout & verify gate |
| 1 | Market & Sentiment | Vance | All-in-one market reader (price + sentiment + fast-filter) |
| 2 | Research | Halvorsen | Internal bull/bear debate, outputs ResearchPlan |
| 3 | Trader | Petrova | Execution + EV check at current odds |
| 4 | Risk & Portfolio | Castellan | 3-lens sizing (aggressive/conservative/neutral) + final decision |

## Why Minimal?

The original 13-agent system ran 6 waves with parallel analysts and multi-round debates. This version consolidates the same discipline into 4 linear steps because:

- **Latency is risk** — in a 5-minute window, every extra API call eats into execution time
- **Same rigor, less ceremony** — each agent internalizes the debate it used to outsource
- **Simpler debugging** — linear pipeline means every failure is obvious
- **Lower cost** — 4 LLM calls vs 12+ per cycle

## Setup

### 1. Install

```bash
git clone https://github.com/Akmalaka1122/btc-agent-system.git
cd btc-agent-system
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Isi `.env` dengan:
- **LLM provider** (Xpiki, UniModel, OpenAI, dll — OpenAI-compatible)
- **Telegram bot token** (dari @BotFather)
- **Polymarket credentials** (isi saat mau live trading)
- **Binance API** (untuk BTC price data)

### 3. Run

```bash
python main.py
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | Cek sistem running/paused |
| `/history` | 5 keputusan terakhir |
| `/run` | Trigger 1 cycle manual (admin) |
| `/pause` | Stop scheduler (admin) |
| `/resume` | Resume scheduler (admin) |

## Output

```
🟢 Cycle a1b2c3d4 — 14:32:15 UTC

Decision: UP
Confidence: 7/10
Position size: $15.00
Expected value: 0.0342
Risk/Reward: 1.85

Reasoning: Multi-domain convergence on bullish momentum...

Warnings: Thin liquidity at current price level

Total latency: 45.2s | This is system output, NOT financial advice.
```

## ⚠️ Disiplin

- **PAPER_TRADING=true** sampai terbukti profitable (ratusan trade)
- **Hard cap 2% risk** per trade (Portfolio Manager)
- **SKIP adalah keputusan valid** — sistem dirancang untuk tidak overtrade
- **Backtest dulu** sebelum pakai uang asli

## Tech Stack

- **Python 3.11+** — asyncio, pydantic, openai SDK
- **LLM** — Any OpenAI-compatible provider (Xpiki, UniModel, OpenAI, etc.)
- **Telegram** — python-telegram-bot v21+
- **Polymarket** — py-clob-client (official SDK)
- **Scheduler** — APScheduler (async)

## License

MIT
