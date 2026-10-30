# Pump News Paper Test: run it on your computer

PAPER ONLY. Nothing here holds a wallet or buys anything. Every trade is simulated.

## What you need
- A Mac or Linux computer (on Windows, use WSL)
- Python 3.9 or newer. Check with `python3 --version`; on a Mac, install it from python.org if it's missing.
- No other installs. Everything uses Python's standard library.

## Start it (about 1 minute)
1. Unzip `pump-news-paper.zip`, for example into your home folder.
2. Open Terminal and go into the folder:
   ```bash
   cd ~/pump-news-paper
   chmod +x run.sh src/watchdog.sh
   ```
3. Start the paper bot and its watchdog (they keep running in the background):
   ```bash
   ./run.sh start
   ```
4. Start the dashboard (keep this Terminal window open):
   ```bash
   ./run.sh dashboard
   ```
5. Open http://127.0.0.1:8050 in your browser. The badge turns green ("Live") within about 15 seconds, and the
   page refreshes every 10 seconds.

Want to see the page before the bot has data? Run `./run.sh dashboard --sample` to load the Oct 30 snapshot.

## Everyday commands (run inside the folder)
| Command | What it does |
|---|---|
| `./run.sh start` | Start the bot and watchdog |
| `./run.sh dashboard` | Open the live dashboard at http://127.0.0.1:8050 |
| `./run.sh status` | Show whether the bot is running, plus recent log lines |
| `./run.sh stats` | Print per-rule results in the terminal |
| `./run.sh stop` | Stop the bot and watchdog |

## Things to know
- Keep the computer awake. Sleep pauses the test (it shows as a GAP in the logs). Each rule needs at least
  50 closed trades, which can take hours to days.
- Four rules run side by side. FIRST and LEADER are the original v1 test; FIRST2 and MOMO are v2, the
  "more trades" changes. Each is judged on its own: at least 50 closed trades and net PnL above 0 after the 8% cost.
- Settings are in `config.json` (the v2 settings are under `"v2"`). Changing any number starts a new test version,
  so note the change in `logs/status.log`.
- Logs and state go in `logs/` and `data/state.json`. Delete both to start fresh.

## Continuing with Claude Code locally
Open a terminal in this folder and run `claude`. `CLAUDE.md` holds the full project context, including the hard
rules, strategy details, v2 notes and dashboard docs, so a new session picks up where this one stopped.
