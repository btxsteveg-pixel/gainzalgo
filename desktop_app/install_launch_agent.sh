#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster"
PLIST_SOURCE="$PROJECT_ROOT/desktop_app/com.gainzalgo.monster.plist"
PLIST_TARGET="$HOME/Library/LaunchAgents/com.gainzalgo.monster.plist"
TUNNEL_PLIST_SOURCE="$PROJECT_ROOT/desktop_app/com.gainzalgo.monster.tunnel.plist"
TUNNEL_PLIST_TARGET="$HOME/Library/LaunchAgents/com.gainzalgo.monster.tunnel.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_ROOT/desktop_app/logs"

cp "$PLIST_SOURCE" "$PLIST_TARGET"
cp "$TUNNEL_PLIST_SOURCE" "$TUNNEL_PLIST_TARGET"
launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)" "$TUNNEL_PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
launchctl bootstrap "gui/$(id -u)" "$TUNNEL_PLIST_TARGET"
launchctl enable "gui/$(id -u)/com.gainzalgo.monster"
launchctl enable "gui/$(id -u)/com.gainzalgo.monster.tunnel"
launchctl kickstart -k "gui/$(id -u)/com.gainzalgo.monster"
launchctl kickstart -k "gui/$(id -u)/com.gainzalgo.monster.tunnel"

echo "Installed and started com.gainzalgo.monster and com.gainzalgo.monster.tunnel"
