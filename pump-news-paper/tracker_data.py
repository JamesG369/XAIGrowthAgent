#!/usr/bin/env python3
"""Emit the DATA object for the 'Crypto paper-trading tracker' Page as JSON.
Usage: python3 tracker_data.py [--logs DIR] [--state FILE]   -> JSON to stdout
       python3 tracker_data.py --block    -> full '// DATA-START ... // DATA-END' block (also saved to tracker_block_new.txt)
After a successful EditCanvas, run: mv tracker_block_new.txt tracker_block_published.txt (published = current old_string).
Paper only; reads local logs, no network."""
import csv, json, os, re, sys, time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
# Paths are relative to this script (portable). Override with env vars or --logs DIR / --state FILE.
HERE = os.path.dirname(os.path.abspath(__file__))
NEWS = os.environ.get("PUMP_NEWS_DIR", HERE)
CONS = os.environ.get("PUMP_CONS_DIR", os.path.join(HERE, "legacy", "pump-consensus-paper"))
def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else default
NL = _arg("--logs", os.environ.get("PUMP_NEWS_LOGS", os.path.join(NEWS, "logs")))
STATE = _arg("--state", os.environ.get("PUMP_NEWS_STATE", os.path.join(NEWS, "data", "state.json")))

def et(ts, fmt="%b %-d, %-I:%M %p"):
    if ts in (None, ""): return ""
    if isinstance(ts, str):
        try: d = datetime.fromisoformat(ts)
        except ValueError: return ts
        if d.tzinfo is None: d = d.replace(tzinfo=ZoneInfo("UTC"))
    else: d = datetime.fromtimestamp(float(ts), tz=ET)
    return d.astimezone(ET).strftime(fmt) + " ET"

def tsec(iso):
    try: return datetime.fromisoformat(iso).timestamp()
    except Exception: return None

def jl(path):
    out = []
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            l = l.strip()
            if not l: continue
            try: out.append(json.loads(l))
            except Exception: pass
    return out

def alive(pidfile):
    try:
        pid = int(open(pidfile).read().strip()); os.kill(pid, 0); return True
    except Exception: return False

def short(s, n=70):
    s = (s or "").strip(); return s if len(s) <= n else s[: n - 1] + "…"

def fnum(x):
    try: return float(x)
    except Exception: return None

def skip_cat(why):
    w = (why or "unknown").lower()
    w = re.sub(r"_?[\d.]+(sol|pct|_in_2h)?$", "", w)
    w = re.sub(r"_\d+(_in_2h)?$", "", w)
    return {"top_holder": "Top holder too big", "no_traction": "Leader: no traction", "serial_launcher": "Serial launcher",
            "creator_tokens": "Creator has many tokens", "late": "Too late", "dev_holds": "Dev holds too much",
            "pre_story": "Coin predates story", "baseline_generic": "Generic keyword", "insiders": "Too many insiders",
            "rugged": "Rugged", "mint_auth": "Mint authority set", "freeze_auth": "Freeze authority set",
            "banned": "Banned / NSFW", "nsfw": "Banned / NSFW", "max_concurrent": "Max concurrent",
            "decision_late": "Leader decision late", "bad_price_data": "Bad price data", "non_sol_quote": "Not SOL-quoted"}.get(w, w.replace("_", " ").capitalize())

now = time.time()
cfg = json.load(open(os.path.join(NEWS, "config.json")))
notional = cfg.get("notional_sol", 0.05)

# ---------- status ----------
hb = {}
try: hb = json.load(open(os.path.join(NL, "heartbeat.json")))
except Exception: pass
hb_ts = tsec(hb.get("ts", "")) if hb.get("ts") else None
hb_age = round(now - hb_ts) if hb_ts else None
bot_up, wd_up = alive(os.path.join(NL, "bot.pid")), alive(os.path.join(NL, "watchdog.pid"))
running = bot_up and hb_age is not None and hb_age < 180
status_lines = open(os.path.join(NL, "status.log"), encoding="utf-8").read().splitlines() if os.path.exists(os.path.join(NL, "status.log")) else []
gaps = [{"time": et(l.split(" ", 1)[0]), "text": l.split(" ", 1)[1] if " " in l else l}
        for l in status_lines if "GAP" in l or "RESTART" in l.upper() or "watchdog restart" in l.lower()]
sources = []
for k, v in (hb.get("sources") or {}).items():
    ok = str(v).startswith("ok")
    sources.append({"name": k, "ok": ok, "detail": str(v)})
stories = jl(os.path.join(NL, "stories.jsonl"))
status = {
    "running": running, "bot_process": bot_up, "watchdog": wd_up,
    "last_heartbeat": et(hb.get("ts"), "%b %-d, %-I:%M:%S %p") if hb.get("ts") else "",
    "heartbeat_age_s": hb_age, "cycles": hb.get("cycle"), "live_keywords": hb.get("live_keywords"),
    "stories_seen": len(stories), "clusters": hb.get("clusters"), "pump_errs": hb.get("pump_errs"),
    "started": "Oct 30, 5:31 PM ET", "sources": sources, "sources_ok": sum(s["ok"] for s in sources),
    "gaps": gaps[-10:],
}

# ---------- trades ----------
allrows = list(csv.DictReader(open(os.path.join(NL, "paper_trades.csv"), encoding="utf-8"))) if os.path.exists(os.path.join(NL, "paper_trades.csv")) else []
def _excl(x): return bool((x.get("excluded") or "").strip())
voided = [{"time": et(x.get("exit_iso")), "rule": x["rule"], "symbol": x["symbol"], "name": x.get("name", ""), "mint": x["mint"],
           "story": short(x.get("story"), 60), "entry_mcap_sol": fnum(x.get("entry_mcap_sol")), "reason": x.get("void_reason") or "excluded"} for x in allrows if _excl(x)]
rows = [x for x in allrows if not _excl(x)]
rows.sort(key=lambda r: fnum(r.get("exit_ts")) or 0)
V1_RULES, V2_RULES = ["FIRST", "LEADER"], ["FIRST2", "MOMO"]
RULES = V1_RULES + [r for r in V2_RULES if (cfg.get("v2") or {}).get("enabled") or any(x["rule"] == r for x in allrows)]
rules = {}
for rule in RULES:
    r = [x for x in rows if x["rule"] == rule]
    pn = [fnum(x["pnl_sol"]) or 0.0 for x in r]; nr = [fnum(x["net_ret"]) or 0.0 for x in r]
    eq = peak = dd = 0.0
    for p in pn: eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    w = [v for v in nr if v > 0]; l = [v for v in nr if v <= 0]
    rules[rule] = {"closed": len(r), "wins": len(w), "losses": len(l),
        "win_rate": round(len(w) / len(r) * 100, 1) if r else 0,
        "avg_win_pct": round(sum(w) / len(w) * 100, 1) if w else None,
        "avg_loss_pct": round(sum(l) / len(l) * 100, 1) if l else None,
        "net_sol": round(sum(pn), 5), "net_pct": round(sum(pn) / (notional * len(r)) * 100, 1) if r else 0,
        "max_dd_sol": round(dd, 5), "exits": dict(Counter(x["reason"] for x in r)),
        "progress": min(len(r), 50), "pass_bar_met": len(r) >= 50 and sum(pn) > 0, "open": 0,
        "version": "v2" if rule in V2_RULES else "v1"}
# cumulative series: one point per close, both rules carried forward
cum = {r: 0.0 for r in RULES}; series = []
for x in rows:
    cum[x["rule"]] = cum.get(x["rule"], 0.0) + (fnum(x["pnl_sol"]) or 0.0)
    series.append({"label": et(x.get("exit_iso"), "%-m/%-d %-I:%M %p")[:-3], **{r: round(v, 5) for r, v in cum.items()}})
if series: series.insert(0, {"label": "Start", **{r: 0.0 for r in cum}})

recent = []
for x in reversed(rows[-25:]):
    recent.append({"time": et(x.get("exit_iso")), "rule": x["rule"], "symbol": x["symbol"], "name": x.get("name", ""),
        "mint": x["mint"], "keyword": x["keyword"], "story": short(x["story"], 60), "hold_s": int(fnum(x["hold_s"]) or 0),
        "reason": x["reason"], "net_pct": round((fnum(x["net_ret"]) or 0) * 100, 1), "pnl_sol": round(fnum(x["pnl_sol"]) or 0, 5)})

# ---------- open positions ----------
opens = []
try:
    st = json.load(open(STATE))
    for p in st.get("positions", []):
        if p.get("excluded"): continue
        e, m = fnum(p.get("entry_mcap_sol")), fnum(p.get("last_mcap"))
        rules.get(p["rule"], {}).__setitem__("open", rules.get(p["rule"], {}).get("open", 0) + 1)
        opens.append({"rule": p["rule"], "symbol": p.get("symbol"), "name": p.get("name"), "mint": p.get("mint"),
            "keyword": p.get("keyword"), "story": short(p.get("story"), 60), "entry": et(p.get("entry_ts")),
            "held_s": int(now - p["entry_ts"]) if p.get("entry_ts") else None,
            "entry_mcap_sol": round(e, 1) if e else None, "mark_mcap_sol": round(m, 1) if m else None,
            "marks": p.get("marks"), "gross_pct": round((m / e - 1) * 100, 1) if e and m else None})
except Exception: pass

# ---------- matches & skips ----------
events = jl(os.path.join(NL, "events.jsonl"))
outcome = {}
for ev in events:
    key = (ev.get("kw"), ev.get("mint"))
    if ev.get("event") == "OPEN": outcome.setdefault(key, []).append(f"{ev.get('rule')}: opened")
    elif ev.get("event") == "skip": outcome.setdefault(key, []).append(f"{ev.get('rule')}: {skip_cat(ev.get('why'))}")
matches = jl(os.path.join(NL, "matches.jsonl"))
recent_matches = []
for m in reversed(matches[-20:]):
    o = outcome.get((m.get("kw"), m.get("mint")), [])
    if m.get("status") not in (None, "match"): o = [skip_cat(m.get("status"))] + o
    mc = fnum(m.get("mcap_sol"))
    recent_matches.append({"time": et(m.get("iso")), "keyword": m.get("kw"), "symbol": m.get("symbol"), "name": m.get("name"),
        "mint": m.get("mint"), "story": short(m.get("story"), 60), "source": m.get("source"), "coin_age_s": m.get("coin_age_s"),
        "mcap_sol": round(mc, 1) if mc and mc < 100000 else None, "outcome": "; ".join(dict.fromkeys(o)) or "logged"})
skips = Counter(skip_cat(ev.get("why")) for ev in events if ev.get("event") == "skip")
skips.update(skip_cat(m.get("status")) for m in matches if m.get("status") not in (None, "match"))
skip_list = [{"label": k, "value": v} for k, v in skips.most_common()]

# ---------- paused consensus logger ----------
ct = jl(os.path.join(CONS, "logs", "paper_trades.jsonl"))
closes = [c for c in ct if c.get("action") == "close"]
priced = [c for c in closes if c.get("sim_pnl_sol") not in (None, "")]
sig = jl(os.path.join(CONS, "logs", "signals.jsonl"))
prim = [s for s in sig if s.get("primary")]
cw = [c for c in priced if (fnum(c["sim_pnl_sol"]) or 0) > 0]
consensus = {"status": "Paused", "paused_at": "Oct 29, 12:58 PM ET", "first_signal": et(sig[0]["ts"]) if sig else "",
    "signals_5": sum(1 for s in prim if s.get("rule_hit") == 5), "signals_7": sum(1 for s in prim if s.get("rule_hit") == 7),
    "opened": sum(1 for c in ct if c.get("action") == "open"), "skipped": sum(1 for c in ct if c.get("action") == "skip"),
    "closed": len(closes), "priced": len(priced), "wins": len(cw), "losses": len(priced) - len(cw),
    "net_sol": round(sum(fnum(c["sim_pnl_sol"]) for c in priced), 4),
    "exits": dict(Counter(c.get("exit_reason") for c in closes)),
    "note": "3 early time exits (Oct 28) were booked at entry price by a since-fixed price bug, and 1 has no price, so the total is approximate.",
    "trades": [{"time": et(c["ts"]), "mint": c["mint"], "reason": c.get("exit_reason"),
                "net_pct": fnum(c.get("net_pct_after_8rt")), "pnl_sol": fnum(c.get("sim_pnl_sol"))} for c in closes]}

DATA = {"as_of": datetime.now(ET).strftime("%b %-d, %-I:%M %p") + " ET", "status": status, "rules": rules,
        "rule_order": RULES, "series": series, "open": opens, "recent": recent, "matches": recent_matches, "skips": skip_list, "excluded": voided, "consensus": consensus}

if "--block" in sys.argv:
    blk = "// DATA-START\nconst DATA = " + json.dumps(DATA, ensure_ascii=False, separators=(",", ":")) + ";\n// DATA-END"
    open(os.path.join(NEWS, "tracker_block_new.txt"), "w", encoding="utf-8").write(blk)
    print("// DATA-START\nconst DATA = " + json.dumps(DATA, ensure_ascii=False, separators=(",", ":")) + ";\n// DATA-END")
else:
    print(json.dumps(DATA, ensure_ascii=False, indent=1))
