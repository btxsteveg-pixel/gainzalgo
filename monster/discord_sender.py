import json
import time
from urllib import request, error


BROWSER_LIKE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def send_discord_alert(config, alert, trade_plan):
    style_config = config["styles"][alert["trade_style"]]
    webhook = style_config["discord_webhook"]
    if not webhook:
        return False
    discord_config = config.get("discord") or {}

    is_buy = alert["side"] == "BUY"
    side_emoji = "🟢" if is_buy else "🔴"
    style_emoji = "🎯" if alert["trade_style"] == "LOTTO" else "📈"
    contract_emoji = "📞" if trade_plan["contract_side"] == "CALL" else "📉"
    direction_label = "BULLISH" if is_buy else "BEARISH"
    contract_label = _fmt_contract_label(trade_plan.get("option_symbol")) if trade_plan.get("option_symbol") else None
    description_bits = [f"{side_emoji} **{direction_label}**  {contract_emoji} **{trade_plan['contract_side']}**"]
    if contract_label and contract_label != "N/A":
        description_bits.append(f"**{contract_label}**")
    if trade_plan.get("entry_type"):
        description_bits.append(f"`{trade_plan['entry_type']}`")

    fields = [
        _field("Current Price", f"{alert['symbol']} {_fmt(alert['price'])}", True),
        _field("Contract", contract_label or "N/A", True),
        _field("Entry Premium", _fmt_money(trade_plan.get("contract_price")), True),
        _field("Expiry", trade_plan.get("target_expiry"), True),
        _field("Underlying TP1", _fmt(trade_plan["tp1"]), True),
        _field("Stop", _fmt(trade_plan["stop"]), True),
        _field("Confidence", f"{_fmt(alert['confidence'])}%", True),
        _field("Data", _fmt_source(trade_plan.get("pricing_source"), trade_plan.get("contract_price_source")), True),
    ]
    if trade_plan.get("tp2") not in (None, ""):
        fields.append(_field("Underlying TP2", _fmt(trade_plan["tp2"]), True))
    if trade_plan.get("delta") not in (None, ""):
        fields.append(_field("Delta", _fmt(trade_plan.get("delta")), True))
    if trade_plan.get("open_interest") not in (None, ""):
        fields.append(_field("Open Interest", _fmt_int(trade_plan.get("open_interest")), True))

    payload = {
        "username": f"GainzAlgo {alert['trade_style']}",
        "embeds": [
            {
                "author": {"name": f"GainzAlgo Monster • {alert['trade_style']} Lane"},
                "title": f"{style_emoji} {alert['trade_style']} | {direction_label} | {alert['symbol']}",
                "description": "\n".join(description_bits),
                "fields": fields,
                "color": 0x00E676 if alert["side"] == "BUY" else 0xFF1744,
                "footer": {"text": _footer_text(alert, trade_plan)},
            }
        ],
    }

    payload["embeds"][0] = {k: v for k, v in payload["embeds"][0].items() if v is not None}

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        webhook,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": BROWSER_LIKE_USER_AGENT,
        },
        method="POST",
    )
    return _post_with_retry(
        req,
        timeout_seconds=float(discord_config.get("timeout_seconds", 6)),
        max_retries=int(discord_config.get("max_retries", 2)),
        retry_backoff_seconds=float(discord_config.get("retry_backoff_seconds", 0.75)),
    )


def _field(name, value, inline):
    if value in (None, ""):
        value = "N/A"
    return {"name": name, "value": str(value)[:1024], "inline": inline}


def _fmt_source(pricing_source, contract_price_source):
    if not pricing_source:
        return "Model Estimate"
    if pricing_source == "polygon":
        return f"Polygon {'Live ' + str(contract_price_source).upper() if contract_price_source else 'Contract Match'}"
    if str(pricing_source).startswith("alpaca"):
        label = str(pricing_source).replace("-", " ").title()
        return f"{label} {str(contract_price_source).upper()}" if contract_price_source else label
    return str(pricing_source).replace("-", " ").title()


def _fmt_contract_label(option_symbol):
    if not option_symbol:
        return "N/A"

    symbol = str(option_symbol)
    if symbol.startswith("O:"):
        symbol = symbol[2:]

    if len(symbol) < 15:
        return symbol

    root = symbol[:-15].strip()
    date_part = symbol[-15:-9]
    side_code = symbol[-9:-8]
    strike_part = symbol[-8:]

    try:
        month = int(date_part[2:4])
        day = int(date_part[4:6])
        side = "Call" if side_code == "C" else "Put" if side_code == "P" else side_code
        strike = int(strike_part) / 1000
        strike_text = str(int(strike)) if float(strike).is_integer() else f"{strike:.1f}".rstrip("0").rstrip(".")
        return f"{root} {strike_text} {side} {month}/{day}"
    except (TypeError, ValueError):
        return symbol


def _footer_text(alert, trade_plan):
    parts = [_fmt_source(trade_plan.get("pricing_source"), trade_plan.get("contract_price_source"))]
    if alert.get("timeframe"):
        parts.append(f"{alert['timeframe']}m" if str(alert["timeframe"]).isdigit() else str(alert["timeframe"]))
    if alert.get("received_at"):
        parts.append(_fmt_timestamp(alert["received_at"]))
    if trade_plan.get("contract_price") in (None, "") and trade_plan.get("option_symbol"):
        parts.append("premium pending data plan")
    return " • ".join(parts)


def _fmt(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_money(value):
    text = _fmt(value)
    return "N/A" if text == "N/A" else f"${text}"


def _fmt_int(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_timestamp(value):
    text = str(value or "")
    if not text:
        return ""
    if "T" in text:
        text = text.replace("T", " ")
    return text[:16]


def _post_with_retry(req, timeout_seconds, max_retries, retry_backoff_seconds):
    attempts = max(max_retries, 0) + 1
    last_error = None
    for attempt in range(attempts):
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                if 200 <= response.status < 300:
                    return True
                last_error = RuntimeError(f"discord webhook returned {response.status}")
        except error.HTTPError as exc:
            last_error = exc
            if 400 <= exc.code < 500 and exc.code != 429:
                break
        except error.URLError as exc:
            last_error = exc

        if attempt < attempts - 1:
            time.sleep(retry_backoff_seconds * (attempt + 1))

    return False
