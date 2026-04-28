# GainzAlgo Monster

A fresh TradingView-to-Discord alert system with hard `LOTTO` and `SWING` separation.

## What It Does

- Receives live TradingView webhook alerts
- Keeps `LOTTO` and `SWING` in separate lanes
- Sends each style to its own Discord webhook
- Writes separate JSON state and CSV logs per style
- Shows a browser dashboard with alert flow, paper-trade results, and lane analytics
- Pulls real options contracts and premiums from Alpaca for LOTTO/SWING contract matching
- Runs paper trading on Alpaca Paper with auto monitoring and end-of-day closes
- Supports an options flow scanner and Discord-posted sector heatmap

## Files

- `app.py` - main server
- `monster/config.py` - environment loading and config
- `monster/router.py` - alert validation and style routing
- `monster/discord_sender.py` - Discord webhook delivery
- `monster/store.py` - state and CSV logging
- `monster/dashboard.py` - simple HTML dashboard

## Quick Start

1. Copy `.env.example` to `.env`
2. Fill in your Discord webhook URLs and webhook secret
3. Add Alpaca API keys for contract matching and paper trading
4. Optionally add Tastytrade credentials for the options flow scanner
5. Run:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 app.py
```

6. Open:

```text
http://localhost:8787/dashboard
```

## Test Without TradingView

With the server running:

```bash
python3 send_test_alert.py sample_payload_lotto.json
python3 send_test_alert.py sample_payload_swing.json
```

That will create:

- `data/lotto_state.json`
- `data/swing_state.json`
- `data/lotto_alerts.csv`
- `data/swing_alerts.csv`

## Anti-Flood Protection

The app blocks:

- duplicate `signal_id` values
- repeated alerts for the same symbol during a cooldown window

Default cooldowns:

- `LOTTO_COOLDOWN_SECONDS=900` (15 minutes)
- `SWING_COOLDOWN_SECONDS=3600` (60 minutes)

## TradingView

Use `alert()` in Pine and include:

- `trade_style` as `LOTTO` or `SWING`
- `secret` matching `TRADINGVIEW_WEBHOOK_SECRET`

See `TRADINGVIEW_SETUP.md`.

## Stable Hosting

If you want a permanent TradingView webhook URL, stop using the local quick tunnel and host the app on Render or Railway.

See [HOSTING.md](/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/HOSTING.md).

## Reliable Contract Data

Monster now uses Alpaca as the live contract-matching path for LOTTO and SWING.

That lets the alert show:

- exact contract symbol
- exact expiry
- exact strike
- live contract premium
- paper-trade sizing from your configured risk budget

If Alpaca is missing or no valid contract is found, the trade plan can fall back to an estimated contract idea internally, but production Discord delivery should be restricted to real matched contracts.

## Extra Modules

- `/flow-scan` runs the Tastytrade unusual-options-flow scanner
- `/heatmap` generates and posts a Discord sector heatmap
- the dashboard includes a paper ledger, execution funnel, and lane analytics
