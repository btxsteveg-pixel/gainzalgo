# Run Program Guide

This is the simple guide for running GainzAlgo Monster in the future.

## Main Paths

Project folder:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster`

Desktop app:

`/Applications/GainzAlgo Monster.app`

Dashboard:

[http://localhost:8787/dashboard](http://localhost:8787/dashboard)

TradingView webhook endpoint:

`/webhook/tradingview`

## What Each Part Does

- `TradingView` = sends the buy/sell signal
- `GainzAlgo Monster` = receives the alert, formats it, sends Discord, updates dashboard
- `Alpaca` = live options contract and pricing data
- `Discord` = subscriber-facing alerts

## What You Need Turned On

You need all of these:

1. your computer awake
2. internet connected
3. the app/backend running
4. the public tunnel running if TradingView is hitting your local machine

If your Mac sleeps, the webhook will usually stop working.

## Fastest Way To Open It

Use the Mac app:

`/Applications/GainzAlgo Monster.app`

That is the easiest launch point.

## No-Terminal Setup

If you do not want to open Terminal every time, install the Mac background service once:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
./desktop_app/install_launch_agent.sh
```

After that:

1. the backend starts in the background when you log in
2. opening `GainzAlgo Monster.app` just opens the dashboard
3. you do not need to manually run `python3 app.py`

The launch agent file is:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/desktop_app/com.gainzalgo.monster.plist`

## Manual Start Method

If you ever want to run it by hand:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 app.py
```

Then open:

[http://localhost:8787/dashboard](http://localhost:8787/dashboard)

## .env File

Your config file is here:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/.env`

To open it:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
open -a TextEdit .env
```

Important keys in `.env`:

- `TRADINGVIEW_WEBHOOK_SECRET`
- `DISCORD_WEBHOOK_URL_LOTTO`
- `DISCORD_WEBHOOK_URL_SWING`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_OPTIONS_FEED=opra`

## TradingView

Your TradingView alert should:

- use your Pine `alert()` block
- use `Any alert() function call`
- send to the current webhook URL

Your Pine alert block lives in:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/TRADINGVIEW_SETUP.md`

## Test Alerts

To test locally:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 send_test_alert.py sample_payload_lotto.json
python3 send_test_alert.py sample_payload_swing.json
```

## Important Files

Main server:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/app.py`

Dashboard:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/monster/dashboard.py`

Discord sender:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/monster/discord_sender.py`

Options data:

`/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/monster/options_data.py`

State data:

- `/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/data/lotto_state.json`
- `/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/data/swing_state.json`

Logs:

- `/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/data/lotto_alerts.csv`
- `/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/data/swing_alerts.csv`

## If Something Stops Working

### Dashboard won’t load

Run:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 app.py
```

### Discord alerts stop

Check:

- Discord webhook URLs in `.env`
- app is running
- TradingView is still sending alerts

### Contract prices look weird

Remember:

- Alpaca is live now
- fake/manual test payloads can still create weird-looking contract output
- the real test is live market hours with real TradingView alerts

### TradingView alerts do not arrive

Check:

1. app is running
2. Mac is not sleeping
3. tunnel/public webhook path is still alive if using local hosting
4. TradingView alert is still active
5. webhook secret still matches `.env`

## Best Daily Routine

Before market:

1. wake your Mac
2. make sure it will not sleep
3. open `GainzAlgo Monster.app`
4. check dashboard
5. check Discord
6. check TradingView alert is active

After market:

1. review dashboard
2. review closed trades
3. check recap

## Current Reality Check

Right now the system is strongest at:

- receiving TradingView signals
- sending Discord alerts
- showing dashboard state
- using Alpaca for live options data

The real live-market test is still the thing that matters most.
