# Stable Hosting

This app is now ready to run on a stable public URL so TradingView does not need a new webhook every time the local quick tunnel dies.

## Best path

Use **Render** or **Railway**.

Both should run:

```text
python app.py
```

The app now supports the hosted `PORT` environment variable automatically.

## Render

1. Push this folder to GitHub.
2. In Render, create a new **Web Service** from that repo.
3. Render can use the included [render.yaml](/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/render.yaml), or use these manual settings:
   - Runtime: `Python`
   - Build command: `pip install -r requirements.txt`
   - Start command: `python app.py`
4. Add these environment variables in Render:
   - `TRADINGVIEW_WEBHOOK_SECRET`
   - `DISCORD_WEBHOOK_URL_LOTTO`
   - `DISCORD_WEBHOOK_URL_SWING`
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `ALPACA_OPTIONS_FEED=opra`
   - `TV_WEBHOOK_HOST=0.0.0.0`
   - `DATA_DIR=/var/data/gainzalgo`
   - `LOTTO_COOLDOWN_SECONDS`
   - `SWING_COOLDOWN_SECONDS`
   - `ALLOWED_SYMBOLS`

5. Add a Render persistent disk mounted at `/var/data`.
   This is what keeps dashboard state and history from resetting on redeploy/restart.

After deploy, Render gives you a stable public base URL like:

```text
https://gainzalgo-monster.onrender.com
```

Your TradingView webhook becomes:

```text
https://gainzalgo-monster.onrender.com/webhook/tradingview
```

## Railway

1. Push this folder to GitHub.
2. Create a new Railway project from the repo.
3. Railway should detect Python because this folder now includes:
   - [requirements.txt](/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/requirements.txt)
   - [Procfile](/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster/Procfile)
4. Add the same environment variables listed above.

After deploy, Railway gives you a stable public base URL. Use:

```text
https://YOUR-RAILWAY-DOMAIN/webhook/tradingview
```

## What changes once hosted

- No more Cloudflare quick tunnel.
- No more changing TradingView webhook every time the tunnel dies.
- Dashboard is reachable on the hosted URL too.
- Your Mac no longer has to stay awake just for TradingView to reach the bot.
