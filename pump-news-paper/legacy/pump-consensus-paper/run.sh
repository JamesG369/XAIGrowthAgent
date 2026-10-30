#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p logs data
PIDFILE=logs/logger.pid
WDPIDFILE=logs/watchdog.pid
OUT=logs/logger.out
WDOUT=logs/watchdog.out

# Stall seconds before watchdog restarts logger (matches config watchdog_stall_sec default)
STALL_SEC="${WATCHDOG_STALL_SEC:-180}"

cmd="${1:-start}"

_is_alive() {
  local pf="$1"
  [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null
}

_start_logger() {
  if _is_alive "$PIDFILE"; then
    echo "already running pid=$(cat "$PIDFILE")"
    return 0
  fi
  nohup python3 -u src/logger.py >>"$OUT" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 1
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "started pid=$(cat "$PIDFILE") out=$ROOT/$OUT"
  else
    echo "failed to start — see $OUT"
    return 1
  fi
}

_start_watchdog() {
  if _is_alive "$WDPIDFILE"; then
    echo "watchdog already running pid=$(cat "$WDPIDFILE")"
    return 0
  fi
  nohup bash -c "
    STALL=$STALL_SEC
    ROOT='$ROOT'
    cd \"\$ROOT\"
    echo \"\$(date -Iseconds) watchdog start stall=\${STALL}s\" >> logs/watchdog.out
    while true; do
      sleep 30
      if [[ ! -f logs/logger.pid ]] || ! kill -0 \"\$(cat logs/logger.pid)\" 2>/dev/null; then
        echo \"\$(date -Iseconds) watchdog: logger dead — restarting\" >> logs/watchdog.out
        echo \"\$(date -Iseconds) WATCHDOG restart: logger process dead\" >> logs/status.log
        nohup python3 -u src/logger.py >> logs/logger.out 2>&1 &
        echo \$! > logs/logger.pid
        sleep 2
        continue
      fi
      if [[ -f logs/heartbeat.json ]]; then
        # Prefer python for ISO parse; fall back to mtime
        age=\$(python3 -c '
import json, time
from datetime import datetime
try:
  hb=json.load(open(\"logs/heartbeat.json\"))
  ts=hb.get(\"ts\") or \"\"
  if ts.endswith(\"Z\"): ts=ts[:-1]+\"+00:00\"
  t=datetime.fromisoformat(ts).timestamp()
  print(int(time.time()-t))
except Exception:
  import os
  print(int(time.time()-os.path.getmtime(\"logs/heartbeat.json\")))
' 2>/dev/null || echo 99999)
        if [[ \"\$age\" -gt \"\$STALL\" ]]; then
          old=\$(cat logs/logger.pid)
          echo \"\$(date -Iseconds) watchdog: stall age=\${age}s>\${STALL}s — killing \$old and restarting\" >> logs/watchdog.out
          echo \"\$(date -Iseconds) WATCHDOG stall recovery: heartbeat_age=\${age}s>\${STALL}s killing_pid=\$old\" >> logs/status.log
          kill \"\$old\" 2>/dev/null || true
          sleep 2
          kill -9 \"\$old\" 2>/dev/null || true
          nohup python3 -u src/logger.py >> logs/logger.out 2>&1 &
          echo \$! > logs/logger.pid
          echo \"\$(date -Iseconds) WATCHDOG restarted pid=\$(cat logs/logger.pid)\" >> logs/status.log
          sleep 2
        fi
      fi
    done
  " >>"$WDOUT" 2>&1 &
  echo $! >"$WDPIDFILE"
  sleep 0.5
  echo "watchdog started pid=$(cat "$WDPIDFILE") stall=${STALL_SEC}s"
}

_stop_all() {
  if _is_alive "$WDPIDFILE"; then
    kill "$(cat "$WDPIDFILE")" 2>/dev/null || true
    # kill the inner bash loop's child sleep too
    sleep 0.3
    echo "stopped watchdog $(cat "$WDPIDFILE")"
    rm -f "$WDPIDFILE"
  else
    echo "no watchdog pidfile"
    rm -f "$WDPIDFILE"
  fi
  if _is_alive "$PIDFILE"; then
    pid=$(cat "$PIDFILE")
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "stopped logger $pid"
  else
    echo "no logger pidfile / not running"
    rm -f "$PIDFILE"
  fi
}

case "$cmd" in
  start)
    _start_logger
    _start_watchdog
    ;;
  stop)
    _stop_all
    ;;
  status)
    if _is_alive "$PIDFILE"; then
      echo "running pid=$(cat "$PIDFILE")"
    else
      echo "not running"
    fi
    if _is_alive "$WDPIDFILE"; then
      echo "watchdog pid=$(cat "$WDPIDFILE") stall=${STALL_SEC}s"
    else
      echo "watchdog not running"
    fi
    [[ -f logs/heartbeat.json ]] && cat logs/heartbeat.json
    echo "---- status.log (last 15) ----"
    tail -n 15 logs/status.log 2>/dev/null || true
    ;;
  *)
    echo "usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
