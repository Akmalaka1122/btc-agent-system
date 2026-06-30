# BTC Polymarket 5-Minute Trading Playbook

> Dokumen ini adalah spesifikasi strategi konkret untuk dipakai oleh Market & Sentiment Analyst, Research Agent, dan Risk & Portfolio Manager. Tujuannya: ubah "analisis kualitatif" jadi kriteria yang bisa diverifikasi dan di-backtest.

---

## 0. Premis Dasar (jangan diabaikan)

1. **Market 5 menit hampir efisien.** Mayoritas window tidak punya edge nyata. Playbook ini ada untuk membantu sistem mengenali pengecualian, bukan untuk membuat setiap window terlihat seperti peluang.
2. **Vig/spread Polymarket harus dikalahkan dulu** sebelum bicara profit. Kalau implied probability dari odds sudah ≥ estimasi probabilitas kamu sendiri, trade itu -EV meskipun arahnya "benar".
3. **Setiap angka win-rate di bawah ini adalah hipotesis, bukan fakta historis.** Tidak ada satupun di sini yang sudah saya backtest — semua perlu divalidasi dengan data nyata sebelum dipercaya (lihat Bagian 9).
4. **Default sistem adalah SKIP.** Trade hanya terjadi kalau confluence score (Bagian 1) melewati threshold DAN tidak ada disqualifier (Bagian 6) yang aktif.

---

## 1. Confluence Scoring System

Daripada keputusan biner "bullish/bearish", setiap window dapat **skor 0-10** dari 3 kategori. Threshold trading: **skor ≥ 6 untuk LEAN, ≥ 8 untuk full-size.**

| Kategori | Bobot Maks | Apa yang dinilai |
|---|---|---|
| **A. Technical Confluence** | 4 poin | Berapa banyak indikator independen (momentum, volatilitas, microstructure) yang searah |
| **B. Positioning Confluence** | 3 poin | Funding rate, OI, liquidation data searah dengan arah technical |
| **C. Microstructure/Orderbook** | 3 poin | Orderbook imbalance, VWAP deviation, volume spike mengonfirmasi |

**Cara hitung A (Technical, maks 4):**
- +1 jika RSI(14) 1m & 5m searah (keduanya >55 atau keduanya <45, bukan netral)
- +1 jika MACD histogram baru saja cross dan momentum-nya menguat (bukan crossover lemah)
- +1 jika harga di luar Bollinger Band 1 sigma DAN arah breakout sama dengan momentum (bukan band-walk lemah)
- +1 jika EMA9/EMA21 alignment searah dengan sinyal di atas

**Cara hitung B (Positioning, maks 3):**
- +1 jika funding rate searah (positif = bias short squeeze ke atas valid, negatif = bias long squeeze ke bawah valid — lihat Setup D)
- +1 jika OI berubah signifikan (>2% dalam 15 menit) searah dengan arah
- +1 jika tidak ada liquidation cascade besar yang baru terjadi BERLAWANAN arah (liquidation cascade berlawanan = invalidasi, bukan poin tambahan)

**Cara hitung C (Microstructure, maks 3):**
- +1 jika orderbook imbalance bid/ask >60:40 searah arah
- +1 jika harga >0.1% dari VWAP searah arah (institusi sedang membayar premium ke arah itu)
- +1 jika volume 1 menit terakhir >1.5x rata-rata 20 menit (bukan volume mati)

Skor ini yang harus ditulis eksplisit oleh Market & Sentiment Analyst di setiap report, bukan cuma "confidence 7/10" yang subjektif.

---

## 2. Setup A — Momentum Continuation

**Tesis:** Breakout dengan volume dan positioning yang mengonfirmasi punya kecenderungan continuation lebih besar daripada breakout kering di market crypto likuid.

**Kriteria masuk:**
- Technical confluence ≥ 3/4 (momentum jelas, bukan choppy)
- Volume spike confirmed (>1.5x rata-rata)
- Tidak sedang mendekati level resistance/support major dalam 15 menit terakhir (lihat Bagian 6 disqualifier)
- Funding rate TIDAK ekstrem berlawanan arah (funding ekstrem searah breakout = red flag crowded trade, lihat Setup D)

**Invalidasi:** Harga balik ke dalam range sebelum candle 5m berikutnya close — keluar/jangan masuk.

**Sizing tier:** LEAN jika skor 6-7, FULL jika skor 8+.

---

## 3. Setup B — Mean Reversion Extreme

**Tesis:** Pada window 5 menit, pergerakan yang sangat cepat tanpa positioning/fundamental pendukung punya kecenderungan snap-back, terutama kalau microstructure menunjukkan exhaustion (volume turun saat harga masih bergerak).

**Kriteria masuk:**
- RSI(1m) <20 atau >80 (ekstrem, bukan sekadar oversold/overbought biasa)
- Harga menyentuh atau melewati Bollinger Band 2-sigma
- Volume MENURUN di candle terakhir dibanding candle sebelumnya saat harga masih bergerak ke arah ekstrem (tanda exhaustion, bukan konfirmasi)
- TIDAK ada news/event aktif yang menjelaskan pergerakan (lihat fast-filter flags dari Market Analyst — kalau ada news nyata, ini bukan mean reversion setup, ini repricing yang sah)

**Invalidasi:** Volume justru naik di candle berikutnya searah pergerakan awal — exhaustion gagal, jangan masuk/keluar.

**Sizing tier:** Setup ini secara struktural lebih berisiko (melawan momentum) — cap di LEAN kecuali confluence positioning juga mendukung reversal (funding ekstrem searah reversal).

---

## 4. Setup C — Liquidation Cascade Fade

**Tesis:** Liquidation cascade sering overshoot harga wajar dalam hitungan menit karena forced selling/buying, lalu sebagian terkoreksi balik begitu cascade selesai.

**Kriteria masuk:**
- Liquidation data menunjukkan cascade besar (>$5-10M dalam <5 menit, sesuaikan threshold dengan likuiditas BTC saat ini) ke satu arah
- Harga sudah bergerak >0.3-0.5% dalam waktu sangat singkat (<2 menit) — tanda forced flow, bukan organic move
- Orderbook mulai menunjukkan replenishment di sisi yang baru saja "disapu" (bid/ask wall muncul kembali)

**Invalidasi:** Cascade berlanjut tanpa tanda replenishment — ini bukan fade setup, ini trend day, jangan melawan.

**Sizing tier:** LEAN only — setup ini punya tail risk tinggi kalau cascade ternyata baru permulaan dari pergerakan struktural lebih besar (misal news nyata yang memicu cascade).

---

## 5. Setup D — Funding/Positioning Divergence (Crowded Trade Unwind)

**Tesis:** Funding rate ekstrem (banyak orang long atau short di perpetual) menciptakan kerapuhan — sedikit pemicu bisa memaksa unwind massal ke arah berlawanan dari posisi crowded.

**Kriteria masuk:**
- Funding rate di luar 1.5x standar deviasi historis (sesuaikan dengan rolling window data kamu)
- OI tinggi dan terus naik mendekati level funding ekstrem ini (tanda makin banyak orang masuk ke trade yang sama)
- Technical menunjukkan momentum mulai melemah ke arah crowded trade (early sign of stall)

**Arah trade:** BERLAWANAN dengan crowded positioning. Funding sangat positif (semua long) → bias DOWN. Funding sangat negatif (semua short) → bias UP.

**Invalidasi:** Funding ekstrem tapi momentum masih kuat searah crowd — belum waktunya, tunggu tanda stall dulu.

**Sizing tier:** Setup paling kuat secara teori (kontrarian dengan struktur jelas) tapi butuh sample backtest paling banyak sebelum dipercaya, karena timing-nya sulit — mulai dari LEAN meskipun skor tinggi, sampai terbukti dari data live.

---

## 6. Disqualifiers (Hard No-Trade Filters)

Apapun skor confluence-nya, **SKIP otomatis** kalau salah satu ini aktif:

- Scheduled macro event (CPI/FOMC/NFP) dalam ±10 menit dari window — volatilitas tidak bisa diprediksi dari technical
- Spread/liquidity orderbook melebar signifikan dari normal (tanda market maker menarik diri, biasanya sebelum berita)
- News HIGH impact aktif dari Market Analyst fast-filter flags — ini bukan lagi soal teknikal, ini repricing fundamental
- Cascade liquidation sedang berlangsung TANPA tanda replenishment (kecuali eksplisit masuk Setup C dengan kriteria lengkap terpenuhi)
- Implied probability dari Polymarket odds sudah ≥ estimasi probabilitas internal sistem (selalu cek ini di Trader Agent — ini final gatekeeper EV)

---

## 7. Position Sizing Framework

Sizing mengikuti confluence score, bukan "perasaan yakin":

| Confluence Score | Posisi (% dari sizing unit harian) | Catatan |
|---|---|---|
| 0-5 | 0% (SKIP) | Tidak ada edge yang cukup tervalidasi |
| 6-7 | 25-40% (LEAN) | Setup valid tapi belum confluence penuh |
| 8-10 | 60-100% (FULL, capped 2% account) | Semua kategori confluence searah |

Hard cap tetap **2% account balance per trade**, terlepas dari skor — ini sudah ada di soul Risk & Portfolio Manager dan tidak boleh dilonggarkan oleh skor tinggi sekalipun.

---

## 8. Risk Circuit Breakers

Selain sizing per-trade, sistem perlu pembatas harian/mingguan supaya satu sesi buruk tidak merusak modal:

- **Daily loss limit:** stop trading otomatis kalau drawdown harian mencapai 6% account (3 kali ukuran max per trade) — ini tanda hari ini bukan hari yang "punya edge", lanjut trading biasanya memperparah.
- **Cooldown setelah 3 loss beruntun:** jeda minimal 1 jam sebelum trade berikutnya, terlepas skor confluence-nya — mencegah revenge trading otomatis dari sistem.
- **Win-rate tracking rolling 50 trade per setup type:** kalau satu setup (misal Setup B) menunjukkan win rate jauh di bawah breakeven implied-odds-nya setelah 50 sample, setup itu di-pause otomatis sampai direview manual.

---

## 9. Validasi Sebelum Live (Wajib)

Playbook ini tidak boleh langsung dipakai live trading. Urutan validasi yang benar:

1. **Backtest tiap setup secara terpisah** pada data historis BTC 1m/5m minimal 3-6 bulan, hitung win rate dan EV riil per setup (bukan gabungan).
2. **Paper trade minimal 100-200 trade per setup** di kondisi live (bukan backtest) untuk menangkap realita slippage, latency, dan eksekusi nyata.
3. **Walk-forward test:** validasi parameter (threshold RSI, Bollinger sigma, dll) pada periode data yang BERBEDA dari periode kalibrasi awal — banyak strategi yang terlihat bagus di in-sample data hancur di out-of-sample.
4. **Cek korelasi antar setup:** kalau Setup A dan Setup D sering trigger bersamaan dengan arah sama, itu bukan dua sumber edge independen — sesuaikan sizing supaya tidak double-count confluence yang sama.
5. Baru pertimbangkan capital kecil nyata setelah semua langkah di atas selesai dan hasilnya konsisten secara statistik (bukan hanya "kelihatan untung" dalam sample kecil).

---

## 10. Pemetaan ke Pipeline Agent

| Bagian Playbook | Agent yang Bertanggung Jawab |
|---|---|
| Confluence Scoring (Bag. 1) | Market & Sentiment Analyst — hitung & laporkan skor A/B/C eksplisit |
| Setup A-D matching (Bag. 2-5) | Research Agent — identifikasi setup mana yang match, bangun bull/bear case berdasarkan setup itu |
| Disqualifiers (Bag. 6) | Market & Sentiment Analyst (fast-filter flags) + Trader Agent (final gate sebelum propose) |
| Position Sizing (Bag. 7) | Risk & Portfolio Manager — translate skor jadi ukuran posisi, tetap hard cap 2% |
| Circuit Breakers (Bag. 8) | Orchestrator — perlu state tracking lintas-cycle (daily PnL, loss streak), bukan keputusan single-cycle |

> Catatan implementasi: Circuit breaker (Bagian 8) butuh state yang persisten lintas cycle (database, bukan in-memory) karena harus tahu performa hari ini, bukan cuma cycle ini. Ini salah satu alasan kenapa database persisten (disebut di README sebelumnya sebagai "belum diimplementasi") sebenarnya wajib sebelum live, bukan opsional.
