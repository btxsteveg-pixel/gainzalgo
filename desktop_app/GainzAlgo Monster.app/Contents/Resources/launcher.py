from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_ROOT_HINT = Path.home() / "Library/Application Support/GainzAlgoMonster"
SOURCE_ROOT_HINT = Path(
    "/Users/stevengonzalez/Documents/Codex/2026-04-20-fix-my-codes-and-make-them/gainzalgo_monster"
)
HEALTH_URL = "http://localhost:8787/health"
DASHBOARD_URL = "http://localhost:8787/dashboard"
ROOT = None
APP_FILE = None
LOG_DIR = None


def _resolve_project_root() -> Path:
    env_root = os.environ.get("GAINZALGO_MONSTER_ROOT", "").strip()
    candidates = []
    if env_root:
        candidates.append(Path(env_root).expanduser())

    resources_dir = Path(__file__).resolve().parent
    candidates.extend(
        [
            PROJECT_ROOT_HINT,
            SOURCE_ROOT_HINT,
            resources_dir.parents[1],
            resources_dir.parents[2] if len(resources_dir.parents) > 2 else None,
        ]
    )

    for candidate in candidates:
        if candidate and (candidate / "app.py").exists() and (candidate / "monster").is_dir():
            return candidate
    raise RuntimeError("Could not find GainzAlgo Monster project root.")


ROOT = _resolve_project_root()
APP_FILE = ROOT / "app.py"
LOG_DIR = ROOT / "desktop_app" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def main():
    if not _server_is_healthy():
        _start_server()
        _wait_for_server()
    if _server_is_healthy():
        webbrowser.open(DASHBOARD_URL, new=1)
    else:
        raise RuntimeError("GainzAlgo Monster server did not become healthy in time.")


def _server_is_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


def _start_server() -> None:
    log_path = LOG_DIR / "desktop_app.log"
    handle = log_path.open("ab")
    subprocess.Popen(
        [sys.executable, str(APP_FILE)],
        cwd=str(ROOT),
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )


def _wait_for_server() -> None:
    deadline = time.time() + 12
    while time.time() < deadline:
        if _server_is_healthy():
            return
        time.sleep(0.4)


if __name__ == "__main__":
    main()
