import json
from datetime import date, datetime, timedelta, timezone
from urllib import error, parse, request


USER_AGENT = "GainzAlgoMonster/2.0"


def polygon_enabled(config):
    polygon = config.get("polygon") or {}
    return bool(polygon.get("api_key"))


def alpaca_enabled(config):
    alpaca = config.get("alpaca") or {}
    return bool(alpaca.get("api_key") and alpaca.get("secret_key"))


def enrich_trade_plan_with_option_data(config, alert, trade_plan):
    option_data = resolve_option_contract(config, alert)
    if not option_data:
        trade_plan["pricing_source"] = "estimated"
        return trade_plan

    trade_plan.update(option_data)

    contract_price = option_data.get("contract_price")
    contract_cost = round(contract_price * 100, 2) if contract_price not in (None, 0) else None
    trade_plan["contract_cost"] = contract_cost
    trade_plan["max_contracts"] = _max_contracts(trade_plan.get("risk_budget"), contract_cost)
    trade_plan["pricing_source"] = option_data.get("pricing_source", "alpaca")
    return trade_plan


def attach_live_pnl(config, states):
    if not polygon_enabled(config) and not alpaca_enabled(config):
        return states

    for state in states.values():
        open_position = state.get("open_position") or {}
        if not open_position.get("option_symbol"):
            continue

        current_contract_price = None
        price_source = None
        if polygon_enabled(config):
            snapshot = fetch_polygon_contract_snapshot(
                config,
                underlying_symbol=open_position.get("symbol"),
                contract_type=(open_position.get("contract_side") or "").lower(),
                expiration_date=open_position.get("target_expiry"),
                strike_price=open_position.get("suggested_strike"),
            )
            current_contract_price, price_source = _extract_contract_price(snapshot, provider="polygon")

        if current_contract_price is None and alpaca_enabled(config):
            snapshots = fetch_option_snapshots(config, [open_position["option_symbol"]])
            snapshot = snapshots.get(open_position["option_symbol"])
            current_contract_price, price_source = _extract_contract_price(snapshot, provider="alpaca")

        if current_contract_price is None:
            continue

        open_position["current_contract_price"] = current_contract_price
        open_position["current_contract_price_source"] = price_source
        entry_price = open_position.get("entry_contract_price")
        contracts = open_position.get("contracts")
        if entry_price is None or contracts in (None, 0):
            continue

        pnl_per_contract = current_contract_price - entry_price
        live_pnl = round(pnl_per_contract * 100 * contracts, 2)
        open_position["live_pnl"] = live_pnl
        open_position["live_pnl_pct"] = round((pnl_per_contract / entry_price) * 100, 2) if entry_price else None
    return states


def resolve_option_contract(config, alert):
    price = alert.get("price")
    if price in (None, 0):
        return None

    style = config["styles"][alert["trade_style"]]
    contract_type = "call" if alert["side"] == "BUY" else "put"
    expiry_floor, expiry_ceiling = _expiry_window(alert["received_at"], style["dte_min"], style["dte_max"])
    strike_low, strike_high = _strike_window(price)

    target_expiry = _target_expiry(expiry_floor, expiry_ceiling)
    if polygon_enabled(config):
        resolved = resolve_polygon_contract(
            config,
            underlying_symbol=alert["symbol"],
            underlying_price=price,
            contract_type=contract_type,
            expiry_floor=expiry_floor,
            expiry_ceiling=expiry_ceiling,
            strike_low=strike_low,
            strike_high=strike_high,
            target_expiry=target_expiry,
        )
        if resolved:
            return resolved

    if alpaca_enabled(config):
        contracts = fetch_option_contracts(
            config,
            underlying_symbol=alert["symbol"],
            contract_type=contract_type,
            expiry_floor=expiry_floor,
            expiry_ceiling=expiry_ceiling,
            strike_low=strike_low,
            strike_high=strike_high,
        )
        if not contracts:
            return None

        selected = _pick_contract(contracts, price, target_expiry)
        if not selected:
            return None

        snapshot = fetch_option_snapshots(config, [selected["symbol"]]).get(selected["symbol"])
        contract_price, price_source = _extract_contract_price(snapshot, provider="alpaca") if snapshot else (None, None)

        return {
            "option_symbol": selected.get("symbol"),
            "target_expiry": selected.get("expiration_date") or target_expiry.isoformat(),
            "suggested_strike": _safe_float(selected.get("strike_price")) or trade_round(price),
            "contract_price": contract_price,
            "contract_price_source": price_source,
            "delta": _safe_float((snapshot or {}).get("greeks", {}).get("delta")),
            "open_interest": _safe_int(selected.get("open_interest")),
            "pricing_source": f"alpaca-{config['alpaca']['options_feed']}",
        }

    return None


def resolve_polygon_contract(
    config,
    *,
    underlying_symbol,
    underlying_price,
    contract_type,
    expiry_floor,
    expiry_ceiling,
    strike_low,
    strike_high,
    target_expiry,
):
    contracts = fetch_polygon_contracts(
        config,
        underlying_symbol=underlying_symbol,
        contract_type=contract_type,
        expiry_floor=expiry_floor,
        expiry_ceiling=expiry_ceiling,
        strike_low=strike_low,
        strike_high=strike_high,
    )
    if not contracts:
        return None

    selected = _pick_polygon_contract(contracts, underlying_price, target_expiry)
    if not selected:
        return None

    snapshot = fetch_polygon_contract_snapshot(
        config,
        underlying_symbol=underlying_symbol,
        contract_type=contract_type,
        expiration_date=selected.get("expiration_date"),
        strike_price=selected.get("strike_price"),
    )
    contract_price, price_source = _extract_contract_price(snapshot, provider="polygon") if snapshot else (None, None)
    details = (snapshot or {}).get("details") or selected
    greeks = (snapshot or {}).get("greeks") or {}
    return {
        "option_symbol": details.get("ticker"),
        "target_expiry": details.get("expiration_date") or target_expiry.isoformat(),
        "suggested_strike": _safe_float(details.get("strike_price")) or trade_round(underlying_price),
        "contract_price": contract_price,
        "contract_price_source": price_source,
        "delta": _safe_float(greeks.get("delta")),
        "open_interest": _safe_int((snapshot or {}).get("open_interest")),
        "pricing_source": "polygon",
    }


def fetch_polygon_contracts(
    config,
    *,
    underlying_symbol,
    contract_type,
    expiry_floor,
    expiry_ceiling,
    strike_low,
    strike_high,
):
    params = {
        "underlying_ticker": underlying_symbol,
        "contract_type": contract_type,
        "expiration_date.gte": expiry_floor.isoformat(),
        "expiration_date.lte": expiry_ceiling.isoformat(),
        "strike_price.gte": _trim_float(strike_low),
        "strike_price.lte": _trim_float(strike_high),
        "limit": 250,
        "sort": "expiration_date",
        "order": "asc",
    }
    payload = _polygon_get_json(config, "/v3/reference/options/contracts", params=params)
    if not payload:
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    return results if isinstance(results, list) else []


def fetch_polygon_contract_snapshot(config, *, underlying_symbol, contract_type, expiration_date, strike_price):
    if not underlying_symbol or not contract_type or not expiration_date or strike_price in (None, ""):
        return None
    params = {
        "contract_type": contract_type,
        "expiration_date": expiration_date,
        "strike_price": _trim_float(strike_price),
        "limit": 10,
    }
    payload = _polygon_get_json(config, f"/v3/snapshot/options/{underlying_symbol}", params=params)
    if not payload or not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    for result in results:
        details = result.get("details") or {}
        if (
            str(details.get("expiration_date")) == str(expiration_date)
            and _safe_float(details.get("strike_price")) == _safe_float(strike_price)
            and str(details.get("contract_type") or "").lower() == str(contract_type).lower()
        ):
            return result
    return results[0] if results else None


def fetch_option_contracts(
    config,
    *,
    underlying_symbol,
    contract_type,
    expiry_floor,
    expiry_ceiling,
    strike_low,
    strike_high,
):
    params = {
        "underlying_symbols": underlying_symbol,
        "status": "active",
        "type": contract_type,
        "expiration_date_gte": expiry_floor.isoformat(),
        "expiration_date_lte": expiry_ceiling.isoformat(),
        "strike_price_gte": _trim_float(strike_low),
        "strike_price_lte": _trim_float(strike_high),
        "limit": 250,
    }
    payload = _alpaca_get_json(config, "/v2/options/contracts", params=params, api="trading")
    if not payload:
        return []

    if isinstance(payload, dict):
        contracts = payload.get("option_contracts") or payload.get("contracts") or payload.get("data") or []
        if isinstance(contracts, list):
            return contracts
    return []


def fetch_option_snapshots(config, option_symbols):
    if not option_symbols:
        return {}

    params = {
        "symbols": ",".join(option_symbols[:100]),
        "feed": config["alpaca"]["options_feed"],
    }
    payload = _alpaca_get_json(config, "/v1beta1/options/snapshots", params=params, api="data")
    if not payload:
        return {}

    if isinstance(payload, dict):
        snapshots = payload.get("snapshots")
        if isinstance(snapshots, dict):
            return snapshots
        if all(isinstance(value, dict) for value in payload.values()):
            return payload
    return {}


def _pick_contract(contracts, underlying_price, target_expiry):
    def score(contract):
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        strike_gap = abs(strike - underlying_price)
        expiry_gap = abs((expiry - target_expiry).days)
        tradable_penalty = 0 if contract.get("tradable", True) else 1000
        return (tradable_penalty, expiry_gap, strike_gap, strike)

    ranked = sorted(contracts, key=score)
    return ranked[0] if ranked else None


def _pick_polygon_contract(contracts, underlying_price, target_expiry):
    def score(contract):
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        strike_gap = abs(strike - underlying_price)
        expiry_gap = abs((expiry - target_expiry).days)
        return (expiry_gap, strike_gap, strike)

    ranked = sorted(contracts, key=score)
    return ranked[0] if ranked else None


def _extract_contract_price(snapshot, provider):
    if not snapshot:
        return None, None

    if provider == "polygon":
        quote = snapshot.get("last_quote") or {}
        bid = _safe_float(quote.get("bid"))
        ask = _safe_float(quote.get("ask"))
        midpoint = _safe_float(quote.get("midpoint"))
        trade = snapshot.get("last_trade") or {}
        trade_price = _safe_float(trade.get("price"))
        if midpoint not in (None, 0):
            return round(midpoint, 4), "mid"
    else:
        quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
        bid = _safe_float(quote.get("bp") if "bp" in quote else quote.get("bid_price"))
        ask = _safe_float(quote.get("ap") if "ap" in quote else quote.get("ask_price"))
        trade = snapshot.get("latestTrade") or snapshot.get("latest_trade") or {}
        trade_price = _safe_float(trade.get("p") if "p" in trade else trade.get("price"))

    if bid not in (None, 0) and ask not in (None, 0):
        return round((bid + ask) / 2, 4), "mid"
    if ask not in (None, 0):
        return round(ask, 4), "ask"
    if bid not in (None, 0):
        return round(bid, 4), "bid"
    if trade_price not in (None, 0):
        return round(trade_price, 4), "trade"
    return None, None


def _max_contracts(risk_budget, contract_cost):
    if risk_budget in (None, 0) or contract_cost in (None, 0):
        return None
    return int(risk_budget // contract_cost)


def _expiry_window(received_at, dte_min, dte_max):
    base = _parse_datetime(received_at) or datetime.now(timezone.utc)
    return (base.date() + timedelta(days=dte_min), base.date() + timedelta(days=dte_max))


def _target_expiry(expiry_floor, expiry_ceiling):
    midpoint = expiry_floor + timedelta(days=((expiry_ceiling - expiry_floor).days // 2))
    days_to_friday = (4 - midpoint.weekday()) % 7
    return midpoint + timedelta(days=days_to_friday)


def _strike_window(price):
    radius = max(price * 0.08, 5)
    return max(price - radius, 0.01), price + radius


def trade_round(price):
    if price is None:
        return None
    return int(round(price))


def _alpaca_get_json(config, path, *, params, api):
    alpaca = config["alpaca"]
    base_url = alpaca["data_base_url"] if api == "data" else alpaca["trading_base_url"]
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{parse.urlencode(params)}"

    req = request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": alpaca["api_key"],
            "APCA-API-SECRET-KEY": alpaca["secret_key"],
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _polygon_get_json(config, path, *, params):
    polygon = config["polygon"]
    params = dict(params or {})
    params["apiKey"] = polygon["api_key"]
    url = f"{polygon['base_url']}{path}?{parse.urlencode(params)}"
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _safe_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _trim_float(value):
    return f"{float(value):.4f}"
