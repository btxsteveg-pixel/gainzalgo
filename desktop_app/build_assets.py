from __future__ import annotations

import math
import shutil
import struct
import subprocess
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "GainzAlgo Monster"
APP_DIR = ROOT / f"{APP_NAME}.app"
CONTENTS = APP_DIR / "Contents"
MACOS = CONTENTS / "MacOS"
RESOURCES = CONTENTS / "Resources"
ICONSET = ROOT / "GainzAlgoMonster.iconset"
ICON_NAME = "GainzAlgoMonster"
MASTER_ICON = ROOT / f"{ICON_NAME}.png"


def main():
    _reset_dirs()
    _write_launcher()
    _write_plist()
    _build_iconset()
    _build_icns()
    _copy_launcher_py()


def _reset_dirs():
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    if MASTER_ICON.exists():
        MASTER_ICON.unlink()
    MACOS.mkdir(parents=True, exist_ok=True)
    RESOURCES.mkdir(parents=True, exist_ok=True)
    ICONSET.mkdir(parents=True, exist_ok=True)


def _write_launcher():
    script = MACOS / "gainzalgo-monster"
    script.write_text(
        "#!/bin/zsh\n"
        'SCRIPT_DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"\n'
        'exec /usr/bin/python3 "$SCRIPT_DIR/launcher.py"\n'
    )
    script.chmod(0o755)


def _write_plist():
    plist = CONTENTS / "Info.plist"
    plist.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>gainzalgo-monster</string>
  <key>CFBundleIconFile</key>
  <string>GainzAlgoMonster</string>
  <key>CFBundleIdentifier</key>
  <string>com.gainzalgo.monster</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>GainzAlgo Monster</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
"""
    )


def _build_iconset():
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for size in sizes:
        target = ICONSET / f"icon_{size}x{size}.png"
        _write_png(target, size)
        if size == 1024:
            shutil.copy2(target, MASTER_ICON)
        if size < 1024:
            _write_png(ICONSET / f"icon_{size}x{size}@2x.png", size * 2)


def _build_icns():
    icns_path = RESOURCES / f"{ICON_NAME}.icns"
    subprocess.run(["/usr/bin/sips", "-i", str(MASTER_ICON)], check=True)
    temp_rsrc = ROOT / f"{ICON_NAME}.rsrc"
    try:
        with temp_rsrc.open("wb") as handle:
            subprocess.run(["/usr/bin/DeRez", "-only", "icns", str(MASTER_ICON)], check=True, stdout=handle)
        icns_path.touch()
        subprocess.run(["/usr/bin/Rez", "-append", str(temp_rsrc), "-o", str(icns_path)], check=True)
        subprocess.run(["/usr/bin/SetFile", "-a", "C", str(icns_path)], check=True)
    finally:
        if temp_rsrc.exists():
            temp_rsrc.unlink()


def _copy_launcher_py():
    shutil.copy2(ROOT / "launcher.py", RESOURCES / "launcher.py")
    if MASTER_ICON.exists():
        shutil.copy2(MASTER_ICON, RESOURCES / f"{ICON_NAME}.png")


def _write_png(path: Path, size: int):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            r, g, b, a = _pixel(x, y, size)
            raw.extend((r, g, b, a))

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)))
    png.extend(_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
    png.extend(_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _pixel(x: int, y: int, size: int):
    nx = x / (size - 1)
    ny = y / (size - 1)

    # dark background
    r, g, b, a = 12, 12, 18, 255

    # red radial glow
    cx, cy = size * 0.28, size * 0.24
    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    glow = max(0.0, 1.0 - dist / (size * 0.72))
    r = _mix(r, 206, glow * 0.95)
    g = _mix(g, 17, glow * 0.55)
    b = _mix(b, 38, glow * 0.55)

    # rounded card
    margin = size * 0.12
    if _inside_rounded_rect(x, y, margin, margin, size - margin, size - margin, size * 0.16):
        r = _mix(r, 28, 0.5)
        g = _mix(g, 28, 0.5)
        b = _mix(b, 33, 0.5)

    # white G letter
    if _is_g_shape(x, y, size):
        return (245, 245, 247, 255)

    # lower red bar accent
    if y > size * 0.78 and x > size * 0.18 and x < size * 0.82:
        r = _mix(r, 206, 0.85)
        g = _mix(g, 17, 0.3)
        b = _mix(b, 38, 0.3)

    return (r, g, b, a)


def _inside_rounded_rect(x, y, left, top, right, bottom, radius):
    if left + radius <= x <= right - radius or top + radius <= y <= bottom - radius:
        return left <= x <= right and top <= y <= bottom
    corners = [
        (left + radius, top + radius),
        (right - radius, top + radius),
        (left + radius, bottom - radius),
        (right - radius, bottom - radius),
    ]
    return any((x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 for cx, cy in corners)


def _is_g_shape(x: int, y: int, size: int) -> bool:
    cx = size * 0.5
    cy = size * 0.44
    dx = x - cx
    dy = y - cy
    radius = size * 0.21
    thickness = size * 0.07
    dist = math.sqrt(dx * dx + dy * dy)

    ring = radius - thickness <= dist <= radius + thickness
    opening = x > cx + size * 0.08 and y < cy + size * 0.04
    if ring and not opening:
        return True

    bar = (
        cx - size * 0.01 <= x <= cx + size * 0.15
        and cy + size * 0.02 <= y <= cy + size * 0.09
    )
    return bar


def _mix(base: int, target: int, amount: float) -> int:
    amount = max(0.0, min(1.0, amount))
    return int(round(base + (target - base) * amount))


if __name__ == "__main__":
    main()
