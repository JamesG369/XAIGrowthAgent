#!/usr/bin/env python3
"""Local read-only live dashboard for the PAPER test. Stdlib only.
Usage: python3 dashboard.py [--port 8050] [--sample] [--logs DIR --state FILE]  ->  http://127.0.0.1:8050
Serves dashboard.html and /data (the JSON from tracker_data.py). Binds to 127.0.0.1 only and exposes no
write endpoints: the dashboard can never start, stop, or place trades."""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
def _arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else default
PORT = int(_arg("--port", os.environ.get("DASHBOARD_PORT", "8050")))
TRACKER = [sys.executable, os.path.join(HERE, "tracker_data.py")]
if "--sample" in sys.argv:
    TRACKER += ["--logs", os.path.join(HERE, "sample_logs"), "--state", os.path.join(HERE, "sample_logs", "state.json")]
for flag in ("--logs", "--state"):
    if flag in sys.argv and "--sample" not in sys.argv: TRACKER += [flag, _arg(flag, "")]

# Several open tabs share one tracker run per 3 s instead of each spawning their own.
_cache, _lock = {"t": 0.0, "body": b""}, threading.Lock()
def tracker_json():
    with _lock:
        if time.time() - _cache["t"] < 3 and _cache["body"]: return _cache["body"]
        out = subprocess.run(TRACKER, capture_output=True, text=True, timeout=20, cwd=HERE)
        if out.returncode != 0: raise RuntimeError((out.stderr or "tracker_data.py failed").strip().splitlines()[-1])
        data = json.loads(out.stdout)
        data["sample"] = "--sample" in sys.argv
        _cache.update(t=time.time(), body=json.dumps(data, ensure_ascii=False).encode())
        return _cache["body"]

class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.send(200, open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html; charset=utf-8")
        elif path == "/data":
            try: self.send(200, tracker_json(), "application/json")
            except Exception as e: self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
        else:
            self.send(404, b"not found", "text/plain")
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"dashboard on http://127.0.0.1:{PORT}  ({'SAMPLE logs' if '--sample' in sys.argv else 'live logs'}; Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
