# Pump consensus PAPER logger

**PAPER ONLY — no live trades, no keys signed, no custody.**

Watches 18 high-realized Solana memecoin wallets. When ≥5 or ≥7 of them buy the **same mint** inside a short window, logs a consensus signal and optionally opens a **simulated** 0.05 SOL position with an **8% round-trip cost** haircut on close.

## Feed status (degraded)

| Source | Role | Status from this box |
|---|---|---|
| Public Solana RPC (`api.mainnet-beta.solana.com`, `solana-rpc.publicnode.com`) | Poll `getSignaturesForAddress` + `getTransaction` | **Live** (rate-limited) |
| DexScreener | Mcap / price / pair age for filters & mark-to-market | **Live** (forced refresh each mark) |
| pump.fun frontend API | Curve % / native trades | **Blocked** (Cloudflare 403) |
| Helius / Birdeye / Solscan APIs | Faster indexed wallet feeds | **No key** — optional `HELIUS_RPC_URL` env stub only |
| Yellowstone gRPC / PumpPortal account WS | Sub-second account trades | **Not configured** (needs paid key) |

**Lag (honest):** v0.2 polls in **parallel** (~6 wallets) with **~10s RPC timeouts**, **~70s cycle deadline**, and **~30s** poll interval. Typical cycle is still **~15–45s**, not sub-second. Signals older than **`max_signal_lag_sec` (180s)** are logged as **stale/skip** — no fake open then instant time-exit. Leaders often hold 12–21s, so this logger measures consensus **as observed late**.

**Noise filter:** only counts txs where the watched wallet’s **token balance** for a non-WSOL mint changes (skips tip/referral mention spam). Dust `|delta| < 1` is logged with `"dust": true` and does **not** count toward consensus.

## Hardening (v0.2)

- **Price refresh:** every mark-to-market / exit re-fetches DexScreener (`force=True`); never reuses entry price as the mark.
- **Hold clock:** wall-clock open time (not consensus block time).
- **Stale skip:** if detection lag > 180s, signal is logged + skipped (no paper open).
- **Timeouts / parallel / cycle deadline:** hung RPC cannot block the loop for ~50 minutes.
- **Watchdog:** `./run.sh start` also starts a watchdog that restarts the logger if heartbeat is stale >180s; recovery lines go to `status.log`.

## Rules (config.json)

- Windows: 30s / **60s (primary)** / 120s (all logged; paper opens only on 60s)
- Thresholds: **≥5** and **≥7** of 18
- Prefer mint age ≤10 min (DexScreener `pairCreatedAt`); kill if mcap >+40% vs first watched buy
- Curve >55% kill: **unavailable** without pump.fun API (logged as null)
- Size: 0.05 SOL notional; **8% RT** subtracted on close
- TP +15% / SL −10% / time exit 240s / majority-sell (≥3 watched wallets sell in 5m)
- Max **2** concurrent paper positions

## Files

```
watchlist.json          # 18 addresses + labels
config.json             # knobs
src/logger.py           # poller + paper engine
data/state.json         # seen signatures, cycle
logs/status.log         # human-readable cycle log
logs/heartbeat.json     # liveness (watchdog reads this)
logs/events.jsonl       # every detected wallet buy/sell
logs/signals.jsonl      # consensus hits (≥5 / ≥7)
logs/paper_trades.jsonl # opens / skips / closes
logs/paper_trades.csv   # same, spreadsheet-friendly (history preserved)
logs/logger.out         # stdout/stderr from nohup
logs/logger.pid         # logger PID
logs/watchdog.out       # watchdog log
logs/watchdog.pid       # watchdog PID
```

## Run

```bash
cd /workspace/pump-consensus-paper
./run.sh          # start logger + stall watchdog
./run.sh status   # heartbeat + tail
./run.sh stop     # kill logger + watchdog
```

Or foreground: `python3 src/logger.py`

## Safety

- `paper_only: true` — never submits Solana transactions
- No private keys loaded
- Solo Pump Desk paper remains paused unless James says otherwise; this is a separate research logger
