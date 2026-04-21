from datetime import datetime, timedelta, timezone

from monster.options_data import enrich_trade_plan_with_option_data


VALID_SIDES = {"BUY", "SELL"}
VALID_STYLES = {"LOTTO", "SWING"}


def normalize_alert(payload, config):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    secret = str(payload.get("secret", "")).strip()
    if not config["secret"]:
        raise PermissionError("TRADINGVIEW_WEBHOOK_SECRET is missing from .env")
    if secret != config["secret"]:
        raise PermissionError("invalid webhook secret")

    trade_style = str(payload.get("trade_style", "LOTTO")).strip().upper()
    if trade_style not in VALID_STYLES:
        raise ValueError("trade_style must be LOTTO or SWING")

    side = str(payload.get("side") or payload.get("signal") or "").strip().upper()
    if side in {"LONG", "CALL", "BULLISH"}:
        side = "BUY"
    elif side in {"SHORT", "PUT", "BEARISH"}:
        side = "SELL"
    if side not in VALID_SIDES:
        raise ValueError("side must be BUY or SELL")

    symbol = str(payload.get("symbol") or payload.get("ticker") or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if config["allowed_symbols"] and symbol not in config["allowed_symbols"]:
        raise ValueError(f"{symbol} is not allowed by ALLOWED_SYMBOLS")

    confidence = _to_float(payload.get("confidence"), 100.0)
    if confidence < config["styles"][trade_style]["min_confidence"]:
        raise ValueError(
            f"{trade_style} confidence must be at least {config['styles'][trade_style]['min_confidence']}"
        )

    received_at = datetime.now(timezone.utc).isoformat()

    return {
        "secret": secret,
        "trade_style": trade_style,
        "symbol": symbol,
        "side": side,
        "signal_id": str(
            payload.get("signal_id")
            or payload.get("signalId")
            or f"{symbol}-{trade_style}-{side}-{int(datetime.now(timezone.utc).timestamp())}"
        ),
        "timeframe": str(payload.get("timeframe") or payload.get("interval") or ""),
        "price": _to_float(payload.get("price")),
        "confidence": confidence,
        "take_profit": _to_float(payload.get("take_profit", payload.get("tp"))),
        "stop_loss": _to_float(payload.get("stop_loss", payload.get("sl"))),
        "message": str(payload.get("message") or payload.get("notes") or "").strip(),
        "received_at": received_at,
    }


def build_trade_plan(alert, config):
    style = config["styles"][alert["trade_style"]]
    price = alert["price"]
    strike_hint = round(price) if price is not None else None
    stop = alert["stop_loss"]
    target_1 = alert["take_profit"]
    target_2 = None
    if price is not None and target_1 is None:
        target_2 = round(price * (1.015 if alert["trade_style"] == "LOTTO" else 1.03), 4)
    risk_per_share = _risk_per_share(price, stop)
    risk_budget = round(config["paper_account_size"] * (style["risk_pct"] / 100.0), 2)
    suggested_shares = _suggested_shares(risk_budget, risk_per_share)
    reward_to_risk = _reward_to_risk(price, target_1, stop, alert["side"])
    target_expiry = _target_expiry(alert["received_at"], style["dte_min"], style["dte_max"])
    trade_plan = {
        "style": alert["trade_style"],
        "contract_side": "CALL" if alert["side"] == "BUY" else "PUT",
        "dte_window": f"{style['dte_min']}-{style['dte_max']} days",
        "target_expiry": target_expiry,
        "entry_type": "fast momentum entry" if alert["trade_style"] == "LOTTO" else "trend confirmation entry",
        "suggested_strike": strike_hint,
        "risk_budget": risk_budget,
        "risk_per_share": risk_per_share,
        "suggested_shares": suggested_shares,
        "reward_to_risk": reward_to_risk,
        "tp1": target_1,
        "tp2": target_2,
        "stop": stop,
    }
    return enrich_trade_plan_with_option_data(config, alert, trade_plan)


def _to_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid number: {value}")


def _risk_per_share(price, stop):
    if price is None or stop is None:
        return None
    gap = abs(price - stop)
    return round(gap, 4) if gap > 0 else None


def _suggested_shares(risk_budget, risk_per_share):
    if risk_per_share in (None, 0):
        return None
    return max(int(risk_budget // risk_per_share), 1)


def _reward_to_risk(price, target, stop, side):
    if price is None or target is None or stop is None:
        return None
    risk = abs(price - stop)
    if risk == 0:
        return None
    reward = (target - price) if side == "BUY" else (price - target)
    return round(reward / risk, 2)


def _target_expiry(received_at, dte_min, dte_max):
    try:
        base = datetime.fromisoformat(received_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)

    target_days = dte_min if dte_min == dte_max else int(round((dte_min + dte_max) / 2))
    candidate = base + timedelta(days=target_days)

    # Options most commonly expire on Friday; roll forward to the next Friday
    days_to_friday = (4 - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=days_to_friday)
    return candidate.date().isoformat()
