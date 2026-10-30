#!/usr/bin/env python3
"""News-driven pump.fun new-pair PAPER test. PAPER ONLY: no wallet, no signing, no buys."""
import json, os, re, time, csv, html, hashlib, traceback, signal
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, wait
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
LOG = os.path.join(ROOT, "logs"); DATA = os.path.join(ROOT, "data")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
PUMP = "https://frontend-api-v3.pump.fun"
TRADES_CSV = os.path.join(LOG, "paper_trades.csv")
CSV_COLS = ["rule","cluster","keyword","mint","symbol","name","story","entry_ts","entry_iso","coin_age_at_entry_s",
            "entry_mcap_sol","exit_ts","exit_iso","exit_mcap_sol","hold_s","reason","gross_ret","net_ret","pnl_sol","marks","excluded","void_reason"]
SOL_QUOTES = {"11111111111111111111111111111111", "So11111111111111111111111111111111111111112"}
V2 = CFG.get("v2", {}) if CFG.get("v2", {}).get("enabled") else {}
V2_RULES = ("FIRST2", "MOMO") if V2 else ()
RULES = ("FIRST", "LEADER") + V2_RULES
class BadPrice(ValueError): pass
_solpx = {"t": 0, "v": None}
def sol_usd():
    if now() - _solpx["t"] > 120:
        try:
            d = http(f"{PUMP}/sol-price"); v = float(d.get("solPrice") or 0)
            if v > 0: _solpx.update(t=now(), v=v)
        except Exception: pass
    return _solpx["v"]
def norm_mcap_sol(d):
    """pump.fun coins-v2: market_cap_quote is in QUOTE-mint units. Coins quoted in another token (quote_mint != SOL)
    report e.g. 4.29M there. market_cap is SOL-denominated; cross-check vs usd_market_cap / SOL price."""
    qm = d.get("quote_mint"); usd = d.get("usd_market_cap") or d.get("market_cap_usd")
    if qm in SOL_QUOTES or qm is None: mc = d.get("market_cap_quote")
    else: mc = None
    if mc is None: mc = d.get("market_cap")
    px = sol_usd()
    if mc is None and usd and px: mc = float(usd) / px
    try: mc = float(mc) if mc is not None else None
    except Exception: mc = None
    if mc is not None and usd and px:
        alt = float(usd) / px
        if alt > 0 and not (0.5 <= mc / alt <= 2.0): mc = alt   # SOL figure disagrees with USD figure -> trust USD/SOL
    return mc

def now(): return time.time()
def iso(t=None): return datetime.fromtimestamp(t or now()).astimezone().isoformat(timespec="seconds")
def status(msg):
    with open(os.path.join(LOG, "status.log"), "a") as f: f.write(f"{iso()} {msg}\n")
def jl(name, obj):
    with open(os.path.join(LOG, name), "a") as f: f.write(json.dumps(obj, default=str) + "\n")

def http(url, timeout=None, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout or CFG["http_timeout_sec"]) as r:
        b = r.read()
    return json.loads(b) if as_json else b.decode("utf-8", "replace")

STOP = set("""a an the and or but if then than of to in on at by for with from into onto over under about after before
again against all any are as be been being both can could did do does doing down during each few further had has have
having he her here hers him his how i is it its itself just me more most my no nor not now off once only other our out
own same she should so some such that their them there these they this those through too until up very was we were what
when where which while who whom why will would you your yours new news says said say live update updates video watch
watches photos photo report reports breaking today tonight week year years day days time first last next back top best
amid after over just make makes made get gets got set sets one two three four five six ten big man woman men women people
world us usa u.s american america national state states city county police court judge house senate president
government official officials former star stars fans fan show shows season game games team win wins won loses lost play
plays player players coach vs prediction odds score scores free agency trade trades deal deals home away says how why what
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october
november december 2024 2025 2026 2027 reuters associated press nbc cbs abc cnn fox times post journal guardian bbc npr
yahoo google apple news's opinion analysis exclusive inside latest dies dead death killed kill shot shooting crash fire
coin coins token pump meme memes moon inu sol solana crypto bitcoin official ceo company market markets stock stocks price
prices billion million amid could would might new york los angeles there their about more than have from will been were
this that with what into your also says said know need want look looks like right left real full help start ends end
""".split())
try:
    COMMON = set(w.strip() for w in open(os.path.join(DATA, "words20k.txt")).read().split()[:CFG.get("common_word_rank_cutoff", 6000)])
except Exception:
    COMMON = set()
CAPWORD = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")

def norm(s): return re.sub(r"[^a-z0-9]", "", s.lower())

def extract_keywords(title, is_trend=False):
    title = html.unescape(title)
    words = CAPWORD.findall(title)
    kws = set(); run = []
    def flush():
        if 2 <= len(run) <= 3:
            k = norm("".join(run))
            if 6 <= len(k) <= 20: kws.add(k)
        run.clear()
    for i, w in enumerate(words):
        w2 = re.sub(r"['’]s$", "", w)
        n = norm(w2)
        cap = w2[:1].isupper() or is_trend
        if cap and n and n not in STOP and len(n) >= CFG["keyword_min_len"] and not n.isdigit():
            if n not in COMMON: kws.add(n)
            run.append(w2)
        elif cap and n and n not in STOP and len(n) >= 2 and not n.isdigit():
            run.append(w2)
        else:
            flush()
    flush()
    for q in re.findall(r"['‘“\"]([^'’”\"]{3,30})['’”\"]", title):
        k = norm(q)
        if 4 <= len(k) <= 20 and k not in COMMON and k not in STOP: kws.add(k)
    if is_trend:
        k = norm(title)
        if 4 <= len(k) <= 20: kws.add(k)
    return kws

def parse_rss(text):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", text, re.S):
        it = m.group(1)
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        traffic = re.search(r"<ht:approx_traffic>(.*?)<", it)
        if not t: continue
        ts = None
        if d:
            try: ts = parsedate_to_datetime(d.group(1).strip()).timestamp()
            except Exception: ts = None
        items.append({"title": html.unescape(t.group(1).strip()), "ts": ts, "traffic": traffic.group(1) if traffic else None})
    return items

def fetch_source(name, url):
    if name == "bsky_trends":
        d = http(url)
        return [{"title": t.get("displayName") or t.get("topic"), "ts": (t.get("startedAt") and datetime.fromisoformat(t["startedAt"].replace("Z","+00:00")).timestamp()) or None,
                 "traffic": t.get("postCount")} for t in d.get("trends", [])]
    if name == "hn_front":
        d = http(url)
        return [{"title": h.get("title") or "", "ts": h.get("created_at_i"), "traffic": h.get("points")} for h in d.get("hits", [])]
    items = parse_rss(http(url, as_json=False))
    if name.startswith("gnews"):
        for it in items: it["title"] = re.sub(r"\s+-\s+[^-]+$", "", it["title"])
    return items

class Bot:
    def __init__(self):
        self.state_path = os.path.join(DATA, "state.json")
        s = json.load(open(self.state_path)) if os.path.exists(self.state_path) else {}
        self.keywords = s.get("keywords", {})     # kw -> {story_id, story, source, story_ts, first_seen}
        self.stories = s.get("stories", {})       # story_id -> {...}
        self.clusters = s.get("clusters", {})     # kw -> {first_match_ts, coins:{mint:{...}}, first_done, leader_done}
        self.positions = s.get("positions", [])   # open paper positions
        self.coin_seen = s.get("coin_seen", {})   # mint -> {created, name, symbol, creator}
        self.traded = s.get("traded", {})
        for r in RULES: self.traded.setdefault(r, [])
        self.last_news = 0; self.source_ok = {}; self.cycle = s.get("cycle", 0)
        self.last_cycle_end = s.get("last_cycle_end")
        self.pool = ThreadPoolExecutor(max_workers=12)
        if not os.path.exists(TRADES_CSV):
            with open(TRADES_CSV, "w", newline="") as f: csv.writer(f).writerow(CSV_COLS)

    def save(self):
        s = dict(keywords=self.keywords, stories=self.stories, clusters=self.clusters, positions=self.positions,
                 coin_seen=self.coin_seen, traded=self.traded, cycle=self.cycle, last_cycle_end=now())
        tmp = self.state_path + ".tmp"; json.dump(s, open(tmp, "w")); os.replace(tmp, self.state_path)

    # ---------- news ----------
    def poll_news(self):
        futs = {self.pool.submit(fetch_source, n, u): n for n, u in CFG["news_sources"].items()}
        done, _ = wait(futs, timeout=CFG["http_timeout_sec"] + 5)
        new_st = 0; t0 = now()
        for f, n in futs.items():
            if f not in done or f.exception():
                self.source_ok[n] = f"ERR {f.exception() if f in done else 'timeout'}"[:80]; continue
            items = f.result(); self.source_ok[n] = f"ok {len(items)}"
            for it in items:
                title = (it.get("title") or "").strip()
                if not title: continue
                sid = hashlib.sha1((n + "|" + title).encode()).hexdigest()[:12]
                if sid in self.stories: continue
                sts = it.get("ts") or t0
                if t0 - sts > CFG["story_max_age_hours"] * 3600:
                    self.stories[sid] = {"skip": "old", "seen": t0}; continue
                kws = sorted(extract_keywords(title, is_trend=n in ("gtrends_us", "bsky_trends")))
                rec = {"id": sid, "source": n, "title": title, "story_ts": sts, "first_seen": t0,
                       "lag_s": round(t0 - sts), "traffic": it.get("traffic"), "keywords": kws}
                self.stories[sid] = {"seen": t0, "title": title, "source": n}
                jl("stories.jsonl", {**rec, "story_iso": iso(sts), "seen_iso": iso(t0)})
                new_st += 1
                for k in kws:
                    if k in self.keywords:
                        kk = self.keywords[k]; kk["sources"] = sorted(set(kk.get("sources", [])) | {n}); kk["story_ts"] = min(kk["story_ts"], sts)
                    else:
                        self.keywords[k] = {"story_id": sid, "story": title, "source": n, "sources": [n], "story_ts": sts, "first_seen": t0}
        # expire
        ttl = CFG["keyword_ttl_hours"] * 3600
        self.keywords = {k: v for k, v in self.keywords.items() if t0 - v["story_ts"] < ttl}
        self.stories = {k: v for k, v in self.stories.items() if t0 - v["seen"] < 24 * 3600}
        self.last_news = t0
        return new_st

    # ---------- coins ----------
    def poll_coins(self):
        urls = [f"{PUMP}/coins?offset={i*50}&limit=50&sort=created_timestamp&order=DESC&includeNsfw=false&_={int(now())}" for i in range(CFG["pump_pages"])]
        futs = [self.pool.submit(http, u) for u in urls]
        done, _ = wait(futs, timeout=CFG["http_timeout_sec"] + 3)
        coins = []; errs = 0
        for f in futs:
            if f in done and not f.exception(): coins += f.result()
            else: errs += 1
        return coins, errs

    def coin_tokens(self, c):
        name = c.get("name") or ""; sym = c.get("symbol") or ""
        toks = {norm(w) for w in re.findall(r"[A-Za-z0-9]+", name + " " + sym)}
        toks |= {norm(name), norm(sym)}
        return {t for t in toks if t}

    def is_generic(self, kw, story_ts):
        lb = CFG["baseline_generic_lookback_min"] * 60
        cnt = 0
        for m, c in self.coin_seen.items():
            if story_ts - lb <= c["created"] < story_ts - 60 and kw in c.get("toks", []): cnt += 1
        return cnt >= CFG["baseline_generic_max_coins"]

    def process_coins(self, coins):
        t = now(); newc = 0; matches = []
        for c in coins:
            m = c.get("mint")
            if not m or m in self.coin_seen: continue
            created = (c.get("created_timestamp") or 0) / 1000
            toks = sorted(self.coin_tokens(c))
            self.coin_seen[m] = {"created": created, "name": c.get("name"), "symbol": c.get("symbol"), "creator": c.get("creator"), "toks": toks, "first_seen": t}
            newc += 1
            age = t - created
            if age > CFG["coin_max_age_min"] * 60: continue
            hits = [k for k in toks if k in self.keywords]
            if not hits: continue
            hits.sort(key=len, reverse=True); kw = hits[0]; K = self.keywords[kw]
            rec = {"ts": t, "iso": iso(t), "kw": kw, "mint": m, "symbol": c.get("symbol"), "name": c.get("name"),
                   "coin_age_s": round(age), "mcap_sol": c.get("market_cap_quote") or c.get("market_cap"),
                   "usd_mcap": c.get("usd_market_cap"), "creator": c.get("creator"), "story": K["story"], "source": K["source"],
                   "story_iso": iso(K["story_ts"])}
            if created < K["story_ts"] - CFG["coin_created_slack_before_story_min"] * 60:
                rec["status"] = "pre_story"; jl("matches.jsonl", rec); continue
            if self.is_generic(kw, K["story_ts"]):
                rec["status"] = "baseline_generic"; jl("matches.jsonl", rec); continue
            rec["status"] = "match"; jl("matches.jsonl", rec); matches.append(rec)
            cl = self.clusters.setdefault(kw, {"first_match_ts": t, "story": K["story"], "coins": {}, "first_done": False, "leader_done": False})
            cl["coins"][m] = {"symbol": c.get("symbol"), "name": c.get("name"), "created": created, "creator": c.get("creator"), "detected": t}
        # trim coin memory 2h
        self.coin_seen = {k: v for k, v in self.coin_seen.items() if t - v["created"] < 2 * 3600 or t - v["first_seen"] < 600}
        return newc, matches

    # ---------- pricing / filters ----------
    def fresh(self, mint):
        d = http(f"{PUMP}/coins-v2/{mint}?_={int(now()*1000)}")
        mc = norm_mcap_sol(d)
        if mc is None or mc <= 0 or mc > CFG.get("max_plausible_mcap_sol", 5000):
            raise BadPrice(f"bad_price_data mcap={mc} quote={d.get('quote_mint')}")
        return {"mcap_sol": mc, "quote_mint": d.get("quote_mint"), "sol_quoted": d.get("quote_mint") in SOL_QUOTES, "usd_mcap": d.get("usd_market_cap"), "vol1h": d.get("volume_1h_usd") or 0,
                "complete": d.get("complete"), "banned": d.get("is_banned"), "nsfw": d.get("nsfw"), "creator": d.get("creator"),
                "bonding_curve": d.get("bonding_curve"), "liq": d.get("canonical_pool_liquidity_usd")}

    def filters(self, mint, info):
        if info.get("banned"): return "banned"
        if info.get("nsfw"): return "nsfw"
        cr = info.get("creator")
        launches = sum(1 for c in self.coin_seen.values() if c.get("creator") == cr)
        if cr and launches >= CFG["filter_max_creator_launches_seen_2h"]: return f"serial_launcher_{launches}_in_2h"
        try:
            r = http(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=8)
        except Exception as e:
            info["rugcheck"] = f"unavailable:{type(e).__name__}"; return None
        bc = info.get("bonding_curve"); abc = None
        top = 0.0
        for h in r.get("topHolders") or []:
            if h.get("owner") == bc or h.get("address") == bc: continue
            if (h.get("pct") or 0) > 90: continue  # bonding-curve vault
            top = max(top, h.get("pct") or 0)
        supply = 1e15
        dev = 100.0 * (r.get("creatorBalance") or 0) / supply
        ins = r.get("graphInsidersDetected") or 0
        ctoks = len(r.get("creatorTokens") or [])
        info["rugcheck"] = {"top_holder_pct": round(top, 2), "dev_pct": round(dev, 2), "insiders": ins, "creator_tokens": ctoks,
                            "mint_auth": r.get("mintAuthority"), "freeze_auth": r.get("freezeAuthority"), "rugged": r.get("rugged")}
        if r.get("rugged"): return "rugcheck_rugged"
        if r.get("mintAuthority"): return "mint_authority"
        if r.get("freezeAuthority"): return "freeze_authority"
        if top > CFG["filter_max_holder_pct"]: return f"top_holder_{top:.0f}pct"
        if dev > CFG["filter_max_dev_pct"]: return f"dev_holds_{dev:.0f}pct"
        if ins > CFG["filter_max_insiders"]: return f"insiders_{ins}"
        if ctoks >= CFG["filter_max_creator_tokens"]: return f"creator_tokens_{ctoks}"
        return None

    def open_count(self, rule): return sum(1 for p in self.positions if p["rule"] == rule)

    def try_enter(self, rule, kw, mint, coin, reason_ctx):
        t = now()
        base = {"ts": t, "iso": iso(t), "rule": rule, "kw": kw, "mint": mint, "symbol": coin.get("symbol"), "ctx": reason_ctx}
        if mint in self.traded[rule]: jl("events.jsonl", {**base, "event": "skip", "why": "already_traded"}); return False
        if self.open_count(rule) >= (V2["max_concurrent_per_rule"] if rule in V2_RULES else CFG["max_concurrent_per_rule"]):
            jl("events.jsonl", {**base, "event": "skip", "why": "max_concurrent"}); return False
        try: info = self.fresh(mint)
        except BadPrice as e:
            jl("events.jsonl", {**base, "event": "skip", "why": "bad_price_data", "detail": str(e)}); return False
        except Exception as e:
            jl("events.jsonl", {**base, "event": "skip", "why": f"price_fail:{e}"}); return False
        if CFG.get("require_sol_quote", True) and not info.get("sol_quoted"):
            jl("events.jsonl", {**base, "event": "skip", "why": "non_sol_quote", "info": info}); return False
        why = self.filters(mint, info)
        if why:
            jl("events.jsonl", {**base, "event": "skip", "why": why, "info": info}); return False
        t2 = now()
        p = {"rule": rule, "cluster": kw, "keyword": kw, "mint": mint, "symbol": coin.get("symbol"), "name": coin.get("name"),
             "story": self.clusters[kw]["story"], "entry_ts": t2, "coin_age_at_entry_s": round(t2 - coin["created"]),
             "entry_mcap_sol": info["mcap_sol"], "marks": 0, "last_mcap": info["mcap_sol"], "rugcheck": info.get("rugcheck")}
        if rule in V2_RULES: p["peak_mcap"] = info["mcap_sol"]
        self.positions.append(p); self.traded[rule].append(mint)
        jl("events.jsonl", {**base, "event": "OPEN", "entry_mcap_sol": info["mcap_sol"], "usd_mcap": info["usd_mcap"], "info": info})
        status(f"PAPER OPEN {rule} {coin.get('symbol')} kw={kw} mcap={info['mcap_sol']:.1f} SOL (${(info['usd_mcap'] or 0):,.0f}) age={p['coin_age_at_entry_s']}s")
        return True

    def handle_entries(self):
        t = now()
        for kw, cl in list(self.clusters.items()):
            coins = cl["coins"]
            if not cl["first_done"]:
                # FIRST: earliest-created match that is still fresh enough
                for m, c in sorted(coins.items(), key=lambda x: x[1]["created"]):
                    if t - c["created"] > CFG["first_max_coin_age_sec"]:
                        jl("events.jsonl", {"ts": t, "iso": iso(t), "rule": "FIRST", "kw": kw, "mint": m, "symbol": c["symbol"], "event": "skip", "why": f"late_coin_age_{round(t-c['created'])}s"})
                        cl["first_done"] = True; break
                    ok = self.try_enter("FIRST", kw, m, c, "first_match")
                    cl["first_done"] = True; break
            if not cl["leader_done"] and t - cl["first_match_ts"] >= CFG["leader_window_sec"]:
                cl["leader_done"] = True
                lag = t - cl["first_match_ts"] - CFG["leader_window_sec"]
                if lag > CFG["leader_max_decision_lag_sec"]:
                    jl("events.jsonl", {"ts": t, "iso": iso(t), "rule": "LEADER", "kw": kw, "event": "skip", "why": f"late_decision_{round(lag)}s"}); continue
                cands = {m: c for m, c in coins.items() if t - c["created"] <= CFG["coin_max_age_min"] * 60}
                futs = {m: self.pool.submit(self.fresh, m) for m in cands}
                wait(list(futs.values()), timeout=CFG["http_timeout_sec"] + 2)
                board = []
                for m, f in futs.items():
                    if f.done() and not f.exception():
                        i = f.result()
                        if not i.get("banned") and i.get("sol_quoted", True): board.append((i["mcap_sol"], i["vol1h"], m))
                board.sort(reverse=True)
                jl("events.jsonl", {"ts": t, "iso": iso(t), "rule": "LEADER", "kw": kw, "event": "leader_board",
                                    "n": len(coins), "board": [{"mint": m, "symbol": coins[m]["symbol"], "mcap_sol": round(a, 2), "vol1h": v} for a, v, m in board[:10]]})
                if not board: continue
                a, v, m = board[0]
                if a < CFG["leader_min_mcap_sol"]:
                    jl("events.jsonl", {"ts": t, "iso": iso(t), "rule": "LEADER", "kw": kw, "mint": m, "event": "skip", "why": f"no_traction_{a:.1f}sol"}); continue
                self.try_enter("LEADER", kw, m, coins[m], f"leader_of_{len(coins)}")
        if V2: self.handle_v2_entries(t)
        # drop old clusters
        self.clusters = {k: v for k, v in self.clusters.items() if t - v["first_match_ts"] < 3 * 3600}

    # ---------- v2 rules (separate test version; FIRST/LEADER above are unchanged) ----------
    def handle_v2_entries(self, t):
        # FIRST2: like FIRST, but if the earliest coin is filtered out, try the next-earliest fresh coin in the cluster.
        for kw, cl in self.clusters.items():
            if cl.get("first2_done"): continue
            tried = cl.setdefault("first2_tried", [])
            for m, c in sorted(cl["coins"].items(), key=lambda x: x[1]["created"]):
                if m in tried: continue
                if t - c["created"] > V2["first2_max_coin_age_sec"]: continue
                tried.append(m)
                if self.try_enter("FIRST2", kw, m, c, f"first2_attempt_{len(tried)}"): cl["first2_done"] = True
                elif len(tried) >= V2["first2_max_attempts"]: cl["first2_done"] = True
                break  # at most one attempt per cluster per cycle
        # MOMO: re-price cluster coins every cycle during the watch window; enter the first coin that is above the
        # mcap floor AND still rising (last N marks up). LEADER makes one decision at 150 s; this keeps watching.
        cands = []
        for kw, cl in self.clusters.items():
            if cl.get("momo_done"): continue
            for m, c in cl["coins"].items():
                since = t - c["detected"]
                if V2["momo_min_watch_sec"] <= since <= V2["momo_watch_sec"] and t - c["created"] <= CFG["coin_max_age_min"] * 60:
                    cands.append((c.get("momo_checked", 0), kw, m))
        cands.sort()  # least recently checked first, so a busy cycle round-robins instead of starving coins
        cands = cands[: V2["momo_max_checks_per_cycle"]]
        if not cands: return
        futs = {(kw, m): self.pool.submit(self.fresh, m) for _, kw, m in cands}
        wait(list(futs.values()), timeout=CFG["http_timeout_sec"] + 2)
        n = V2["momo_rising_marks"]
        for (kw, m), f in futs.items():
            cl = self.clusters[kw]; c = cl["coins"][m]; c["momo_checked"] = t
            if cl.get("momo_done") or not f.done() or f.exception(): continue
            i = f.result()
            if i.get("banned") or not i.get("sol_quoted", True): continue
            hist = c.setdefault("momo_marks", []); hist.append(round(i["mcap_sol"], 3)); del hist[:-(n + 1)]
            rising = len(hist) == n + 1 and all(b > a for a, b in zip(hist, hist[1:]))
            if i["mcap_sol"] >= V2["momo_min_mcap_sol"] and rising:
                if self.try_enter("MOMO", kw, m, c, f"momo_{i['mcap_sol']:.1f}sol_rising{n}"): cl["momo_done"] = True

    def v2_exit(self, p, mc, g, held):
        p["peak_mcap"] = max(p.get("peak_mcap") or mc, mc)
        peak_g = p["peak_mcap"] / p["entry_mcap_sol"] - 1
        if g <= V2["exit_sl_gross"]: return "sl"
        if g >= V2["exit_tp_cap_gross"]: return "tp"
        if peak_g >= V2["exit_trail_arm_gross"] and mc <= p["peak_mcap"] * (1 - V2["exit_trail_drop"]): return "trail"
        if held >= V2["exit_time_sec"]: return "time"
        return None

    def manage_positions(self):
        if not self.positions: return
        t = now()
        futs = {id(p): self.pool.submit(self.fresh, p["mint"]) for p in self.positions}
        wait(list(futs.values()), timeout=CFG["http_timeout_sec"] + 2)
        keep = []
        for p in self.positions:
            f = futs[id(p)]
            held = now() - p["entry_ts"]
            if not f.done() or f.exception():
                p["price_errors"] = p.get("price_errors", 0) + 1
                if held > CFG["time_exit_sec"] + 300:
                    self.close(p, p["last_mcap"], "time_exit_stale_price"); continue
                keep.append(p); continue
            mc = f.result()["mcap_sol"]; prev = p["last_mcap"]
            jx = CFG.get("max_mark_jump_x", 20)
            if prev and (mc / prev > jx or prev / mc > jx):
                p["bad_marks"] = p.get("bad_marks", 0) + 1
                jl("events.jsonl", {"ts": t, "iso": iso(t), "event": "bad_mark", "rule": p["rule"], "mint": p["mint"], "symbol": p["symbol"], "mcap": mc, "prev": prev})
                if held > CFG["time_exit_sec"] + 300:
                    self.close(p, p["last_mcap"], "time_exit_stale_price"); continue
                keep.append(p); continue
            p["marks"] += 1; p["last_mcap"] = mc
            g = mc / p["entry_mcap_sol"] - 1
            reason = None
            if p["rule"] in V2_RULES: reason = self.v2_exit(p, mc, g, held)
            elif g >= CFG["tp_gross"]: reason = "tp"
            elif g <= CFG["sl_gross"]: reason = "sl"
            elif held >= CFG["time_exit_sec"]: reason = "time"
            if reason: self.close(p, mc, reason)
            else: keep.append(p)
        self.positions = keep

    def close(self, p, mc, reason):
        t = now(); g = mc / p["entry_mcap_sol"] - 1; net = g - CFG["rt_cost"]; pnl = CFG["notional_sol"] * net
        row = {**p, "exit_ts": t, "exit_iso": iso(t), "entry_iso": iso(p["entry_ts"]), "exit_mcap_sol": mc, "hold_s": round(t - p["entry_ts"]),
               "reason": reason, "gross_ret": round(g, 4), "net_ret": round(net, 4), "pnl_sol": round(pnl, 5)}
        with open(TRADES_CSV, "a", newline="") as f: csv.writer(f).writerow([row.get(c) for c in CSV_COLS])
        jl("events.jsonl", {"ts": t, "iso": iso(t), "event": "CLOSE", **row})
        status(f"PAPER CLOSE {p['rule']} {p['symbol']} {reason} gross={g*100:+.1f}% net={net*100:+.1f}% pnl={pnl:+.4f} SOL hold={row['hold_s']}s")

    # ---------- loop ----------
    def run(self):
        status(f"START pid={os.getpid()} PAPER_ONLY cfg tp={CFG['tp_gross']} sl={CFG['sl_gross']} time={CFG['time_exit_sec']}s cost={CFG['rt_cost']}")
        if V2: status(f"TEST v2 rules {','.join(V2_RULES)} running alongside v1 FIRST/LEADER (v1 unchanged); v2 params={json.dumps({k: v for k, v in V2.items() if k != 'note'})}")
        if self.last_cycle_end and now() - self.last_cycle_end > 120:
            status(f"GAP detected: {round(now()-self.last_cycle_end)}s since last cycle (box sleep/stop)")
        while True:
            t0 = now(); self.cycle += 1
            signal.alarm(CFG["cycle_deadline_sec"])
            try:
                if self.last_cycle_end and t0 - self.last_cycle_end > 120:
                    status(f"GAP {round(t0-self.last_cycle_end)}s between cycles (box sleep?)")
                ns = self.poll_news() if t0 - self.last_news >= CFG["news_poll_sec"] else None
                coins, errs = self.poll_coins()
                newc, matches = self.process_coins(coins)
                self.handle_entries()
                self.manage_positions()
                signal.alarm(0)
                self.last_cycle_end = now(); self.save()
                hb = {"ts": iso(), "cycle": self.cycle, "dur_s": round(now() - t0, 2), "new_stories": ns, "live_keywords": len(self.keywords),
                      "coins_fetched": len(coins), "new_coins": newc, "pump_errs": errs, "matches": len(matches),
                      "clusters": len(self.clusters), "open": [(p["rule"], p["symbol"]) for p in self.positions], "sources": self.source_ok}
                json.dump(hb, open(os.path.join(LOG, "heartbeat.json"), "w"))
                if ns is not None or matches or self.cycle % 20 == 0:
                    status(f"cycle={self.cycle} dur={hb['dur_s']}s stories+={ns} kws={len(self.keywords)} coins={len(coins)} new={newc} matches={len(matches)} "
                           f"{[m['symbol'] + '~' + m['kw'] for m in matches][:6]} open={len(self.positions)} pump_errs={errs}")
            except Deadline:
                status(f"cycle={self.cycle} DEADLINE exceeded {CFG['cycle_deadline_sec']}s — continuing")
            except Exception as e:
                signal.alarm(0)
                status(f"cycle={self.cycle} ERROR {type(e).__name__}: {e}")
                jl("errors.jsonl", {"iso": iso(), "tb": traceback.format_exc()})
            time.sleep(max(1, CFG["cycle_sec"] - (now() - t0)))

class Deadline(Exception): pass
def _alarm(sig, frm): raise Deadline()
signal.signal(signal.SIGALRM, _alarm)

if __name__ == "__main__":
    Bot().run()
