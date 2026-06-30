# Soul Files — Polymarket BTC 5-Min Agent Pipeline

12 file `soul.md`, satu per agent, berisi persona expert + filosofi kerja + disiplin output untuk masing-masing role. Gunakan ini sebagai **system prompt utama** (gabungkan dengan system prompt teknis asli yang berisi schema/tools dari dokumen sumber).

| # | File | Agent | Karakter |
|---|------|-------|----------|
| 0 | 00-orchestrator.soul.md | Orchestrator | Hale — koordinator swarm, decompose/dispatch/verify |
| 1 | 01-btc-price-analyst.soul.md | BTC Price Analyst | Vance — ex-HFT, microstructure specialist |
| 2 | 02-sentiment-analyst.soul.md | Sentiment Analyst | Mira — sentiment data scientist, anti-noise |
| 3 | 03-news-analyst.soul.md | News Analyst | Dax — ex-Bloomberg, skeptis headline |
| 4 | 04-onchain-analyst.soul.md | On-Chain Analyst | Soo-jin — forensik on-chain, jujur soal lag |
| 5 | 05-bull-researcher.soul.md | Bull Researcher | Reyes — steelman bull case |
| 6 | 06-bear-researcher.soul.md | Bear Researcher | Okafor — risk-focused, bukan permabear |
| 7 | 07-research-manager.soul.md | Research Manager | Halvorsen — juri debat, disiplin SKIP |
| 8 | 08-trader-agent.soul.md | Trader Agent | Petrova — eksekusi + EV check |
| 9 | 09-aggressive-risk-analyst.soul.md | Aggressive Risk | Kade — agresif tapi berbasis bukti |
| 10 | 10-conservative-risk-analyst.soul.md | Conservative Risk | Whitfield — capital preservation |
| 11 | 11-neutral-risk-analyst.soul.md | Neutral Risk | Asghar — Kelly-style sizing |
| 12 | 12-portfolio-manager.soul.md | Portfolio Manager | Castellan — keputusan final, hard cap 2% |

## Orchestrator
File `00-orchestrator.soul.md` adalah agent ke-13 — dia tidak ikut menentukan arah trade sama sekali. Tugasnya murni koordinasi: Decompose → Dispatch (paralel utk 4 analyst, sequential utk debat) → Execute dgn timeout handling → Verify schema/kualitas output tiap agent → baru handoff ke Portfolio Manager. Ini yang membuat sistem auditable: setiap cycle menghasilkan log terpisah dari keputusan trading itu sendiri, jadi kalau ada trade yang salah, kamu bisa bedakan "analisisnya salah" vs "pipeline-nya gagal verifikasi."

## Cara pakai
1. Combine `soul.md` (persona/filosofi) + system prompt teknis dari dokumen sumber kamu (schema/tools) jadi satu system prompt per agent.
2. Setiap agent punya "Self-Check Before Submitting" di akhir — bisa kamu jadikan instruksi tambahan sebelum agent mengembalikan output final, untuk konsistensi kualitas.
3. Semua persona dirancang untuk saling melengkapi: analyst jujur soal keterbatasan timeframe-nya, researcher steelman argumen lawan, risk team punya 3 sudut pandang yang benar-benar independen (bukan sekadar role-play "agresif/konservatif").

## Catatan penting
Sistem ini untuk **prediction market 5 menit dengan vig/spread** — secara matematis sebagian besar window akan SKIP atau low-conviction kalau agent-nya jujur. Disiplin ini sengaja ditanam di setiap soul (terutama Conservative Risk, Research Manager, dan Portfolio Manager) supaya sistem tidak overtrade. Pastikan kamu backtest dan paper trade dulu sebelum live — sistem multi-agent ini tidak menjamin edge nyata, hanya membantu proses keputusan jadi lebih terstruktur.
