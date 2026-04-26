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

    # FIX: default was 100.0 — any payload missing confidence silently passed every gate.
    # Default to 0 so missing confidence is always rejected, not auto-approved.
    confidence = _to_float(payload.get("confidence"), 0.0)
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
        # Pine v4.1 enrichment fields — passed through so options_data.py can use them
        # for smarter strike anchoring, delta-aware selection, and routing validation.
        "delta_target": str(payload.get("delta_target") or "").strip(),
        "tfs_aligned": _to_int(payload.get("tfs_aligned")),
        "atr": _to_float(payload.get("atr")),
        "bounce_off": _to_float(payload.get("bounce_off")),
        "nearest_resistance": _to_float(payload.get("nearest_resistance")),
        "nearest_support": _to_float(payload.get("nearest_support")),
    }


def build_trade_plan(alert, config):
    style = config["styles"][alert["trade_style"]]
    price = alert["price"]
    strike_hint = _suggested_strike_hint(alert["trade_style"], alert["side"], price)
    stop = alert["stop_loss"]
    target_1 = alert["take_profit"]
    if price is not None and target_1 is None:
        target_1 = _default_target(price, alert["side"], alert["trade_style"], target_number=1)
    target_2 = _default_target(price, alert["side"], alert["trade_style"], target_number=2) if price is not None else None
    risk_per_share = _risk_per_share(price, stop)
    risk_budget = round(config["paper_account_size"] * (style["risk_pct"] / 100.0), 2)
    suggested_shares = _suggested_shares(risk_budget, risk_per_share)
    reward_to_risk = _reward_to_risk(price, target_1, stop, alert["side"])
    target_expiry = _target_expiry(alert["received_at"], style["dte_min"], style["dte_max"], alert["trade_style"])
    is_swing = alert["trade_style"] == "SWING"
    trade_plan = {
        "style": alert["trade_style"],
        "contract_side": "CALL" if alert["side"] == "BUY" else "PUT",
        "dte_window": f"{style['dte_min']}-{style['dte_max']} days",
        "target_expiry": target_expiry,
        "entry_type": "fast momentum entry" if alert["trade_style"] == "LOTTO" else "trend-following swing entry",
        "suggested_strike": strike_hint,
        "risk_budget": risk_budget,
        "risk_per_share": risk_per_share,
        "suggested_shares": suggested_shares,
        "reward_to_risk": reward_to_risk,
        "tp1": target_1,
        "tp2": target_2,
        "stop": stop,
        "hold_window": "same day to 1 day" if not is_swing else f"1-{style['hold_days_max']} days",
        "exit_policy": "take profit or hard stop" if not is_swing else "scale at TP1, trail remainder, exit before Friday expiry",
        "trailing_stop_enabled": bool(style.get("trailing_stop_enabled")) if is_swing else False,
        "trailing_stop_pct": style.get("trailing_stop_pct") if is_swing else None,
        "contract_profile": "2-5 OTM weekly" if not is_swing else "slightly OTM swing contract",
    }
    return enrich_trade_plan_with_option_data(config, alert, trade_plan)


def _suggested_strike_hint(trade_style, side, price):
    if price is None:
        return None
    if trade_style == "LOTTO":
        if side == "BUY":
            return round(price + 3.5)
        if side == "SELL":
            return max(round(price - 3.5), 0)
    swing_offset = max(0.5, price * 0.0075)
    if side == "BUY":
        return round(price + swing_offset, 2)
    if side == "SELL":
        return max(round(price - swing_offset, 2), 0)
    return round(price, 2)


def _to_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid number: {value}")


def _to_int(value, default=None):
    """Safe int coercion — never raises, returns default on bad input."""
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def _target_expiry(received_at, dte_min, dte_max, trade_style="LOTTO"):
    try:
        base = datetime.fromisoformat(received_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)

    normalized_style = str(trade_style or "").upper()
    if normalized_style == "LOTTO":
        return _lotto_weekly_expiry(base.date()).isoformat()
    if normalized_style == "SWING":
        return _swing_weekly_expiry(base.date(), dte_min, dte_max).isoformat()

    target_days = dte_min if dte_min == dte_max else int(round((dte_min + dte_max) / 2))
    candidate = base + timedelta(days=target_days)

    # Options most commonly expire on Friday; roll forward to the next Friday
    days_to_friday = (4 - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=days_to_friday)
    return candidate.date().isoformat()


def _lotto_weekly_expiry(base_date):
    weekday = base_date.weekday()
    days_to_friday = (4 - weekday) % 7

    # Early week: aim for the current weekly. Late week: roll to next Friday to reduce theta crush.
    if weekday >= 3:
        days_to_friday += 7

    return base_date + timedelta(days=days_to_friday)


def _swing_weekly_expiry(base_date, dte_min, dte_max):
    days_to_friday = (4 - base_date.weekday()) % 7
    current_friday = base_date + timedelta(days=days_to_friday)
    current_dte = (current_friday - base_date).days
    if dte_min <= current_dte <= dte_max:
        return current_friday
    if current_dte < dte_min:
        return current_friday + timedelta(days=7)
    return current_friday


def _default_target(price, side, trade_style, target_number):
    if price is None:
        return None

    if trade_style == "LOTTO":
        move = 0.015 if target_number == 1 else 0.025
    else:
        move = 0.025 if target_number == 1 else 0.04

    if side == "BUY":
        return round(price * (1 + move), 4)
    return round(price * (1 - move), 4)
