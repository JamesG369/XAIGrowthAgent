# CLAUDE.md — pump.fun news-driven new-pair PAPER test

## ⚠️ Hard rules (read first)
- **PAPER ONLY.** This project never holds a wallet, never signs a transaction, never buys or sells. Every "trade" is a simulated
  0.05 SOL position priced from public pump.fun data. `config.json` has `"mode": "PAPER_ONLY"`.
- **No wallet keys, seed phrases, private keys, or RPC/API secrets** may be added to this repo, its config, or env files.
- **No live trading without explicit, written approval from the owner (James).** Do not add buy/sell/swap code, Jupiter/PumpPortal
  trade endpoints, or wallet libraries (solana-py, solders, web3) unless he explicitly asks for that specific change.
- Owner is US (Maine). **No Hyperliquid, no VPN/geo workarounds.** Don't launch memecoins. Never present results as guaranteed profit.
- Rules and the pass bar were fixed before results. Changing any threshold = a **new test version**: log it in `logs/status.log`
  and report results separately; never silently mix versions.

## What this is
A paper test of: "watch viral news, then buy the brand-new pump.fun coins named after the story." Every ~15 s the bot polls
news feeds, extracts keywords, scans the newest pump.fun coins, matches coin names/symbols to live keywords, and opens simulated
positions under two competing entry rules, with an 8% round-trip cost haircut on every trade. The question being answered:
**does either rule make money after realistic costs over ≥50 trades?**

Status when handed off (Oct 30, 2026 ~6 PM ET): running ~30 min on the original box; a handful of trades, all small losses or flat
— far from the 50-trade bar. Treat as unproven.

## Strategy rules (see `config.json` for every number)
| | FIRST | LEADER |
|---|---|---|
| Entry | Earliest-created coin matching a story keyword, entered at detection | `leader_window_sec`=150 s after the cluster's first match, re-price all coins in the cluster and enter the **highest market cap** coin if it is **≥ `leader_min_mcap_sol`=35 SOL** (launch mcap ≈28 SOL) |
| Skips | `late` if coin already > `first_max_coin_age_sec`=180 s old | `no_traction` if best < 35 SOL; skip if decision > `leader_max_decision_lag_sec`=90 s late |

Shared:
- One trade per cluster (keyword) per rule; **max 3 concurrent open per rule**; **0.05 SOL notional**.
- **Exits:** TP **+30% gross**, SL **−15% gross**, time exit **600 s**. Net = gross − **8% round-trip cost** (`rt_cost`).
- Entry price is a fresh `coins-v2` fetch at entry (never the listing snapshot). Each check force-refreshes (cache-busted).
- Coin age ≤ 30 min; coin created > 15 min before the story → `pre_story` reject; keyword already seen in ≥5 coins in the 60 min
  before the story → `baseline_generic` reject (needs ~1 h of coin history after start to work).
- **Rug filters** (skip + reason logged in `events.jsonl`): banned/nsfw; creator launched ≥3 coins seen in 2 h; Rugcheck
  (`api.rugcheck.xyz/v1/tokens/{mint}/report`, free): rugged, mint/freeze authority set, any non-curve holder >20%, dev >10%,
  >5 insiders, creator ≥5 prior tokens. If Rugcheck is unreachable the trade proceeds tagged `rugcheck=unavailable`.

## Test v2: FIRST2 + MOMO (added Oct 30, 2026 at the owner's request: "more trades and more success")
v2 runs as **two extra rules in the same bot**, beside the **unchanged** v1 FIRST/LEADER (v1 code paths and thresholds are
untouched, so the v1 test continues cleanly and both versions see the same news and coins). Rules are reported separately
(CSV `rule` column; dashboard tags each card v1/v2). Settings live in `config.json` → `"v2"`; `"enabled": false` turns v2 off.
Same 0.05 SOL notional, 8% `rt_cost`, rug filters and pass bar (≥50 closed AND net > 0, per rule).
| | FIRST2 | MOMO |
|---|---|---|
| Entry | Like FIRST, but if the earliest coin is skipped (rug filter, bad price) it tries the next-earliest coin in the cluster, up to `first2_max_attempts`=3, coin age ≤180 s | Every cycle from 45 s to 600 s after a coin is detected, re-price it; enter the first cluster coin with mcap ≥ `momo_min_mcap_sol`=33 SOL **and** rising over the last `momo_rising_marks`=2 checks. LEADER looks once at 150 s; MOMO keeps watching |
| Why | v1 FIRST gives up on a cluster after one filtered coin → lost trades | LEADER skipped most clusters as `no_traction` at its single 150 s check |
Shared v2 changes: **max 5 concurrent** per rule (v1: 3). **Exits:** SL −15% gross, **trailing stop** (once up ≥ +15% gross, exit
if price falls 12% from its peak), hard cap +100%, time exit 600 s. v1 capped winners at +30% while losses run past −15% after
costs; the trailing stop lets runners keep going. Exit reason `trail` is new.
**Unproven:** none of this has been validated on real data (only 4 v1 trades existed). Expect more trades; whether net PnL
improves is exactly what v2 measures. MOMO buys after a rise, so it can chase tops (see stop-loss risk).

## Data sources (all free, no keys)
- News (every 90 s): Google News RSS (top, entertainment, tech, "viral when:1h", "elon musk when:1h"), Google Trends US RSS,
  Bluesky public trends (`app.bsky.unspecced.getTrends`), Know Your Meme newsfeed, TMZ, BBC, Hacker News front page (Algolia).
- New coins: `https://frontend-api-v3.pump.fun/coins` sorted by creation (latest 100 ≈ last 3–4 min, `pump_pages`=2).
- Prices: `frontend-api-v3.pump.fun/coins-v2/{mint}` force-refreshed every check; SOL/USD from `/sol-price`.
- Keyword list: `data/words20k.txt` (common English words; top `common_word_rank_cutoff`=6000 are excluded as keywords).

## Market-cap normalization fix (important)
`coins-v2` `market_cap_quote` is in **quote-token units**, not always SOL. Some new coins are quoted in another pump token, and
those showed bogus mcaps (e.g. ~4.29M "SOL" for coins really worth ~24 SOL). Fix in `norm_mcap_sol()` (`src/newsbot.py`):
use `market_cap_quote` only when `quote_mint` is SOL/WSOL; else fall back to `market_cap`, cross-checked against
`usd_market_cap / SOL price` (trust USD/SOL if they disagree by >2×). Config guards:
- `require_sol_quote: true` — skip coins not priced in SOL (they had < $1 liquidity; not realistically buyable).
- `max_plausible_mcap_sol: 5000` — reject entries with implausible mcap.
- `max_mark_jump_x: 20` — ignore a price mark that jumps >20× from the last one (bad data).
Affected historical trades are kept in the CSV with `excluded`/`void_reason` set and are not counted.

## Known issues / limits
- Keyword matching is crude: generic words ("viral", "trump", "gamble") cause coincidental matches. Tightening this is a
  candidate for a **v2** test — don't change it mid-test without the owner's OK.
- Stops can fill well past −15% because prices are checked every ~15 s and bonding-curve coins gap; fills are recorded at the
  actual fetched price. Slippage beyond the 8% haircut is not modeled.
- Reddit returns 403 from the original box (not used). DexScreener lags/doesn't index brand-new coins (not used for this bot).
- News feeds lag real events (minutes to hours); X is faster but not pollable without paid API.
- If the machine sleeps, gaps are logged as `GAP` in `status.log`.
- `src/newsbot.py` uses `signal.SIGALRM` for the 45 s cycle deadline → **Unix only (Linux/macOS)**; on Windows use WSL.

## Pass bar (fixed before results)
Per rule (v1 FIRST/LEADER and v2 FIRST2/MOMO each): **≥50 closed paper trades AND positive total net PnL after the 8% costs.** Also report max drawdown (cumulative SOL),
win rate, avg win/avg loss, exit-reason mix, FIRST vs LEADER. If neither passes → not viable for live.

## How to run
Requires **Python ≥ 3.9** (tested 3.13.5), bash, Linux/macOS. No third-party packages.
```bash
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt                       # no-op today (stdlib only)
chmod +x run.sh src/watchdog.sh
./run.sh start    # starts src/newsbot.py + src/watchdog.sh in background (nohup); creates logs/ and data/
./run.sh status   # pids, heartbeat age, status.log tail
./run.sh stats    # per-rule summary from logs/paper_trades.csv
./run.sh stop     # touches logs/stopped (watchdog exits), kills bot + watchdog
```
Watchdog: checks every 30 s; restarts the bot if its PID is dead or `logs/heartbeat.json` is older than
`watchdog_stall_sec`=180 s. `logs/stopped` tells it to exit. Starting fresh creates new `logs/` and `data/state.json`.
To continue from the box's state instead: `mkdir -p logs && cp sample_logs/*.jsonl sample_logs/*.csv sample_logs/status.log logs/ && cp sample_logs/state.json data/`
(note: positions open in that snapshot will be marked/exited on the first cycle with whatever the price is then).

### Tracker data (for a dashboard)
`tracker_data.py` reads local logs only (no network) and emits a `DATA` JSON object (status, per-rule totals, PnL series, open
positions, recent closes, matches, skip reasons, voided trades, legacy consensus summary).
```bash
python3 tracker_data.py                                   # JSON from ./logs and ./data/state.json
python3 tracker_data.py --logs sample_logs --state sample_logs/state.json   # run against the bundled sample
python3 tracker_data.py --block                           # '// DATA-START ... // DATA-END' JS block (+ tracker_block_new.txt)
```
Env overrides: `PUMP_NEWS_DIR`, `PUMP_NEWS_LOGS`, `PUMP_NEWS_STATE`, `PUMP_CONS_DIR` (defaults to `legacy/pump-consensus-paper`).
Times are shown in America/New_York. Uses `%-d` strftime (Linux/macOS only).

## Paths: what changed vs the original box
On the original box this lived at `/workspace/pump-news-paper/` (legacy logger at `/workspace/pump-consensus-paper/`).
In this package everything is **relative to the script directory**: `run.sh`/`watchdog.sh` use `ROOT=$(dirname $0)`,
`newsbot.py`/`stats.py` use `__file__`, and `tracker_data.py` uses its own dir (+ the env/flags above). Also made portable here:
heartbeat age via Python instead of GNU `stat -c`, ISO dates via `date '+%Y-%m-%dT%H:%M:%S%z'` instead of `date -Iseconds`,
and `pkill` patterns scoped to `$ROOT`. Run it from any directory.

## File layout
```
CLAUDE.md            this file
README.md            original test spec (rules + pass bar, written before results)
config.json          every threshold
requirements.txt     stdlib only
run.sh               start|stop|status|stats|dashboard
dashboard.py         local read-only dashboard server (127.0.0.1:8050)
dashboard.html       dashboard page (polls /data every 10 s)
tracker_data.py      logs -> DATA JSON for a dashboard/page
src/newsbot.py       the bot (news poll, keyword extraction, coin scan, matching, rules, filters, paper exits)
src/stats.py         per-rule summary
src/watchdog.sh      restart-on-death/stall
data/words20k.txt    common-word list for keyword filtering
sample_logs/         snapshot from the box (Oct 30 ~6 PM ET): paper_trades.csv, events.jsonl, stories.jsonl,
                     matches.jsonl, status.log, state.json
legacy/pump-consensus-paper/   older wallet-consensus paper logger (PAUSED Oct 29; code+config+README only, no logs).
                     Result: 9 closed trades, ≈ −0.048 SOL (approximate; early price bug). Verdict: unprofitable (lag + clustered wallets).
                     Its run.sh still uses GNU `stat -c`/`date -I` (Linux); README mentions /workspace paths — adjust if you revive it.
```
Runtime files (`logs/`, `data/state.json`, `*.pid`, `heartbeat.json`) are created on start and git-ignored.

## Local live dashboard (10-second refresh)
`dashboard.py` (stdlib only, no Flask) serves `dashboard.html` plus `/data` (the `tracker_data.py` JSON, cached 3 s) on
**127.0.0.1 only**. It is read-only: no endpoint can start/stop the bot or place trades.
```bash
./run.sh dashboard            # live logs  -> http://127.0.0.1:8050
./run.sh dashboard --sample   # bundled sample_logs snapshot
python3 dashboard.py --port 8060 --logs DIR --state FILE
```
Page layout (top to bottom): status pill (Live / Stalled / Stopped from heartbeat + pids), KPI row (total net PnL, opened, closed,
open now, each split by rule), FIRST vs LEADER cards (stats, pass-bar progress + checklist, exit-reason mix), open positions
(with an SL←0→TP range marker), cumulative PnL step chart (inline SVG, hover tooltip), closed trades, recent matches, skip reasons,
bot health (heartbeat age, cycles, per-source status, GAP/restart lines), voided trades, legacy summary. Auto-refreshes every
10 s (pause/refresh buttons; refreshes when the tab regains focus), light/dark toggle, works at phone width.
