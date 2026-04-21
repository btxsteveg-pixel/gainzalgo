from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SUPPORT_ROOT = Path.home() / "Library/Application Support/GainzAlgoMonster"
RUNTIME_ROOT = APP_SUPPORT_ROOT if (APP_SUPPORT_ROOT / "app.py").exists() else ROOT
LOG_DIR = RUNTIME_ROOT / "desktop_app" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
URL_FILE = RUNTIME_ROOT / "desktop_app" / "tunnel_url.txt"
CLOUDFLARED = RUNTIME_ROOT / "bin" / "cloudflared"
PUBLIC_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
FATAL_MESSAGES = (
    "Unauthorized: Tunnel not found",
    "Register tunnel error from server side",
)


def main() -> int:
    if not CLOUDFLARED.exists():
        raise SystemExit(f"cloudflared not found at {CLOUDFLARED}")

    URL_FILE.write_text("")
    log_file = LOG_DIR / "cloudflared.log"
    command = [
        str(CLOUDFLARED),
        "tunnel",
        "--url",
        "http://localhost:8787",
        "--no-autoupdate",
        "--protocol",
        "http2",
        "--loglevel",
        "info",
    ]

    process = subprocess.Popen(
        command,
        cwd=str(RUNTIME_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    with log_file.open("a", encoding="utf-8") as handle:
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            match = PUBLIC_URL_RE.search(line)
            if match:
                URL_FILE.write_text(match.group(0))
            if any(message in line for message in FATAL_MESSAGES):
                URL_FILE.write_text("")
                process.terminate()
                return 1

    URL_FILE.write_text("")
    return process.wait()


if __name__ == "__main__":
    sys.exit(main())
