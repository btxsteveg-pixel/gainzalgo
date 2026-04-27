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
    if not _has_real_contract(trade_plan):
        return False
    discord_config = config.get("discord") or {}

    is_buy = alert["side"] == "BUY"
    side_emoji = "🟢" if is_buy else "🔴"
    style_emoji = "🎯" if alert["trade_style"] == "LOTTO" else "📈"
    direction_label = "BULLISH" if is_buy else "BEARISH"
    timeframe_label = _fmt_timeframe(alert.get("timeframe"))
    description_bits = [f"{side_emoji} **{direction_label}** • **{trade_plan['contract_side']}**"]
    if timeframe_label != "N/A":
        description_bits.append(f"Timeframe: **{timeframe_label}**")

    fields = [
        _field("Symbol", alert["symbol"], True),
        _field("Contract Exp", _fmt_expiry(trade_plan.get("target_expiry")), True),
        _field("Contract Price", _fmt_money(trade_plan.get("contract_price")), True),
    ]

    payload = {
        "username": f"GainzAlgo {alert['trade_style']}",
        "embeds": [
            {
                "author": {"name": f"GainzAlgo Monster • {alert['trade_style']} Lane"},
                "title": f"{style_emoji} {alert['symbol']} • {trade_plan['contract_side']}",
                "description": "\n".join(description_bits),
                "fields": fields,
                "color": 0x00E676 if alert["side"] == "BUY" else 0xFF1744,
                "footer": {"text": _footer_text(alert, trade_plan)},
            }
        ],
    }

    payload["embeds"][0] = {k: v for k, v in payload["embeds"][0].items() if v is not None}

    return send_discord_webhook_json(webhook, payload, discord_config)


def send_discord_webhook_json(webhook, payload, discord_config):
    if not webhook:
        return False
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


def send_discord_webhook_multipart(webhook, payload, files, discord_config):
    if not webhook:
        return False
    boundary = f"----GainzAlgoBoundary{int(time.time() * 1000)}"
    data = _encode_multipart(boundary, payload, files)
    req = request.Request(
        webhook,
        data=data,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
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


def _has_real_contract(trade_plan):
    pricing_source = str(trade_plan.get("pricing_source") or "").strip().lower()
    if pricing_source in {"", "estimated"}:
        return False
    if not trade_plan.get("option_symbol"):
        return False
    if trade_plan.get("contract_price") in (None, "", 0):
        return False
    return True


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


def _fmt_expiry(value):
    text = str(value or "").strip()
    if not text:
        return "N/A"
    try:
        if "T" in text:
            text = text.split("T", 1)[0]
        year, month, day = text.split("-", 2)
        return f"{int(month)}/{int(day)}/{int(year)}"
    except (TypeError, ValueError):
        return text


def _footer_text(alert, trade_plan):
    parts = [_fmt_source(trade_plan.get("pricing_source"), trade_plan.get("contract_price_source"))]
    if alert.get("timeframe"):
        parts.append(_fmt_timeframe(alert["timeframe"]))
    if alert.get("received_at"):
        parts.append(_fmt_timestamp(alert["received_at"]))
    if trade_plan.get("contract_price") in (None, "") and trade_plan.get("option_symbol"):
        parts.append("premium pending data plan")
    return " • ".join(parts)


def _fmt_timeframe(value):
    if value in (None, ""):
        return "N/A"
    text = str(value)
    return f"{text}m" if text.isdigit() else text


def _setup_label(alert, trade_plan):
    message = str(alert.get("message") or "").strip()
    cleaned = (
        message.replace("GainzAlgo", "")
        .replace("LOTTO", "")
        .replace("SWING", "")
        .replace("BUY", "")
        .replace("SELL", "")
        .strip(" -")
    )
    if cleaned:
        return cleaned.title()
    if trade_plan.get("entry_type"):
        return str(trade_plan["entry_type"]).replace("_", " ").title()
    return None


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


def _fmt_pct(value):
    text = _fmt(value)
    return "N/A" if text == "N/A" else f"{text}%"


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


def _encode_multipart(boundary, payload, files):
    body = bytearray()

    def write_line(line=""):
        body.extend(str(line).encode("utf-8"))
        body.extend(b"\r\n")

    write_line(f"--{boundary}")
    write_line('Content-Disposition: form-data; name="payload_json"')
    write_line("Content-Type: application/json")
    write_line()
    body.extend(json.dumps(payload).encode("utf-8"))
    body.extend(b"\r\n")

    for index, file_info in enumerate(files or []):
        field_name = str(file_info.get("field_name") or f"files[{index}]")
        filename = str(file_info.get("filename") or f"attachment-{index}")
        content_type = str(file_info.get("content_type") or "application/octet-stream")
        data = file_info.get("data") or b""
        if not isinstance(data, (bytes, bytearray)):
            data = str(data).encode("utf-8")
        write_line(f"--{boundary}")
        write_line(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"')
        write_line(f"Content-Type: {content_type}")
        write_line()
        body.extend(data)
        body.extend(b"\r\n")

    write_line(f"--{boundary}--")
    return bytes(body)


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
