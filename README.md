# GainzAlgo Monster

A fresh TradingView-to-Discord alert system with hard `LOTTO` and `SWING` separation.

## What It Does

- Receives live TradingView webhook alerts
- Keeps `LOTTO` and `SWING` in separate lanes
- Sends each style to its own Discord webhook
- Writes separate JSON state and CSV logs per style
- Shows a simple dashboard in the browser
- Can pull real options contracts and snapshots from Polygon, with Alpaca as fallback
- Shows contract-based paper P&L on the dashboard when live option pricing is available

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
3. Add `POLYGON_API_KEY` if you want Polygon-backed contract data
4. Optionally add Alpaca keys as a fallback source
3. Run:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 app.py
```

4. Open:

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

When a Polygon key is present, Monster uses Polygon's options endpoints first for:

- contract discovery via `/v3/reference/options/contracts`
- option chain snapshots via `/v3/snapshot/options/{underlying}`

That lets the alert show:

- exact contract symbol
- exact expiry
- exact strike
- live contract premium
- max qty based on your configured budget

If Polygon is missing but Alpaca keys are present, Monster falls back to Alpaca.
If neither is configured, Monster falls back to estimated contract info so the app still runs.
