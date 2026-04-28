from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse

from monster.config import load_config
from monster.dashboard import render_dashboard
from monster.discord_sender import send_discord_alert
from monster.router import normalize_alert, build_trade_plan
from monster.store import (
    append_alert_log,
    ensure_signal_is_new,
    load_style_state,
    record_webhook_error,
    reserve_signal,
    save_style_state,
    update_open_position_status,
)


config = load_config()
STATE_LOCK = threading.Lock()


def _health_payload(request_base_url=None):
    styles = config.get("styles") or {}
    alpaca = config.get("alpaca") or {}
    flow = config.get("flow") or {}
    heatmap = config.get("heatmap") or {}
    public_base = request_base_url or config.get("public_base_url") or ""
    webhook_url = f"{public_base.rstrip('/')}/webhook/tradingview" if public_base else None
    return {
        "ok": True,
        "styles": list(styles.keys()),
        "dashboard": "/dashboard",
        "paper_trading_enabled": bool(config.get("paper_trading_enabled", True)),
        "modules": {
            "discord_alerts": {
                "ready": bool(styles.get("LOTTO", {}).get("discord_webhook") and styles.get("SWING", {}).get("discord_webhook"))
            },
            "alpaca": {
                "ready": bool(alpaca.get("api_key") and alpaca.get("secret_key")),
                "options_feed": alpaca.get("options_feed"),
                "trading_base_url": alpaca.get("trading_base_url"),
            },
            "options_flow": {
                "enabled": bool(flow.get("enabled", True)),
                "ready": bool(
                    flow.get("enabled", True)
                    and flow.get("tastytrade_username")
                    and flow.get("tastytrade_password")
                    and flow.get("bull_webhook")
                    and flow.get("bear_webhook")
                ),
            },
            "heatmap": {
                "enabled": bool(heatmap.get("enabled", True)),
                "ready": bool(heatmap.get("enabled", True) and heatmap.get("discord_webhook")),
            },
        },
        "webhook_url": webhook_url,
    }


def _run_heatmap_async():
    """Background thread target for /heatmap endpoint."""
    try:
        from monster.market_heatmap import post_market_heatmap
        import logging
        logging.getLogger(__name__).info("Market heatmap generation started")
        success = post_market_heatmap()
        logging.getLogger(__name__).info("Market heatmap %s", "posted" if success else "failed")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f"Market heatmap error: {exc}")


def _run_flow_scan_async():
    """Background thread target for /flow-scan endpoint."""
    try:
        from monster.options_flow import run_flow_scan
        import logging
        logging.getLogger(__name__).info("Options flow scan started")
        results = run_flow_scan()
        logging.getLogger(__name__).info(f"Options flow scan complete — {len(results)} alerts posted")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f"Options flow scan error: {exc}")


def _process_alert_async(alert):
    try:
        trade_plan = build_trade_plan(alert, config)
        discord_sent = send_discord_alert(config, alert, trade_plan)

        # Paper execution — fires after Discord so a Discord failure never
        # blocks the paper order, and a paper failure never blocks Discord.
        if config.get("paper_trading_enabled", True):
            try:
                from monster.paper_trader import execute_paper_trade
                execute_paper_trade(config, alert, trade_plan)
            except Exception as paper_exc:
                import logging
                logging.getLogger(__name__).error(f"Paper trade error: {paper_exc}")

        with STATE_LOCK:
            state = load_style_state(config, alert["trade_style"])
            append_alert_log(config, alert, trade_plan, discord_sent, state)
            save_style_state(config, alert["trade_style"], state)
    except Exception as exc:
        record_webhook_error(config, alert["trade_style"], exc, alert)


class MonsterHandler(BaseHTTPRequestHandler):
    server_version = "GainzAlgoMonster/1.0"

    def _route_path(self):
        raw_path = str(self.path or "/")
        parsed = urlparse(raw_path)
        route_path = parsed.path or raw_path.split("?", 1)[0]
        # Some proxies/clients may send an absolute-form URI or host-prefixed path.
        # Normalize to the slash-prefixed route segment so route matching is stable.
        if route_path and not route_path.startswith("/"):
            slash_at = route_path.find("/")
            route_path = route_path[slash_at:] if slash_at >= 0 else f"/{route_path}"
        return route_path or "/"

    def do_HEAD(self):
        route_path = self._route_path()
        if route_path in {"/", "/dashboard"}:
            return self._head_response(200, "text/html; charset=utf-8")
        if route_path == "/health":
            return self._head_response(200, "application/json")
        if route_path == "/flow-scan":
            return self._head_response(200, "application/json")
        return self._head_response(404, "application/json")

    def do_GET(self):
        route_path = self._route_path()
        if route_path == "/":
            self.path = "/dashboard"
            route_path = "/dashboard"

        # ── Options Flow Scan ──────────────────────────────────────────────────
        # Trigger: GET /flow-scan?secret=<FLOW_SCAN_SECRET>
        # Returns 202 immediately, runs scan in background thread.
        # Set up UptimeRobot or cron to hit this every 5-10 min during market hours.
        if route_path == "/flow-scan":
            return self._handle_flow_scan()

        if route_path == "/heatmap":
            return self._handle_heatmap()

        if route_path == "/health":
            return self._json(200, _health_payload(self._public_base_url()))

        if route_path == "/dashboard":
            html = render_dashboard(config, self._public_base_url())
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
            with STATE_LOCK:
                state = load_style_state(config, alert["trade_style"])
                ensure_signal_is_new(config, alert, state)
                reserve_signal(config, alert, state)
                save_style_state(config, alert["trade_style"], state)
            self._json(
                202,
                {
                    "accepted": True,
                    "style": alert["trade_style"],
                    "queued": True,
                },
            )
            worker = threading.Thread(target=_process_alert_async, args=(alert,), daemon=True)
            worker.start()
        except PermissionError as exc:
            self._record_webhook_error(payload, exc)
            self._json(401, {"accepted": False, "error": str(exc)})
        except ValueError as exc:
            self._record_webhook_error(payload, exc)
            self._json(400, {"accepted": False, "error": str(exc)})
        except Exception as exc:
            self._record_webhook_error(payload, exc)
            self._json(500, {"accepted": False, "error": str(exc)})

    def _handle_flow_scan(self):
        flow_cfg = config.get("flow", {})

        scan_secret = flow_cfg.get("scan_secret", "")
        if scan_secret:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            provided = qs.get("secret", [""])[0]
            if provided != scan_secret:
                return self._json(401, {"error": "invalid scan secret"})

        if not flow_cfg.get("enabled", True):
            return self._json(200, {"ok": False, "reason": "flow scanner disabled"})

        from monster.options_flow import WATCHLIST

        self._json(202, {"accepted": True, "scanning": True, "symbols": len(WATCHLIST)})
        worker = threading.Thread(target=_run_flow_scan_async, daemon=True)
        worker.start()

    def _handle_heatmap(self):
        """
        GET /heatmap?secret=<HEATMAP_SECRET>
        Returns 202 immediately and generates + posts the heatmap in a background thread.
        Schedule with UptimeRobot at 9:35 AM EST Mon-Fri for daily open snapshot.
        """
        heatmap_cfg = config.get("heatmap", {})
        secret = heatmap_cfg.get("secret", "")
        if secret:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            provided = qs.get("secret", [""])[0]
            if provided != secret:
                return self._json(401, {"error": "invalid heatmap secret"})

        if not heatmap_cfg.get("enabled", True):
            return self._json(200, {"ok": False, "reason": "heatmap disabled (HEATMAP_ENABLED=false)"})

        self._json(202, {"accepted": True, "generating": True})
        worker = threading.Thread(target=_run_heatmap_async, daemon=True)
        worker.start()

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

    def _public_base_url(self):
        configured = str(config.get("public_base_url") or "").strip()
        if configured:
            return configured.rstrip("/")
        proto = self.headers.get("x-forwarded-proto", "http")
        host = self.headers.get("x-forwarded-host") or self.headers.get("host")
        if not host:
            return None
        return f"{proto}://{host}"


def main():
    # Start paper trading monitor if enabled
    if config.get("paper_trading_enabled", True):
        try:
            from monster.paper_trader import ensure_monitor_running
            ensure_monitor_running(config)
            print("Paper trading monitor started")
        except Exception as exc:
            print(f"Paper monitor startup warning: {exc}")

    address = (config["host"], config["port"])
    print(f"GainzAlgo Monster running on http://{config['host']}:{config['port']}")
    print(f"Dashboard: http://localhost:{config['port']}/dashboard")
    ThreadingHTTPServer(address, MonsterHandler).serve_forever()


if __name__ == "__main__":
    main()
