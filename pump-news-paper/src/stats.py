import csv, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
allrows = list(csv.DictReader(open(os.path.join(ROOT, "logs/paper_trades.csv"))))
rows = [x for x in allrows if not (x.get("excluded") or "").strip()]
ex = [x for x in allrows if (x.get("excluded") or "").strip()]
if ex: print(f"excluded (voided, not counted): {len(ex)} -> " + ", ".join(f"{x['rule']} {x['symbol']} ({x.get('void_reason')})" for x in ex))
for rule in ("FIRST", "LEADER"):
    r = [x for x in rows if x["rule"] == rule]
    pn = [float(x["pnl_sol"]) for x in r]; nr = [float(x["net_ret"]) for x in r]
    eq = peak = dd = 0.0
    for p in pn: eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    w = [v for v in nr if v > 0]; l = [v for v in nr if v <= 0]
    reasons = {}
    for x in r: reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    print(f"{rule}: closed={len(r)} net_pnl={sum(pn):+.4f} SOL win_rate={(len(w)/len(r)*100 if r else 0):.0f}% "
          f"avg_win={(sum(w)/len(w)*100 if w else 0):+.1f}% avg_loss={(sum(l)/len(l)*100 if l else 0):+.1f}% max_dd={dd:+.4f} SOL exits={reasons} "
          f"pass_bar={'MET' if len(r)>=50 and sum(pn)>0 else 'not met'}")
