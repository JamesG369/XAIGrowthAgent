#!/usr/bin/env python3
"""
Pump.fun consensus PAPER logger — NO LIVE TRADES.

Polls public Solana RPCs for watched-wallet buy/sell activity, detects
multi-wallet consensus in 30/60/120s windows, and simulates flat 0.05 SOL
entries with an 8% round-trip cost haircut.

Degraded by design: poll lag typically ~30–90s (not gRPC), tip/referral noise
filtered via owner token-balance deltas, pump.fun frontend Cloudflare-blocked.

Optional later: export HELIUS_RPC_URL=https://mainnet.helius-rpc.com/?api-key=...
and prepend it in config rpc_urls (not required; free public RPCs work).
"""
from __future__ import annotations

import csv
import json
import os
import signal
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOGS = ROOT / "logs"
STATE_PATH = DATA / "state.json"
EVENTS_JSONL = LOGS / "events.jsonl"
SIGNALS_JSONL = LOGS / "signals.jsonl"
TRADES_JSONL = LOGS / "paper_trades.jsonl"
TRADES_CSV = LOGS / "paper_trades.csv"
HEARTBEAT = LOGS / "heartbeat.json"
STATUS = LOGS / "status.log"

WSOL = "So11111111111111111111111111111111111111112"
IGNORE_MINTS = {
    WSOL,
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "USD1ttGY1N17NEEOGmBshE8Y8uj4MMqJ2HXNyYZ4pump",
}

RUNNING = True
_STATUS_LOCK = Lock()
_PRICE_LOCK = Lock()
_PRICE_CACHE: Dict[str, Tuple[float, dict]] = {}  # mint -> (fetched_at, info)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: Optional[float] = None) -> str:
    if ts is None:
        return utc_now().isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def log_status(msg: str) -> None:
    line = f"{iso()} {msg}"
    print(line, flush=True)
    with _STATUS_LOCK:
        with open(STATUS, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def append_jsonl(path: Path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    tmp.replace(path)


def write_heartbeat(payload: dict) -> None:
    save_json(HEARTBEAT, payload)


class RpcPool:
    def __init__(self, urls: List[str], timeout: float = 10.0):
        self.urls = list(urls)
        # Optional free upgrade path — stub only; no key required.
        helius = os.environ.get("HELIUS_RPC_URL", "").strip()
        if helius and helius not in self.urls:
            self.urls.insert(0, helius)
        self.i = 0
        self.fail_streak = 0
        self.timeout = timeout
        self._lock = Lock()

    def call(self, method: str, params: list, timeout: Optional[float] = None) -> Any:
        to = self.timeout if timeout is None else timeout
        last_err = None
        n = len(self.urls)
        # At most one pass + one failover — never burn minutes on retries.
        for attempt in range(min(n, 2)):
            with self._lock:
                url = self.urls[(self.i + attempt) % n]
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "pump-consensus-paper/0.2 (paper-only)",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=to) as resp:
                    data = json.load(resp)
                if "error" in data:
                    last_err = data["error"]
                    time.sleep(0.15)
                    continue
                with self._lock:
                    self.i = (self.i + attempt) % n
                    self.fail_streak = 0
                return data.get("result")
            except Exception as e:
                last_err = e
                time.sleep(0.15)
        with self._lock:
            self.fail_streak += 1
        raise RuntimeError(f"RPC fail after retries: {last_err}")


def http_get_json(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "pump-consensus-paper/0.2",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def key_of(k) -> str:
    return k["pubkey"] if isinstance(k, dict) else k


def parse_wallet_token_moves(tx: dict, wallet: str) -> List[Tuple[str, float]]:
    if not tx or not tx.get("meta"):
        return []
    meta = tx["meta"]
    if meta.get("err") is not None:
        return []

    def amt(b: dict) -> float:
        ui = b.get("uiTokenAmount") or {}
        v = ui.get("uiAmount")
        if v is None:
            try:
                return int(ui.get("amount") or 0) / (10 ** int(ui.get("decimals") or 0))
            except Exception:
                return 0.0
        return float(v)

    deltas: Dict[str, float] = defaultdict(float)
    for b in meta.get("preTokenBalances") or []:
        if b.get("owner") == wallet and b.get("mint") not in IGNORE_MINTS:
            deltas[b["mint"]] -= amt(b)
    for b in meta.get("postTokenBalances") or []:
        if b.get("owner") == wallet and b.get("mint") not in IGNORE_MINTS:
            deltas[b["mint"]] += amt(b)
    return [(m, d) for m, d in deltas.items() if abs(d) > 1e-12]


def wallet_is_signer(tx: dict, wallet: str) -> bool:
    try:
        ak = tx["transaction"]["message"]["accountKeys"]
        if key_of(ak[0]) == wallet:
            return True
        for k in ak:
            if key_of(k) == wallet and isinstance(k, dict) and k.get("signer"):
                return True
    except Exception:
        return False
    return False


def dexscreener_info(mint: str, *, force: bool = False, ttl: float = 3.0) -> dict:
    """Fresh mcap/price from DexScreener. Short TTL cache; force bypasses it."""
    now = time.time()
    if not force:
        with _PRICE_LOCK:
            hit = _PRICE_CACHE.get(mint)
            if hit and now - hit[0] < ttl:
                return dict(hit[1])

    out = {
        "mcap_usd": None,
        "price_usd": None,
        "pair_created_ms": None,
        "dex_id": None,
        "curve_pct": None,
        "age_sec": None,
        "fetched_at": now,
    }
    try:
        data = http_get_json(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}?t={int(now * 1000)}",
            timeout=8.0,
        )
        pairs = data.get("pairs") or []
        sol = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol:
            with _PRICE_LOCK:
                _PRICE_CACHE[mint] = (now, out)
            return out
        sol.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
        p = sol[0]
        out["mcap_usd"] = p.get("marketCap") or p.get("fdv")
        out["price_usd"] = float(p["priceUsd"]) if p.get("priceUsd") else None
        out["pair_created_ms"] = p.get("pairCreatedAt")
        out["dex_id"] = p.get("dexId")
        if out["pair_created_ms"]:
            out["age_sec"] = max(0.0, now - out["pair_created_ms"] / 1000.0)
    except Exception as e:
        out["error"] = str(e)
    with _PRICE_LOCK:
        _PRICE_CACHE[mint] = (now, out)
    return out


class PaperEngine:
    def __init__(self, cfg: dict, label_of: Dict[str, str]):
        self.cfg = cfg
        self.label_of = label_of
        self.buys: Dict[str, Deque[Tuple[float, str, str]]] = defaultdict(deque)
        self.sells: Dict[str, Deque[Tuple[float, str, str]]] = defaultdict(deque)
        self.first_buy_mcap: Dict[str, float] = {}
        self.first_buy_ts: Dict[str, float] = {}
        self.fired: Set[str] = set()
        self.positions: List[dict] = []
        self.closed: List[dict] = []
        self._ensure_csv()

    def _ensure_csv(self) -> None:
        if not TRADES_CSV.exists():
            with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "ts", "action", "mint", "rule_hit", "n_wallets", "window_sec",
                        "wallets", "mcap_usd", "age_sec", "curve_pct",
                        "entry_price_usd", "exit_price_usd", "exit_reason",
                        "gross_pct", "net_pct_after_8rt", "sim_pnl_sol", "notes",
                    ],
                )
                w.writeheader()

    def _csv_row(self, row: dict) -> None:
        with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
            fixed = [
                "ts", "action", "mint", "rule_hit", "n_wallets", "window_sec",
                "wallets", "mcap_usd", "age_sec", "curve_pct",
                "entry_price_usd", "exit_price_usd", "exit_reason",
                "gross_pct", "net_pct_after_8rt", "sim_pnl_sol", "notes",
            ]
            w = csv.DictWriter(f, fieldnames=fixed)
            w.writerow({k: row.get(k, "") for k in fixed})

    def on_trade(self, wallet: str, mint: str, side: str, ts: float, sig: str, token_delta: float) -> None:
        label = self.label_of.get(wallet, wallet[:8])
        ev = {
            "ts": iso(ts),
            "ts_unix": ts,
            "type": "wallet_trade",
            "wallet": wallet,
            "label": label,
            "mint": mint,
            "side": side,
            "token_delta": token_delta,
            "sig": sig,
        }
        min_d = float(self.cfg.get("min_token_delta_for_consensus", 1.0))
        if abs(token_delta) < min_d:
            append_jsonl(EVENTS_JSONL, {**ev, "dust": True})
            return
        append_jsonl(EVENTS_JSONL, ev)
        if side == "buy":
            self.buys[mint].append((ts, wallet, sig))
            if mint not in self.first_buy_ts:
                self.first_buy_ts[mint] = ts
            self._trim(mint)
            self._check_consensus(mint, ts)
        else:
            self.sells[mint].append((ts, wallet, sig))
            self._trim(mint)
            self._check_majority_sell(mint, ts)

    def _trim(self, mint: str) -> None:
        cutoff = time.time() - 600
        for dq in (self.buys[mint], self.sells[mint]):
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def _wallets_in_window(self, mint: str, now: float, window: int, side: str = "buy") -> List[str]:
        dq = self.buys[mint] if side == "buy" else self.sells[mint]
        seen = {}
        for ts, w, _sig in dq:
            if now - ts <= window and ts <= now + 1:
                seen[w] = ts
        return sorted(seen.keys(), key=lambda w: seen[w])

    def _check_consensus(self, mint: str, now: float) -> None:
        for window in self.cfg["windows_sec"]:
            wallets = self._wallets_in_window(mint, now, window, "buy")
            n = len(wallets)
            for thr in self.cfg["thresholds"]:
                if n < thr:
                    continue
                bucket = int(now // 60)
                key = f"{mint}|{thr}|{window}|{bucket}"
                if key in self.fired:
                    continue
                self.fired.add(key)
                self._emit_signal(mint, thr, window, wallets, now)

    def _emit_signal(self, mint: str, thr: int, window: int, wallets: List[str], consensus_ts: float) -> None:
        wall_now = time.time()
        lag = wall_now - consensus_ts
        ttl = float(self.cfg.get("price_cache_ttl_sec", 3))
        info = dexscreener_info(mint, force=True, ttl=ttl)
        mcap = info.get("mcap_usd")
        age = info.get("age_sec")
        if mint not in self.first_buy_mcap and mcap:
            self.first_buy_mcap[mint] = float(mcap)

        first_mcap = self.first_buy_mcap.get(mint)
        mcap_chg = None
        if first_mcap and mcap and first_mcap > 0:
            mcap_chg = (float(mcap) - first_mcap) / first_mcap * 100.0

        kills = []
        if age is not None and age > self.cfg["max_mint_age_sec"]:
            kills.append(f"mint_age>{self.cfg['max_mint_age_sec']}s ({age:.0f}s)")
        if mcap_chg is not None and mcap_chg > self.cfg["late_mcap_pct"]:
            kills.append(f"mcap>+{self.cfg['late_mcap_pct']}% ({mcap_chg:.1f}%)")
        curve = info.get("curve_pct")
        if curve is not None and curve > self.cfg["late_curve_pct"]:
            kills.append(f"curve>{self.cfg['late_curve_pct']}%")

        max_lag = float(self.cfg.get("max_signal_lag_sec", 180))
        stale = lag > max_lag
        if stale:
            kills.append(f"stale_signal_lag={lag:.0f}s>{max_lag:.0f}s")

        labels = [self.label_of.get(w, w[:8]) for w in wallets]
        sig_obj = {
            "ts": iso(consensus_ts),
            "ts_unix": consensus_ts,
            "detected_ts": iso(wall_now),
            "detection_lag_sec": round(lag, 2),
            "type": "consensus_signal",
            "mint": mint,
            "rule_hit": thr,
            "n_wallets": len(wallets),
            "window_sec": window,
            "wallets": wallets,
            "labels": labels,
            "mcap_usd": mcap,
            "mcap_chg_from_first_pct": mcap_chg,
            "age_sec": age,
            "curve_pct": curve,
            "dex_id": info.get("dex_id"),
            "kills": kills,
            "primary": window == self.cfg["primary_window_sec"],
            "stale": stale,
        }
        append_jsonl(SIGNALS_JSONL, sig_obj)
        log_status(
            f"SIGNAL ≥{thr}/{len(self.label_of)} mint={mint[:12]}… n={len(wallets)} "
            f"win={window}s lag={lag:.0f}s kills={kills or 'none'} labels={labels}"
        )

        if window != self.cfg["primary_window_sec"]:
            return

        def skip_row(notes: str) -> None:
            row = {
                "ts": iso(wall_now),
                "action": "skip",
                "mint": mint,
                "rule_hit": thr,
                "n_wallets": len(wallets),
                "window_sec": window,
                "wallets": ",".join(labels),
                "mcap_usd": mcap,
                "age_sec": age,
                "curve_pct": curve,
                "entry_price_usd": info.get("price_usd"),
                "exit_price_usd": "",
                "exit_reason": "",
                "gross_pct": "",
                "net_pct_after_8rt": "",
                "sim_pnl_sol": "",
                "notes": notes,
            }
            append_jsonl(TRADES_JSONL, row)
            self._csv_row(row)

        if kills:
            skip_row(";".join(kills))
            return

        open_n = sum(1 for p in self.positions if p["status"] == "open")
        if open_n >= self.cfg["max_positions"]:
            skip_row("max_positions")
            return

        if any(p["status"] == "open" and p["mint"] == mint for p in self.positions):
            return

        entry_px = info.get("price_usd")
        if entry_px is None:
            skip_row("no_entry_price_from_dexscreener")
            return

        # Hold clock is WALL time at open — never consensus block time.
        pos = {
            "id": f"{mint[:8]}-{int(wall_now)}",
            "status": "open",
            "opened_ts": wall_now,
            "consensus_ts": consensus_ts,
            "detection_lag_sec": lag,
            "mint": mint,
            "rule_hit": thr,
            "n_wallets": len(wallets),
            "window_sec": window,
            "wallets": wallets,
            "labels": labels,
            "entry_price_usd": entry_px,
            "entry_mcap_usd": mcap,
            "last_mark_usd": entry_px,
            "last_mark_ts": wall_now,
            "notional_sol": self.cfg["notional_sol"],
            "tp_pct": self.cfg["tp_pct"],
            "sl_pct": self.cfg["sl_pct"],
            "time_exit_sec": self.cfg["time_exit_sec"],
        }
        self.positions.append(pos)
        row = {
            "ts": iso(wall_now),
            "action": "open",
            "mint": mint,
            "rule_hit": thr,
            "n_wallets": len(wallets),
            "window_sec": window,
            "wallets": ",".join(labels),
            "mcap_usd": mcap,
            "age_sec": age,
            "curve_pct": curve,
            "entry_price_usd": entry_px,
            "exit_price_usd": "",
            "exit_reason": "",
            "gross_pct": "",
            "net_pct_after_8rt": "",
            "sim_pnl_sol": "",
            "notes": f"paper_open;8pct_rt_booked_on_close;detect_lag={lag:.0f}s",
        }
        append_jsonl(TRADES_JSONL, {**row, "position_id": pos["id"]})
        self._csv_row(row)
        log_status(
            f"PAPER OPEN ≥{thr} mint={mint[:12]}… entry_px={entry_px} mcap={mcap} "
            f"detect_lag={lag:.0f}s wall_open={iso(wall_now)}"
        )

    def _check_majority_sell(self, mint: str, now: float) -> None:
        sellers5 = self._wallets_in_window(mint, now, 300, "sell")
        need = self.cfg["majority_sell_wallets"]
        if len(sellers5) < need:
            return
        for pos in self.positions:
            if pos["status"] != "open" or pos["mint"] != mint:
                continue
            self._close(pos, time.time(), "majority_sell", note=f"sellers={len(sellers5)}")

    def manage_positions(self) -> None:
        """Mark-to-market every open position with a FRESH DexScreener fetch."""
        wall_now = time.time()
        ttl = float(self.cfg.get("price_cache_ttl_sec", 3))
        for pos in list(self.positions):
            if pos["status"] != "open":
                continue
            hold_sec = wall_now - pos["opened_ts"]
            info = dexscreener_info(pos["mint"], force=True, ttl=ttl)
            px = info.get("price_usd")
            entry = pos.get("entry_price_usd")
            # Never reuse entry as mark — if fetch fails, skip exit decision this cycle
            # (except hard time_exit after grace, logged as price_unavailable).
            if px is None:
                pos["last_mark_error"] = info.get("error") or "no_price"
                log_status(
                    f"MARK FAIL mint={pos['mint'][:12]}… hold={hold_sec:.0f}s "
                    f"err={pos['last_mark_error']}"
                )
                if hold_sec >= pos["time_exit_sec"] + 60:
                    self._close(
                        pos, wall_now, "time_exit_no_price",
                        px=None, gross=None,
                        note=f"held_sec={int(hold_sec)};price_unavailable",
                    )
                continue

            pos["last_mark_usd"] = px
            pos["last_mark_ts"] = wall_now
            reason = None
            gross = None
            if entry and entry > 0:
                gross = (px - entry) / entry * 100.0
                if gross >= pos["tp_pct"]:
                    reason = "tp"
                elif gross <= -pos["sl_pct"]:
                    reason = "sl"
            if reason is None and hold_sec >= pos["time_exit_sec"]:
                reason = "time_exit"
            if reason:
                self._close(pos, wall_now, reason, px=px, gross=gross)
            else:
                log_status(
                    f"MARK mint={pos['mint'][:12]}… hold={hold_sec:.0f}s "
                    f"entry={entry} mark={px} gross={None if gross is None else round(gross, 3)}%"
                )

    def _close(self, pos: dict, now: float, reason: str, px=None, gross=None, note: str = "") -> None:
        if pos["status"] != "open":
            return
        if px is None and reason != "time_exit_no_price":
            info = dexscreener_info(pos["mint"], force=True)
            px = info.get("price_usd")
        entry = pos.get("entry_price_usd")
        # Refuse to invent a mark from entry — leave gross None if no fresh px
        if px is not None and entry and entry > 0 and gross is None:
            gross = (px - entry) / entry * 100.0
        elif px is None:
            gross = None
        rt = self.cfg["rt_cost_pct"]
        net = (gross - rt) if gross is not None else None
        pnl_sol = (net / 100.0 * pos["notional_sol"]) if net is not None else None
        hold_sec = int(now - pos["opened_ts"])
        pos["status"] = "closed"
        pos["closed_ts"] = now
        pos["exit_reason"] = reason
        pos["exit_price_usd"] = px
        pos["gross_pct"] = gross
        pos["net_pct_after_8rt"] = net
        pos["sim_pnl_sol"] = pnl_sol
        same_px = (
            entry is not None and px is not None
            and abs(float(px) - float(entry)) / max(abs(float(entry)), 1e-18) < 1e-12
        )
        notes = note or f"held_sec={hold_sec}"
        if same_px:
            notes += ";exit_eq_entry_real_or_illiquid"
        row = {
            "ts": iso(now),
            "action": "close",
            "mint": pos["mint"],
            "rule_hit": pos["rule_hit"],
            "n_wallets": pos["n_wallets"],
            "window_sec": pos["window_sec"],
            "wallets": ",".join(pos.get("labels") or []),
            "mcap_usd": pos.get("entry_mcap_usd"),
            "age_sec": "",
            "curve_pct": "",
            "entry_price_usd": entry,
            "exit_price_usd": px,
            "exit_reason": reason,
            "gross_pct": None if gross is None else round(gross, 4),
            "net_pct_after_8rt": None if net is None else round(net, 4),
            "sim_pnl_sol": None if pnl_sol is None else round(pnl_sol, 6),
            "notes": notes,
        }
        append_jsonl(TRADES_JSONL, {**row, "position_id": pos["id"]})
        self._csv_row(row)
        self.closed.append(pos)
        log_status(
            f"PAPER CLOSE {reason} mint={pos['mint'][:12]}… "
            f"entry={entry} exit={px} gross={gross} net_after_8%={net} "
            f"pnl_sol={pnl_sol} held={hold_sec}s"
        )


def handle_sig(signum, frame):
    global RUNNING
    RUNNING = False
    log_status(f"signal {signum} — shutting down")


def poll_wallet(rpc: RpcPool, wallet: str, seen: Set[str], cfg: dict) -> List[dict]:
    """Return new trade events for wallet. Caps new txs per cycle to avoid catch-up storms."""
    out: List[dict] = []
    max_new = int(cfg.get("max_new_txs_per_wallet_per_cycle", 8))
    try:
        sigs = rpc.call("getSignaturesForAddress", [wallet, {"limit": cfg["sig_limit"]}]) or []
    except Exception as e:
        log_status(f"sig fail {wallet[:8]}… {e}")
        return out

    pending = []
    for s in reversed(sigs):
        sig = s.get("signature")
        if not sig or sig in seen:
            continue
        if s.get("err") is not None:
            seen.add(sig)
            continue
        pending.append(s)

    fetched = 0
    for s in pending:
        if fetched >= max_new:
            # Leave unseen so a later cycle can pick them up (bounded lag).
            break
        sig = s["signature"]
        seen.add(sig)
        try:
            tx = rpc.call(
                "getTransaction",
                [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}],
            )
        except Exception:
            continue
        if not tx:
            continue
        moves = parse_wallet_token_moves(tx, wallet)
        if not moves:
            continue
        mint, delta = max(moves, key=lambda x: abs(x[1]))
        side = "buy" if delta > 0 else "sell"
        ts = float(tx.get("blockTime") or s.get("blockTime") or time.time())
        out.append(
            {
                "wallet": wallet,
                "mint": mint,
                "side": side,
                "delta": delta,
                "ts": ts,
                "sig": sig,
                "signer": wallet_is_signer(tx, wallet),
            }
        )
        fetched += 1
        sleep_tx = float(cfg.get("sleep_between_txs_sec", 0.05))
        if sleep_tx > 0:
            time.sleep(sleep_tx)
    return out


def poll_all_wallets(
    rpc: RpcPool,
    addresses: List[str],
    seen_map: Dict[str, Set[str]],
    cfg: dict,
    cycle: int,
) -> Tuple[List[dict], int, int]:
    """Parallel wallet poll with per-wallet and cycle deadlines."""
    workers = max(1, int(cfg.get("parallel_wallets", 6)))
    wallet_to = float(cfg.get("wallet_timeout_sec", 18))
    deadline = time.time() + float(cfg.get("cycle_deadline_sec", 70))
    events: List[dict] = []
    errors = 0
    timed_out = 0
    done = 0

    def _one(addr: str) -> List[dict]:
        return poll_wallet(rpc, addr, seen_map[addr], cfg)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, addr): addr for addr in addresses}
        pending = set(futs.keys())
        while pending and RUNNING:
            remaining = deadline - time.time()
            if remaining <= 0:
                for fut in pending:
                    fut.cancel()
                    timed_out += 1
                log_status(
                    f"cycle={cycle} DEADLINE hit — skipped {len(pending)} wallets "
                    f"(completed={done}/{len(addresses)})"
                )
                break
            try:
                for fut in as_completed(pending, timeout=min(remaining, 2.0)):
                    pending.discard(fut)
                    addr = futs[fut]
                    try:
                        evs = fut.result(timeout=0.1)
                        events.extend(evs)
                    except Exception as e:
                        errors += 1
                        log_status(f"wallet loop err {addr[:8]}… {e}")
                    done += 1
                    break
            except FuturesTimeout:
                # poke heartbeat mid-cycle so external watchdog stays calm
                write_heartbeat(
                    {
                        "status": "cycling",
                        "ts": iso(),
                        "cycle": cycle,
                        "wallets_done": done,
                        "wallets_total": len(addresses),
                        "mode": "paper_only",
                    }
                )
                continue

    # Sort by block time so consensus sees natural order
    events.sort(key=lambda e: e["ts"])
    return events, errors, timed_out


def main() -> int:
    # Cap any stray socket hang well below previous multi-minute stalls.
    socket.setdefaulttimeout(15)

    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    cfg = load_json(ROOT / "config.json", {})
    watch = load_json(ROOT / "watchlist.json", [])
    label_of = {w["address"]: w["label"] for w in watch}
    addresses = [w["address"] for w in watch]

    state = load_json(STATE_PATH, {"seen_sigs": {}, "started_at": iso()})
    seen_map: Dict[str, Set[str]] = {
        a: set(state.get("seen_sigs", {}).get(a, [])) for a in addresses
    }

    rpc = RpcPool(cfg["rpc_urls"], timeout=float(cfg.get("rpc_timeout_sec", 10)))
    engine = PaperEngine(cfg, label_of)

    signal.signal(signal.SIGTERM, handle_sig)
    signal.signal(signal.SIGINT, handle_sig)

    log_status(
        f"START paper consensus logger v0.2 wallets={len(addresses)} "
        f"thresholds={cfg['thresholds']} windows={cfg['windows_sec']} "
        f"NOTIONAL={cfg['notional_sol']}SOL RT_COST={cfg['rt_cost_pct']}% "
        f"parallel={cfg.get('parallel_wallets')} cycle_deadline={cfg.get('cycle_deadline_sec')}s "
        f"max_signal_lag={cfg.get('max_signal_lag_sec')}s PAPER_ONLY"
    )
    write_heartbeat(
        {
            "status": "starting",
            "ts": iso(),
            "mode": "paper",
            "feed": "public_solana_rpc_poll+dexscreener",
            "degraded": True,
            "wallets": len(addresses),
            "version": "0.2",
        }
    )

    cycle = 0
    while RUNNING:
        cycle += 1
        t0 = time.time()
        events, errors, timed_out = poll_all_wallets(rpc, addresses, seen_map, cfg, cycle)
        n_trades = 0
        for ev in events:
            if not RUNNING:
                break
            engine.on_trade(ev["wallet"], ev["mint"], ev["side"], ev["ts"], ev["sig"], ev["delta"])
            n_trades += 1

        try:
            engine.manage_positions()
        except Exception as e:
            log_status(f"manage_positions err {e}")

        state["seen_sigs"] = {a: list(seen_map[a])[-400:] for a in addresses}
        state["last_cycle"] = iso()
        state["cycle"] = cycle
        save_json(STATE_PATH, state)

        open_n = sum(1 for p in engine.positions if p["status"] == "open")
        cycle_sec = round(time.time() - t0, 2)
        hb = {
            "status": "running",
            "ts": iso(),
            "cycle": cycle,
            "cycle_sec": cycle_sec,
            "trades_this_cycle": n_trades,
            "errors": errors,
            "timed_out_wallets": timed_out,
            "open_positions": open_n,
            "closed_positions": len(engine.closed),
            "rpc_fail_streak": rpc.fail_streak,
            "mode": "paper_only",
            "feed": "degraded_public_rpc_poll",
            "version": "0.2",
            "lag_note": (
                f"poll~{cfg.get('poll_interval_sec')}s parallel={cfg.get('parallel_wallets')} "
                f"deadline={cfg.get('cycle_deadline_sec')}s; not sub-second; "
                f"stale_skip>{cfg.get('max_signal_lag_sec')}s"
            ),
        }
        write_heartbeat(hb)
        log_status(
            f"cycle={cycle} trades={n_trades} open={open_n} closed={len(engine.closed)} "
            f"sec={cycle_sec} err={errors} timeout_wallets={timed_out}"
        )

        elapsed = time.time() - t0
        wait = max(3.0, float(cfg["poll_interval_sec"]) - elapsed)
        end = time.time() + wait
        while RUNNING and time.time() < end:
            time.sleep(0.5)

    write_heartbeat({"status": "stopped", "ts": iso(), "cycle": cycle, "version": "0.2"})
    log_status("STOPPED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        log_status("FATAL\n" + traceback.format_exc())
        sys.exit(1)
