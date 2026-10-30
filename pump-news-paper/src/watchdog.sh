#!/usr/bin/env bash
# Restarts newsbot if dead or heartbeat older than STALL seconds.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
STALL=$(python3 -c 'import json;print(json.load(open("config.json")).get("watchdog_stall_sec",180))')
echo "$(date '+%Y-%m-%dT%H:%M:%S%z') watchdog start pid=$$ stall=${STALL}s" >> logs/watchdog.out
start_bot(){ nohup python3 -u "$ROOT/src/newsbot.py" >> logs/bot.out 2>&1 & echo $! > logs/bot.pid; echo "$(date '+%Y-%m-%dT%H:%M:%S%z') WATCHDOG started bot pid=$(cat logs/bot.pid) ($1)" >> logs/status.log; }
while true; do
  sleep 30
  [[ -f logs/stopped ]] && exit 0
  if [[ ! -f logs/bot.pid ]] || ! kill -0 "$(cat logs/bot.pid)" 2>/dev/null; then start_bot "bot dead"; sleep 20; continue; fi
  if [[ -f logs/heartbeat.json ]]; then
    age=$(python3 -c 'import os,time;print(int(time.time()-os.path.getmtime("logs/heartbeat.json")))')
    if (( age > STALL )); then
      old=$(cat logs/bot.pid); kill "$old" 2>/dev/null; sleep 2; kill -9 "$old" 2>/dev/null
      start_bot "stall heartbeat_age=${age}s killed=$old"; sleep 20
    fi
  fi
done
