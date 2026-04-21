## GainzAlgo Monster Desktop App

This folder contains a lightweight macOS app launcher for GainzAlgo Monster.

What it does:

- gives you a real `.app` bundle with an icon
- starts the local Python backend if it is not already running
- opens the dashboard in your browser

Main paths:

- `GainzAlgo Monster.app` - the clickable macOS app
- `build_assets.py` - rebuilds the icon and app bundle assets

If you want to rebuild the icon/app assets:

```bash
cd /Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster
python3 desktop_app/build_assets.py
```
