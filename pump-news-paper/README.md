# News-driven pump.fun new-pair — PAPER TEST (no wallet, no signing, no buys)

Started 2026-10-30 ~5:45 PM ET. Rules and pass bar below were fixed **before any results**; do not change mid-test
(any change = new test version, logged in status.log).

## Pipeline (every ~15 s cycle; 45 s hard deadline; 10 s per-request timeout)
1. **News** (every 90 s): Google News RSS (top, entertainment, tech, "viral when:1h", "elon musk when:1h"), Google Trends US RSS,
   Bluesky public trends, Know Your Meme newsfeed, TMZ, BBC, Hacker News front page. Reddit is 403-blocked from the box.
   Stories older than 6 h (by pubDate) ignored. Keywords per story: capitalised words ≥4 chars not in stoplist and not in the top-6000
   common English words, 2–3-word proper-noun runs concatenated (e.g. `patrickstewart`), quoted phrases, whole trend query.
   Keyword live 3 h from story time.
2. **New pairs**: pump.fun `frontend-api-v3 /coins` sorted by creation (latest 100 ≈ last 3–4 min). Coin age ≤30 min.
3. **Match**: normalised keyword == a coin name/symbol token, or == concatenated name/symbol. Longest keyword wins.
   Rejected (logged): coin created >15 min before the story (`pre_story`); keyword that already appeared in ≥5 coins in the
   60 min before the story (`baseline_generic`, e.g. trump/cat noise; needs ~1 h of coin history after start to be effective).
   One cluster per keyword; all matches logged to `logs/matches.jsonl`.
4. **Entry rules** (one trade per cluster per rule; max 3 concurrent per rule; 0.05 SOL notional):
   - **FIRST**: earliest-created matching coin, entered at detection. Skip if that coin is already >180 s old (`late`).
   - **LEADER**: 150 s after the cluster's first match, re-price every cluster coin; enter the highest market cap (SOL)
     if it is ≥35 SOL (~+25% above pump.fun launch mcap ≈28 SOL). Else skip `no_traction`. Skip if decision >90 s late.
5. **Rug filters** (skip + reason in `logs/events.jsonl`): banned/nsfw; creator launched ≥3 coins seen in 2 h; Rugcheck report
   (free): rugged, mint or freeze authority set, any non-bonding-curve holder >20%, dev holds >10%, >5 graph insiders,
   creator has ≥5 prior tokens. If Rugcheck is unreachable the trade proceeds and is tagged `rugcheck=unavailable`.
6. **Exits** (fixed): TP **+30% gross**, SL **−15% gross**, time exit **600 s**. Each check (~15 s) force-fetches
   pump.fun `coins-v2/{mint}` (cache-busted); price = market_cap in SOL (fixed supply). Entry price is a fresh fetch at entry,
   never the listing snapshot. Net = gross − **8% round-trip cost**. Gaps through SL are recorded at the actual fetched price.

## Pass bar (written before results)
Per rule: **≥50 closed paper trades** AND **positive total net PnL after 8% costs**. Also report max drawdown (SOL, cumulative),
win rate, avg win / avg loss, exit-reason mix, and compare FIRST vs LEADER. If neither passes → strategy not viable for live.

## Files
`config.json` (all thresholds), `run.sh start|stop|status|stats`, `src/newsbot.py`, `src/watchdog.sh` (restarts if dead or
heartbeat >180 s), `src/stats.py`; logs: `status.log` (heartbeat lines, opens/closes, GAPs), `heartbeat.json`, `stories.jsonl`,
`matches.jsonl`, `events.jsonl` (entries/skips/leader boards), `paper_trades.csv`, `errors.jsonl`.

## Known limits
- Lag: news feeds lag the real event (Google News minutes–hours; X is faster but not pollable from a daemon). Coin detection lag
  ≤ ~15–20 s. Paper fills ignore slippage beyond the 8% haircut; bonding-curve coins can gap far past the stop.
- Keyword matching is crude; many matches will be coincidental name overlaps, which is part of what the test measures.
- Box may sleep; gaps are logged as `GAP` in status.log.

## Dashboard
`./run.sh dashboard` → http://127.0.0.1:8050 (read-only, refreshes every 10 s). `./run.sh dashboard --sample` shows the bundled snapshot.
