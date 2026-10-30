#!/usr/bin/env bash
# PAPER ONLY news-driven pump.fun test. start|stop|status|stats|dashboard [--sample]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"; mkdir -p logs data
alive(){ [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }
case "${1:-status}" in
  start)
    rm -f logs/stopped
    if alive logs/bot.pid; then echo "bot already running pid=$(cat logs/bot.pid)"; else
      nohup python3 -u "$ROOT/src/newsbot.py" >> logs/bot.out 2>&1 & echo $! > logs/bot.pid; echo "bot started pid=$(cat logs/bot.pid)"; fi
    if alive logs/watchdog.pid; then echo "watchdog already running pid=$(cat logs/watchdog.pid)"; else
      nohup bash "$ROOT/src/watchdog.sh" >> logs/watchdog.out 2>&1 & echo $! > logs/watchdog.pid; echo "watchdog started pid=$(cat logs/watchdog.pid)"; fi ;;
  stop)
    touch logs/stopped
    for f in logs/watchdog.pid logs/bot.pid; do
      if alive "$f"; then p=$(cat "$f"); kill "$p"; sleep 1; kill -9 "$p" 2>/dev/null; echo "stopped $f $p"; fi; rm -f "$f"; done
    pkill -f "$ROOT/src/watchdog.sh" 2>/dev/null; pkill -f "$ROOT/src/newsbot.py" 2>/dev/null; echo "$(date '+%Y-%m-%dT%H:%M:%S%z') STOP via run.sh" >> logs/status.log ;;
  status)
    alive logs/bot.pid && echo "bot running pid=$(cat logs/bot.pid)" || echo "bot NOT running"
    alive logs/watchdog.pid && echo "watchdog running pid=$(cat logs/watchdog.pid)" || echo "watchdog NOT running"
    [[ -f logs/heartbeat.json ]] && { echo "heartbeat age=$(python3 -c 'import os,time;print(int(time.time()-os.path.getmtime("logs/heartbeat.json")))')s"; cat logs/heartbeat.json; echo; }
    echo "---- status.log tail ----"; tail -n 15 logs/status.log ;;
  stats) python3 src/stats.py ;;
  dashboard) shift; exec python3 "$ROOT/dashboard.py" "$@" ;;
  *) echo "usage: $0 start|stop|status|stats|dashboard [--sample]"; exit 1 ;;
esac
