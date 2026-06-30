# BTC Agent System

> Multi-agent LLM system untuk Polymarket BTC 5-minute binary prediction markets

13 specialized AI agents berkolaborasi dalam 6-wave pipeline untuk memprediksi arah BTC dalam 5 menit ke depan.

## Arsitektur

```
WAVE 1 [parallel]  → 4 Analysts (Price, Sentiment, News, On-Chain)
WAVE 2 [debate]    → Bull Researcher ⟷ Bear Researcher
WAVE 3 [single]    → Research Manager
WAVE 4 [single]    → Trader Agent
WAVE 5 [debate]    → Aggressive ⟷ Conservative ⟷ Neutral Risk
WAVE 6 [single]    → Portfolio Manager → FINAL: UP / DOWN / SKIP
```

Lihat `architecture.mermaid` untuk diagram lengkap.

## Agent List

| # | Agent | Persona | Role |
|---|-------|---------|------|
| 0 | Orchestrator | Hale | Pipeline coordinator, timeout & verify gate |
| 1 | BTC Price Analyst | Vance | Microstructure & technical analysis |
| 2 | Sentiment Analyst | Mira | Multi-source sentiment aggregation |
| 3 | News Analyst | Dax | Breaking news & event impact |
| 4 | On-Chain Analyst | Soo-jin | On-chain metrics (honest about lag) |
| 5 | Bull Researcher | Reyes | Steelman bull case |
| 6 | Bear Researcher | Okafor | Risk-focused bear case |
| 7 | Research Manager | Halvorsen | Debate judge, SKIP discipline |
| 8 | Trader Agent | Petrova | Execution + EV check |
| 9 | Aggressive Risk | Kade | Evidence-based aggression |
| 10 | Conservative Risk | Whitfield | Capital preservation |
| 11 | Neutral Risk | Asghar | Kelly-style sizing |
| 12 | Portfolio Manager | Castellan | Final decision, hard cap 2% |

## Setup

### 1. Install

```bash
git clone https://github.com/YOUR_USERNAME/btc-agent-system.git
cd btc-agent-system
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
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

Setiap cycle menghasilkan:

```
🟢 Cycle a1b2c3d4 — 14:32:15 UTC

Decision: UP
Confidence: 7/10
Position size: $15.00
Expected value: 0.0342
Risk/Reward: 1.85

Reasoning: Multi-domain convergence on bullish momentum...

Key factors: RSI oversold bounce, exchange outflow spike, positive funding normalization
Warnings: Thin liquidity at current price level

Total latency: 87.3s | This is system output, NOT financial advice.
```

## ⚠️ Disiplin

- **PAPER_TRADING=true** sampai terbukti profitable (ratusan trade)
- **Hard cap 2% risk** per trade (Portfolio Manager)
- **SKIP adalah keputusan valid** — sistem dirancang untuk tidak overtrade
- **Backtest dulu** sebelum pakai uang asli
- **Tidak menjamin edge** — ini alat bantu keputusan, bukan mesin uang

## Tech Stack

- **Python 3.11+** — asyncio, pydantic, openai SDK
- **LLM** — Any OpenAI-compatible provider (Xpiki, UniModel, OpenAI, etc.)
- **Telegram** — python-telegram-bot v21+
- **Polymarket** — py-clob-client (official SDK)
- **Scheduler** — APScheduler (async)

## License

MIT
