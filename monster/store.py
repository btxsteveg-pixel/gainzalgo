import csv
import json
from datetime import datetime, timezone

STATUS_SEQUENCE = {"ALERTED": 0, "ENTERED": 1, "TRIMMED": 2, "TP1 HIT": 3}


def load_style_state(config, trade_style):
    path = config["styles"][trade_style]["state_file"]
    if not path.exists():
        return {
            "trade_style": trade_style,
            "last_updated": None,
            "last_webhook_error": None,
            "last_alert": None,
            "recent_alerts": [],
            "signal_ids": [],
            "last_symbol_alerts": {},
            "open_position": None,
            "closed_positions": [],
            "stats": {
                "alerts_received": 0,
                "discord_sent": 0,
                "wins": 0,
                "losses": 0,
            },
        }
    state = json.loads(path.read_text())
    state.setdefault("signal_ids", [])
    state.setdefault("last_symbol_alerts", {})
    state.setdefault("open_position", None)
    state.setdefault("closed_positions", [])
    state.setdefault("last_webhook_error", None)
    if state.get("open_position"):
        state["open_position"].setdefault("status", "ALERTED")
        state["open_position"].setdefault("status_updated_at", state["open_position"].get("opened_at"))
        history = state["open_position"].get("status_history")
        if not history:
            state["open_position"]["status_history"] = [
                {
                    "status": state["open_position"]["status"],
                    "time": state["open_position"]["status_updated_at"],
                }
            ]
    state.setdefault("stats", {
        "alerts_received": 0,
        "discord_sent": 0,
        "wins": 0,
        "losses": 0,
    })
    return state


def save_style_state(config, trade_style, state):
    path = config["styles"][trade_style]["state_file"]
    path.write_text(json.dumps(state, indent=2))


def record_webhook_error(config, trade_style, error_message, payload=None):
    if trade_style not in config["styles"]:
        return
    state = load_style_state(config, trade_style)
    state["last_webhook_error"] = {
        "time": datetime.now(timezone.utc).isoformat(),
        "message": str(error_message),
        "symbol": (payload or {}).get("symbol"),
        "signal_id": (payload or {}).get("signal_id"),
    }
    save_style_state(config, trade_style, state)


def update_open_position_status(state, status):
    open_position = state.get("open_position")
    if not open_position:
        raise ValueError("no open position to update")

    current = open_position.get("status", "ALERTED")
    status = str(status or "").strip().upper().replace("_", " ")
    if status not in {"ENTERED", "TRIMMED", "TP1 HIT", "STOPPED", "CLOSED"}:
        raise ValueError("invalid position action")

    if status in {"STOPPED", "CLOSED"}:
        _close_open_position(state, status)
        return

    next_rank = STATUS_SEQUENCE.get(status, 0)
    current_rank = STATUS_SEQUENCE.get(current, 0)
    if next_rank < current_rank:
        raise ValueError(f"cannot move status backward from {current} to {status}")

    open_position["status"] = status
    open_position["status_updated_at"] = datetime.now(timezone.utc).isoformat()
    history = open_position.setdefault("status_history", [])
    history.append({"status": status, "time": open_position["status_updated_at"]})
    open_position["status_history"] = history[-25:]


def ensure_signal_is_new(config, alert, state):
    signal_ids = state.get("signal_ids", [])
    if alert["signal_id"] in signal_ids:
        raise ValueError(f"duplicate signal_id: {alert['signal_id']}")
    _ensure_cooldown_passed(config, alert, state)


def append_alert_log(config, alert, trade_plan, discord_sent, state):
    event = {
        "time": alert["received_at"],
        "symbol": alert["symbol"],
        "side": alert["side"],
        "trade_style": alert["trade_style"],
        "timeframe": alert["timeframe"],
        "price": alert["price"],
        "confidence": alert["confidence"],
        "take_profit": alert["take_profit"],
        "stop_loss": alert["stop_loss"],
        "signal_id": alert["signal_id"],
        "discord_sent": discord_sent,
        "contract_side": trade_plan["contract_side"],
        "status": (state.get("open_position") or {}).get("status"),
        "option_symbol": trade_plan.get("option_symbol"),
        "contract_price": trade_plan.get("contract_price"),
        "contract_cost": trade_plan.get("contract_cost"),
        "pricing_source": trade_plan.get("pricing_source"),
        "dte_window": trade_plan["dte_window"],
        "target_expiry": trade_plan.get("target_expiry"),
        "suggested_strike": trade_plan["suggested_strike"],
        "risk_budget": trade_plan["risk_budget"],
        "risk_per_share": trade_plan["risk_per_share"],
        "suggested_shares": trade_plan["suggested_shares"],
        "suggested_contracts": trade_plan.get("max_contracts"),
        "reward_to_risk": trade_plan["reward_to_risk"],
        "tp1": trade_plan["tp1"],
        "tp2": trade_plan["tp2"],
        "stop": trade_plan["stop"],
    }

    stats = state["stats"]
    stats["alerts_received"] += 1
    if discord_sent:
        stats["discord_sent"] += 1

    signal_ids = (state.get("signal_ids", []) + [alert["signal_id"]])[-config["max_signal_ids"] :]
    state["signal_ids"] = signal_ids
    state["last_symbol_alerts"][alert["symbol"]] = alert["received_at"]
    state["last_updated"] = alert["received_at"]
    state["last_webhook_error"] = None
    state["last_alert"] = event
    state["recent_alerts"] = (state.get("recent_alerts", []) + [event])[-config["max_recent_alerts"] :]
    _update_paper_position(state, event)

    log_path = config["styles"][alert["trade_style"]]["trade_log"]
    file_exists = log_path.exists()
    with log_path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(event.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(event)


def load_all_states(config):
    return {style: load_style_state(config, style) for style in config["styles"]}


def _update_paper_position(state, event):
    open_position = state.get("open_position")
    if open_position and open_position.get("symbol") == event["symbol"] and open_position.get("side") != event["side"]:
        closed = dict(open_position)
        closed["closed_at"] = event["time"]
        closed["close_price"] = event["price"]
        closed["close_contract_price"] = event.get("contract_price")
        closed["close_signal"] = event["signal_id"]
        closed["close_reason"] = "OPPOSITE SIGNAL"
        closed["pnl"] = _paper_pnl(open_position, event["price"])
        closed["option_pnl"] = _option_pnl(open_position, event.get("contract_price"))
        state["closed_positions"] = (state.get("closed_positions", []) + [closed])[-100:]
        decision_pnl = closed["option_pnl"] if closed["option_pnl"] is not None else closed["pnl"]
        if decision_pnl is not None:
            if decision_pnl > 0:
                state["stats"]["wins"] += 1
            else:
                state["stats"]["losses"] += 1
        open_position = None

    if open_position is None:
        state["open_position"] = {
            "symbol": event["symbol"],
            "side": event["side"],
            "opened_at": event["time"],
            "entry_price": event["price"],
            "current_underlying_price": event["price"],
            "entry_contract_price": event.get("contract_price"),
            "option_symbol": event.get("option_symbol"),
            "contracts": event.get("suggested_contracts"),
            "pricing_source": event.get("pricing_source"),
            "contract_side": event.get("contract_side"),
            "target_expiry": event.get("target_expiry"),
            "suggested_strike": event.get("suggested_strike"),
            "signal_id": event["signal_id"],
            "stop": event["stop"],
            "tp1": event["tp1"],
            "tp2": event["tp2"],
            "status": "ALERTED",
            "status_updated_at": event["time"],
            "status_history": [{"status": "ALERTED", "time": event["time"]}],
        }
    else:
        open_position["current_underlying_price"] = event["price"]
        state["open_position"] = open_position


def _paper_pnl(open_position, close_price):
    entry = open_position.get("entry_price")
    if entry is None or close_price is None:
        return None
    if open_position.get("side") == "BUY":
        return round(close_price - entry, 4)
    return round(entry - close_price, 4)


def _option_pnl(open_position, close_contract_price):
    entry_price = open_position.get("entry_contract_price")
    contracts = open_position.get("contracts")
    if entry_price in (None, "") or close_contract_price in (None, "") or contracts in (None, ""):
        return None
    try:
        return round((float(close_contract_price) - float(entry_price)) * 100 * int(contracts), 2)
    except (TypeError, ValueError):
        return None


def _close_open_position(state, reason):
    open_position = state.get("open_position")
    if not open_position:
        raise ValueError("no open position to close")

    now = datetime.now(timezone.utc).isoformat()
    closed = dict(open_position)
    closed["closed_at"] = now
    closed["close_reason"] = reason
    closed["close_price"] = open_position.get("current_underlying_price", open_position.get("entry_price"))
    closed["close_contract_price"] = open_position.get("current_contract_price")
    closed["pnl"] = _paper_pnl(open_position, closed.get("close_price"))
    closed["option_pnl"] = _option_pnl(open_position, closed.get("close_contract_price"))
    state["closed_positions"] = (state.get("closed_positions", []) + [closed])[-100:]

    decision_pnl = closed["option_pnl"] if closed["option_pnl"] is not None else closed["pnl"]
    if decision_pnl is not None:
        if decision_pnl > 0:
            state["stats"]["wins"] += 1
        else:
            state["stats"]["losses"] += 1

    state["open_position"] = None


def _ensure_cooldown_passed(config, alert, state):
    cooldown = config["styles"][alert["trade_style"]].get("cooldown_seconds", 0)
    if cooldown <= 0:
        return

    last_alert_time = (state.get("last_symbol_alerts") or {}).get(alert["symbol"])
    if not last_alert_time:
        return

    previous = _parse_iso(last_alert_time)
    current = _parse_iso(alert["received_at"])
    if previous is None or current is None:
        return

    elapsed = (current - previous).total_seconds()
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        raise ValueError(
            f"cooldown active for {alert['symbol']} in {alert['trade_style']} ({remaining}s remaining)"
        )


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
