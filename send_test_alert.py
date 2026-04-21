import json
import sys
from pathlib import Path
from urllib import request


def main():
    payload_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_payload_lotto.json")
    payload = json.loads(payload_file.read_text())
    payload["signal_id"] = f"{payload.get('signal_id', 'test-signal')}-{int(__import__('time').time())}"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        "http://localhost:8787/webhook/tradingview",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        print(response.status)
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
