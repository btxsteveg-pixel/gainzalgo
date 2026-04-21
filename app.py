from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs

from monster.config import load_config
from monster.dashboard import render_dashboard
from monster.discord_sender import send_discord_alert
from monster.router import normalize_alert, build_trade_plan
from monster.store import (
    append_alert_log,
    ensure_signal_is_new,
    load_style_state,
    record_webhook_error,
    save_style_state,
    update_open_position_status,
)


config = load_config()


class MonsterHandler(BaseHTTPRequestHandler):
    server_version = "GainzAlgoMonster/1.0"

    def do_HEAD(self):
        if self.path in {"/", "/dashboard"}:
            return self._head_response(200, "text/html; charset=utf-8")
        if self.path == "/health":
            return self._head_response(200, "application/json")
        return self._head_response(404, "application/json")

    def do_GET(self):
        if self.path == "/":
            self.path = "/dashboard"

        if self.path == "/health":
            return self._json(
                200,
                {
                    "ok": True,
                    "styles": list(config["styles"].keys()),
                    "dashboard": "/dashboard",
                },
            )

        if self.path == "/dashboard":
            html = render_dashboard(config)
            encoded = html.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/position/action":
            return self._handle_position_action()
        if self.path != "/webhook/tradingview":
            return self._json(404, {"error": "not_found"})

        payload = None
        try:
            payload = self._read_json()
            alert = normalize_alert(payload, config)
            state = load_style_state(config, alert["trade_style"])
            ensure_signal_is_new(config, alert, state)
            trade_plan = build_trade_plan(alert, config)
            discord_sent = send_discord_alert(config, alert, trade_plan)
            append_alert_log(config, alert, trade_plan, discord_sent, state)
            save_style_state(config, alert["trade_style"], state)
            self._json(
                202,
                {
                    "accepted": True,
                    "style": alert["trade_style"],
                    "discord_sent": discord_sent,
                    "trade_plan": trade_plan,
                },
            )
        except PermissionError as exc:
            self._record_webhook_error(payload, exc)
            self._json(401, {"accepted": False, "error": str(exc)})
        except ValueError as exc:
            self._record_webhook_error(payload, exc)
            self._json(400, {"accepted": False, "error": str(exc)})
        except Exception as exc:
            self._record_webhook_error(payload, exc)
            self._json(500, {"accepted": False, "error": str(exc)})

    def _handle_position_action(self):
        try:
            payload = self._read_form()
            trade_style = str(payload.get("trade_style", "")).strip().upper()
            action = str(payload.get("action", "")).strip().upper()
            if trade_style not in config["styles"]:
                raise ValueError("trade_style must be LOTTO or SWING")
            state = load_style_state(config, trade_style)
            update_open_position_status(state, action)
            save_style_state(config, trade_style, state)
            self.send_response(303)
            self.send_header("Location", "/dashboard")
            self.end_headers()
        except ValueError as exc:
            self._json(400, {"updated": False, "error": str(exc)})
        except Exception as exc:
            self._json(500, {"updated": False, "error": str(exc)})

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            raise ValueError("empty request body")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    def _json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _head_response(self, status, content_type):
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.end_headers()

    def _read_form(self):
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            raise ValueError("empty form body")
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw)
        return {key: values[0] for key, values in parsed.items() if values}

    def _record_webhook_error(self, payload, error):
        if not isinstance(payload, dict):
            return
        trade_style = str(payload.get("trade_style", "")).strip().upper()
        if trade_style:
            record_webhook_error(config, trade_style, error, payload)


def main():
    address = (config["host"], config["port"])
    print(f"GainzAlgo Monster running on http://{config['host']}:{config['port']}")
    print(f"Dashboard: http://localhost:{config['port']}/dashboard")
    ThreadingHTTPServer(address, MonsterHandler).serve_forever()


if __name__ == "__main__":
    main()
