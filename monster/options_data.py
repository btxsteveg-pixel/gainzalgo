import json
from datetime import date, datetime, timedelta, timezone
from urllib import error, parse, request


USER_AGENT = "GainzAlgoMonster/2.0"
CRYPTO_TEST_SYMBOLS = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}


def polygon_enabled(config):
    # The live options path is Alpaca-only.
    # Keep Polygon helpers on disk for historical reference, but never activate them.
    return False


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
    if not alpaca_enabled(config):
        return states

    for state in states.values():
        open_position = state.get("open_position") or {}
        if not open_position.get("option_symbol"):
            continue

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
    alert_price = alert.get("price")
    if alert_price in (None, 0):
        return None
    if str(alert.get("symbol") or "").upper() in CRYPTO_TEST_SYMBOLS:
        return None

    style = config["styles"][alert["trade_style"]]
    trade_style = str(alert.get("trade_style") or "LOTTO").upper()
    contract_type = "call" if alert["side"] == "BUY" else "put"
    price, price_source = _resolve_underlying_reference_price(config, alert["symbol"], alert_price)
    strike_anchor = _strike_anchor(alert, price, contract_type, trade_style)
    expiry_floor, expiry_ceiling = _expiry_window(alert["received_at"], style["dte_min"], style["dte_max"], trade_style)
    strike_low, strike_high = _strike_window(price)

    if not alpaca_enabled(config):
        return None

    target_expiry = _target_expiry(alert["received_at"], style["dte_min"], style["dte_max"], trade_style)
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

    option_symbols = [contract.get("symbol") for contract in contracts if contract.get("symbol")]
    snapshots = fetch_option_snapshots(config, option_symbols)
    selected = _pick_contract(
        config,
        contracts,
        snapshots,
        price,
        target_expiry,
        contract_type,
        strike_anchor,
        trade_style,
        style,
        alert.get("confidence"),
    )
    if not selected:
        return None

    snapshot = snapshots.get(selected["symbol"])
    liquidity = _extract_contract_liquidity(snapshot, selected, provider="alpaca")

    return {
        "option_symbol": selected.get("symbol"),
        "target_expiry": selected.get("expiration_date") or target_expiry.isoformat(),
        "suggested_strike": _safe_float(selected.get("strike_price")) or trade_round(price),
        "underlying_reference_price": round(price, 4) if price not in (None, 0) else None,
        "underlying_reference_source": price_source,
        "contract_price": liquidity.get("contract_price"),
        "contract_price_source": liquidity.get("contract_price_source"),
        "delta": liquidity.get("delta"),
        "open_interest": liquidity.get("open_interest"),
        "option_volume": liquidity.get("option_volume"),
        "bid_ask_spread": liquidity.get("bid_ask_spread"),
        "bid_ask_spread_pct": liquidity.get("bid_ask_spread_pct"),
        "liquidity_score": liquidity.get("liquidity_score"),
        "pricing_source": f"alpaca-{config['alpaca']['options_feed']}",
    }


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
    strike_anchor,
    trade_style,
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

    selected = _pick_polygon_contract(contracts, underlying_price, target_expiry, contract_type, strike_anchor, trade_style)
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


def fetch_stock_snapshots(config, symbols):
    if not symbols:
        return {}

    params = {
        "symbols": ",".join(symbols[:50]),
    }
    payload = _alpaca_get_json(config, "/v2/stocks/snapshots", params=params, api="data")
    if not payload or not isinstance(payload, dict):
        return {}
    return payload


def _pick_contract(
    config,
    contracts,
    snapshots,
    underlying_price,
    target_expiry,
    contract_type,
    strike_anchor,
    trade_style,
    style,
    confidence,
):
    if trade_style == "SWING":
        return _pick_swing_contract(
            config,
            contracts,
            snapshots,
            underlying_price,
            target_expiry,
            contract_type,
            strike_anchor,
            style,
            confidence,
        )

    if trade_style == "LOTTO":
        # ── Step 1: OTM enforcement — must be strictly OTM ───────────────────
        contracts = [
            c for c in contracts
            if _otm_penalty(
                _safe_float(c.get("strike_price")) or underlying_price,
                underlying_price,
                contract_type,
            ) == 0
        ]

        # ── Step 2: Percentage-based gap filter (FIX: replaces price-blind $2-$5) ─
        # Old filter: 2.0 <= gap <= 5.0 (fixed dollars — breaks on SPY/NVDA).
        # New filter: gap_pct_min <= gap/price <= gap_pct_max (scales with price).
        # Default: 0.5%–1.5% OTM. On $500 NVDA that's $2.50–$7.50. On $50 AMD
        # that's $0.25–$0.75. Both produce real 0.25–0.45 delta contracts.
        gap_pct_min = style.get("gap_pct_min", 0.005)
        gap_pct_max = style.get("gap_pct_max", 0.015)
        contracts = [
            c for c in contracts
            if _lotto_pct_gap_ok(
                _directional_strike_gap(
                    _safe_float(c.get("strike_price")) or underlying_price,
                    underlying_price,
                    contract_type,
                ),
                underlying_price,
                gap_pct_min,
                gap_pct_max,
            )
        ]

        # ── Step 3: Liquidity filter — wired to config knobs ─────────────────
        # FIX: config knobs existed but were never enforced for lotto. Now they are.
        lotto_min_oi     = style.get("min_open_interest", 50)
        lotto_min_vol    = style.get("min_option_volume", 5)
        lotto_max_spread = style.get("max_bid_ask_spread_pct", 0.30)
        liquid = []
        for c in contracts:
            snap    = snapshots.get(c.get("symbol")) or {}
            metrics = _extract_contract_liquidity(snap, c, provider="alpaca")
            oi     = metrics.get("open_interest") or 0
            vol    = metrics.get("option_volume") or 0
            spread = metrics.get("bid_ask_spread_pct")
            if oi < lotto_min_oi:
                continue
            if vol < lotto_min_vol:
                continue
            if spread is not None and spread > lotto_max_spread:
                continue
            liquid.append(c)
        # Only apply if we still have contracts — avoids blanking out during
        # pre/post market when volume is legitimately zero.
        if liquid:
            contracts = liquid

        # ── Step 4: Delta filter — applied when Alpaca returns greeks ─────────
        # FIX: lotto had no delta filter at all. Now uses the same pattern as
        # swing but with lotto-appropriate thresholds from config.
        # Strict mode: when the feed provides greeks for any contract, missing
        # delta = excluded (not passed through as before).
        delta_min_l = style.get("delta_min", 0.25)
        delta_max_l = style.get("delta_max", 0.45)
        has_greeks = any(
            (snapshots.get(c.get("symbol")) or {}).get("greeks", {}).get("delta") is not None
            for c in contracts
        )
        if has_greeks:
            delta_filtered = [
                c for c in contracts
                if _lotto_delta_ok_strict(
                    snapshots.get(c.get("symbol")), delta_min_l, delta_max_l
                )
            ]
            if delta_filtered:
                contracts = delta_filtered
            # else: greeks present but zero passed — keep liquidity-filtered list
            # so picker always returns something rather than falling to estimated.

        contracts = _apply_contract_premium_cap(config, contracts, snapshots)

    def score(contract):
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        strike_gap = abs(strike - underlying_price)
        expiry_gap = abs((expiry - target_expiry).days)
        tradable_penalty = 0 if contract.get("tradable", True) else 1000
        otm_penalty = _otm_penalty(strike, underlying_price, contract_type)
        anchor_gap = _anchor_gap(strike, strike_anchor)
        directional_gap = _directional_strike_gap(strike, underlying_price, contract_type)
        undershoot_penalty = _lotto_min_gap_penalty(directional_gap, trade_style)
        band_penalty = _lotto_band_penalty(directional_gap, trade_style)
        return (tradable_penalty, otm_penalty, undershoot_penalty, band_penalty, anchor_gap, expiry_gap, directional_gap, strike_gap, strike)

    ranked = sorted(contracts, key=score)
    return ranked[0] if ranked else None


def _pick_swing_contract(config, contracts, snapshots, underlying_price, target_expiry, contract_type, strike_anchor, style, confidence):
    contracts = _apply_contract_premium_cap(config, contracts, snapshots)
    delta_min = style.get("delta_min", 0.40)
    delta_target_max = style.get("delta_target_max", 0.55)
    delta_absolute_max = style.get("delta_absolute_max", 0.65)
    strong_setup_confidence = style.get("strong_setup_confidence", 80.0)
    min_open_interest = style.get("min_open_interest", 100)
    min_option_volume = style.get("min_option_volume", 10)
    max_bid_ask_spread_pct = style.get("max_bid_ask_spread_pct", 0.15)
    max_distance = _swing_max_otm_distance(underlying_price)
    delta_ceiling = delta_absolute_max if _safe_float(confidence) and _safe_float(confidence) >= strong_setup_confidence else delta_target_max

    candidates = []
    for contract in contracts:
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        snapshot = snapshots.get(contract.get("symbol")) or {}
        metrics = _extract_contract_liquidity(snapshot, contract, provider="alpaca")
        signed_gap = _signed_directional_gap(strike, underlying_price, contract_type)
        delta_abs = abs(metrics.get("delta")) if metrics.get("delta") is not None else None

        if signed_gap < 0:
            continue
        if signed_gap > max_distance:
            continue
        if delta_abs is None or delta_abs < delta_min or delta_abs > delta_ceiling:
            continue
        if metrics.get("open_interest", 0) < min_open_interest:
            continue
        if metrics.get("option_volume", 0) < min_option_volume:
            continue
        if metrics.get("bid_ask_spread_pct") is None or metrics.get("bid_ask_spread_pct") > max_bid_ask_spread_pct:
            continue

        candidates.append((contract, strike, expiry, signed_gap, delta_abs, metrics))

    if not candidates:
        return None

    preferred_gap = _swing_preferred_otm_distance(underlying_price)
    preferred_delta = min(max((delta_min + delta_target_max) / 2.0, delta_min), delta_target_max)

    def score(candidate):
        contract, strike, expiry, signed_gap, delta_abs, metrics = candidate
        expiry_gap = abs((expiry - target_expiry).days)
        delta_penalty = 0 if delta_abs <= delta_target_max else round((delta_abs - delta_target_max) * 100, 4)
        preferred_delta_gap = abs(delta_abs - preferred_delta)
        gap_penalty = abs(signed_gap - preferred_gap)
        anchor_gap = _anchor_gap(strike, strike_anchor)
        spread_penalty = metrics.get("bid_ask_spread_pct") or 0
        liquidity_penalty = (
            1 / max(metrics.get("open_interest") or 1, 1),
            1 / max(metrics.get("option_volume") or 1, 1),
        )
        tradable_penalty = 0 if contract.get("tradable", True) else 1000
        return (
            tradable_penalty,
            delta_penalty,
            preferred_delta_gap,
            gap_penalty,
            spread_penalty,
            expiry_gap,
            anchor_gap,
            liquidity_penalty,
            strike,
        )

    ranked = sorted(candidates, key=score)
    return ranked[0][0] if ranked else None


def _pick_polygon_contract(contracts, underlying_price, target_expiry, contract_type, strike_anchor, trade_style):
    if trade_style == "LOTTO":
        # ── Step 1: OTM enforcement — must be strictly OTM ───────────────────
        contracts = [
            c for c in contracts
            if _otm_penalty(
                _safe_float(c.get("strike_price")) or underlying_price,
                underlying_price,
                contract_type,
            ) == 0
        ]

        # ── Step 2: Percentage-based gap filter (FIX: replaces price-blind $2-$5) ─
        # Old filter: 2.0 <= gap <= 5.0 (fixed dollars — breaks on SPY/NVDA).
        # New filter: gap_pct_min <= gap/price <= gap_pct_max (scales with price).
        # Default: 0.5%–1.5% OTM. On $500 NVDA that's $2.50–$7.50. On $50 AMD
        # that's $0.25–$0.75. Both produce real 0.25–0.45 delta contracts.
        gap_pct_min = style.get("gap_pct_min", 0.005)
        gap_pct_max = style.get("gap_pct_max", 0.015)
        contracts = [
            c for c in contracts
            if _lotto_pct_gap_ok(
                _directional_strike_gap(
                    _safe_float(c.get("strike_price")) or underlying_price,
                    underlying_price,
                    contract_type,
                ),
                underlying_price,
                gap_pct_min,
                gap_pct_max,
            )
        ]

        # ── Step 3: Liquidity filter — wired to config knobs ─────────────────
        # FIX: config knobs existed but were never enforced for lotto. Now they are.
        lotto_min_oi     = style.get("min_open_interest", 50)
        lotto_min_vol    = style.get("min_option_volume", 5)
        lotto_max_spread = style.get("max_bid_ask_spread_pct", 0.30)
        liquid = []
        for c in contracts:
            snap    = snapshots.get(c.get("symbol")) or {}
            metrics = _extract_contract_liquidity(snap, c, provider="alpaca")
            oi     = metrics.get("open_interest") or 0
            vol    = metrics.get("option_volume") or 0
            spread = metrics.get("bid_ask_spread_pct")
            if oi < lotto_min_oi:
                continue
            if vol < lotto_min_vol:
                continue
            if spread is not None and spread > lotto_max_spread:
                continue
            liquid.append(c)
        # Only apply if we still have contracts — avoids blanking out during
        # pre/post market when volume is legitimately zero.
        if liquid:
            contracts = liquid

        # ── Step 4: Delta filter — applied when Alpaca returns greeks ─────────
        # FIX: lotto had no delta filter at all. Now uses the same pattern as
        # swing but with lotto-appropriate thresholds from config.
        # Strict mode: when the feed provides greeks for any contract, missing
        # delta = excluded (not passed through as before).
        delta_min_l = style.get("delta_min", 0.25)
        delta_max_l = style.get("delta_max", 0.45)
        has_greeks = any(
            (snapshots.get(c.get("symbol")) or {}).get("greeks", {}).get("delta") is not None
            for c in contracts
        )
        if has_greeks:
            delta_filtered = [
                c for c in contracts
                if _lotto_delta_ok_strict(
                    snapshots.get(c.get("symbol")), delta_min_l, delta_max_l
                )
            ]
            if delta_filtered:
                contracts = delta_filtered
            # else: greeks present but zero passed — keep liquidity-filtered list
            # so picker always returns something rather than falling to estimated.

    def score(contract):
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        strike_gap = abs(strike - underlying_price)
        expiry_gap = abs((expiry - target_expiry).days)
        otm_penalty = _otm_penalty(strike, underlying_price, contract_type)
        anchor_gap = _anchor_gap(strike, strike_anchor)
        directional_gap = _directional_strike_gap(strike, underlying_price, contract_type)
        undershoot_penalty = _lotto_min_gap_penalty(directional_gap, trade_style)
        band_penalty = _lotto_band_penalty(directional_gap, trade_style)
        return (otm_penalty, undershoot_penalty, band_penalty, anchor_gap, expiry_gap, directional_gap, strike_gap, strike)

    ranked = sorted(contracts, key=score)
    return ranked[0] if ranked else None


def _otm_penalty(strike, underlying_price, contract_type):
    if contract_type == "call":
        return 0 if strike >= underlying_price else 1
    if contract_type == "put":
        return 0 if strike <= underlying_price else 1
    return 0


def _directional_strike_gap(strike, underlying_price, contract_type):
    if contract_type == "call":
        gap = strike - underlying_price
    elif contract_type == "put":
        gap = underlying_price - strike
    else:
        gap = abs(strike - underlying_price)
    return gap if gap >= 0 else abs(gap) + 1000


def _signed_directional_gap(strike, underlying_price, contract_type):
    if contract_type == "call":
        return strike - underlying_price
    if contract_type == "put":
        return underlying_price - strike
    return abs(strike - underlying_price)


def _parse_delta_range(delta_target_str):
    """Parse Pine alert delta_target field ('0.30-0.40') into (low, high) floats.
    Returns (None, None) when unparseable so callers fall back gracefully."""
    if not delta_target_str:
        return None, None
    parts = str(delta_target_str).split("-")
    if len(parts) == 2:
        try:
            lo, hi = float(parts[0].strip()), float(parts[1].strip())
            if 0.0 < lo < hi <= 1.0:
                return lo, hi
        except ValueError:
            pass
    try:
        v = float(delta_target_str)
        if 0.0 < v <= 1.0:
            return v, v
    except ValueError:
        pass
    return None, None


def _strike_anchor(alert, underlying_price, contract_type, trade_style):
    """Compute the preferred strike anchor for contract scoring.

    FIX: Previously hardcoded $3.50 OTM for lotto regardless of underlying price.
    That was price-blind — $3.50 OTM on a $500 stock is deep OTM garbage (0.05 delta),
    while $3.50 OTM on a $50 stock is reasonable.

    Now uses delta_target from the Pine alert when available to derive a
    percentage-based OTM offset. Approximation: ATM ≈ 0.50 delta; each 0.05
    below ATM ≈ ~1.2% OTM for typical single-name equity options. This is a
    model approximation — real delta depends on IV and DTE — but it gets the
    anchor into the correct neighbourhood for the contract scorer.

    Falls back to the style config gap_pct target if delta_target is absent.
    """
    # Try delta_target from Pine alert first
    delta_target_str = str(alert.get("delta_target") or "").strip()
    delta_lo, delta_hi = _parse_delta_range(delta_target_str)

    if delta_lo is not None:
        mid_delta = (delta_lo + delta_hi) / 2.0
        # Steps below ATM. Negative (ITM) clamped to 0 — we stay OTM.
        otm_steps = max(0.0, (0.50 - mid_delta) / 0.05)
        otm_pct = otm_steps * 0.012
        offset = round(underlying_price * otm_pct, 2)
        if contract_type == "call":
            return round(underlying_price + offset, 2)
        if contract_type == "put":
            return max(round(underlying_price - offset, 2), 0.01)

    # Lotto fallback: percentage-based gap target (fixes price-blind $3.50)
    if trade_style == "LOTTO":
        gap_pct_target = 0.010   # midpoint of 0.5%-1.5% default band
        offset = round(underlying_price * gap_pct_target, 2)
        if contract_type == "call":
            return round(underlying_price + offset, 2)
        if contract_type == "put":
            return max(round(underlying_price - offset, 2), 0.01)

    # Swing fallback: existing distance model
    target_price = _safe_float(alert.get("take_profit"))
    preferred_offset = _swing_preferred_otm_distance(underlying_price)
    max_offset = _swing_max_otm_distance(underlying_price)
    expected_move = abs(target_price - underlying_price) if target_price is not None else preferred_offset
    swing_offset = max(preferred_offset, min(expected_move * 0.35, max_offset))
    if contract_type == "call":
        return round(underlying_price + swing_offset, 2)
    if contract_type == "put":
        return max(round(underlying_price - swing_offset, 2), 0.01)
    return target_price if target_price is not None else underlying_price


def _anchor_gap(strike, strike_anchor):
    if strike_anchor in (None, ""):
        return 0
    return abs(strike - strike_anchor)


def _lotto_min_gap_penalty(directional_gap, trade_style):
    if trade_style != "LOTTO":
        return 0
    return 100 if directional_gap < 2.0 else 0


def _lotto_gap_allowed(directional_gap):
    """Legacy dollar-based filter — kept for Polygon picker compatibility."""
    return 2.0 <= directional_gap <= 5.0


def _lotto_pct_gap_ok(directional_gap, underlying_price, gap_pct_min, gap_pct_max):
    """Percentage-based gap filter for the Alpaca lotto picker.
    Replaces the price-blind $2-$5 fixed band with a band that scales with
    the underlying price, producing consistent delta ranges across all names.
    """
    if underlying_price in (None, 0):
        return False
    pct = directional_gap / underlying_price
    return gap_pct_min <= pct <= gap_pct_max


def _lotto_delta_ok_strict(snapshot, delta_min, delta_max):
    """Delta filter for lotto — strict mode.

    Returns False when delta is None (missing data = exclude, not pass).
    This closes the loophole where a no-delta contract could win the ranking
    while properly-filtered contracts were excluded.
    """
    if not snapshot:
        return False
    delta = _safe_float((snapshot.get("greeks") or {}).get("delta"))
    if delta is None:
        return False
    return delta_min <= abs(delta) <= delta_max


def _lotto_band_penalty(directional_gap, trade_style):
    if trade_style != "LOTTO":
        return 0
    if 2.0 <= directional_gap <= 5.0:
        return 0
    if directional_gap < 2.0:
        return round((2.0 - directional_gap) + 100.0, 4)
    return round((directional_gap - 5.0) + 50.0, 4)


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


def _apply_contract_premium_cap(config, contracts, snapshots):
    max_contract_premium = _safe_float((config or {}).get("max_contract_premium"))
    if max_contract_premium in (None, 0):
        return contracts

    filtered = []
    for contract in contracts:
        snapshot = snapshots.get(contract.get("symbol")) or {}
        metrics = _extract_contract_liquidity(snapshot, contract, provider="alpaca")
        contract_price = metrics.get("contract_price")
        # Only reject when Alpaca returns real price data. Missing price leaves
        # the contract eligible instead of failing closed on incomplete data.
        if contract_price is not None and contract_price > max_contract_premium:
            continue
        filtered.append(contract)
    return filtered


def _extract_contract_liquidity(snapshot, contract, provider):
    contract_price, contract_price_source = _extract_contract_price(snapshot, provider)
    if provider == "alpaca":
        quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
        daily_bar = snapshot.get("dailyBar") or snapshot.get("daily_bar") or {}
    else:
        quote = snapshot.get("last_quote") or {}
        daily_bar = snapshot.get("day") or {}

    bid = _safe_float(quote.get("bp") if "bp" in quote else quote.get("bid_price") if "bid_price" in quote else quote.get("bid"))
    ask = _safe_float(quote.get("ap") if "ap" in quote else quote.get("ask_price") if "ask_price" in quote else quote.get("ask"))
    spread = round(ask - bid, 4) if bid not in (None, 0) and ask not in (None, 0) and ask >= bid else None
    spread_pct = None
    if spread not in (None, 0) and contract_price not in (None, 0):
        spread_pct = round(spread / contract_price, 4)

    option_volume = _safe_int(
        daily_bar.get("volume")
        if "volume" in daily_bar
        else daily_bar.get("v")
        if "v" in daily_bar
        else snapshot.get("volume")
    )
    open_interest = _safe_int(contract.get("open_interest") or snapshot.get("open_interest"))
    delta = _safe_float((snapshot or {}).get("greeks", {}).get("delta"))
    liquidity_score = None
    if spread_pct is not None:
        liquidity_score = round(
            min((open_interest or 0) / 500.0, 1.0)
            + min((option_volume or 0) / 100.0, 1.0)
            - min(spread_pct, 1.0),
            4,
        )

    return {
        "contract_price": contract_price,
        "contract_price_source": contract_price_source,
        "delta": delta,
        "open_interest": open_interest,
        "option_volume": option_volume,
        "bid_ask_spread": spread,
        "bid_ask_spread_pct": spread_pct,
        "liquidity_score": liquidity_score,
    }


def _resolve_underlying_reference_price(config, symbol, alert_price):
    """Fetch a fresh underlying price from Alpaca.

    FIX: When Alpaca times out or returns nothing, the original code fell back
    to alert_price (stale TradingView data, potentially minutes old). Now we
    try two Alpaca paths before accepting the fallback, and the return value
    is tagged with its source so callers can log/inspect which price was used.
    This function returns (price, source) instead of a bare float.
    """
    if not alpaca_enabled(config) or not symbol:
        return alert_price, "alert-no-alpaca"

    snapshots = fetch_stock_snapshots(config, [symbol])
    snapshot = snapshots.get(symbol) if isinstance(snapshots, dict) else None
    live_price = _extract_stock_price(snapshot)
    if live_price not in (None, 0):
        return live_price, "alpaca-stocks"

    # Second attempt: individual stock snapshot endpoint
    try:
        payload = _alpaca_get_json(config, f"/v2/stocks/{symbol}/snapshot", params={}, api="data")
        if payload and isinstance(payload, dict):
            fallback_price = _extract_stock_price(payload)
            if fallback_price not in (None, 0):
                return fallback_price, "alpaca-stocks-individual"
    except Exception:
        pass

    return alert_price, "alert-stale"


def _extract_stock_price(snapshot):
    if not snapshot:
        return None

    trade = snapshot.get("latestTrade") or snapshot.get("latest_trade") or {}
    trade_price = _safe_float(trade.get("p") if "p" in trade else trade.get("price"))
    if trade_price not in (None, 0):
        return round(trade_price, 4)

    quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or {}
    bid = _safe_float(quote.get("bp") if "bp" in quote else quote.get("bid_price"))
    ask = _safe_float(quote.get("ap") if "ap" in quote else quote.get("ask_price"))
    if bid not in (None, 0) and ask not in (None, 0):
        return round((bid + ask) / 2, 4)
    if ask not in (None, 0):
        return round(ask, 4)
    if bid not in (None, 0):
        return round(bid, 4)

    minute_bar = snapshot.get("minuteBar") or snapshot.get("minute_bar") or {}
    minute_close = _safe_float(minute_bar.get("c") if "c" in minute_bar else minute_bar.get("close"))
    if minute_close not in (None, 0):
        return round(minute_close, 4)

    daily_bar = snapshot.get("dailyBar") or snapshot.get("daily_bar") or {}
    daily_close = _safe_float(daily_bar.get("c") if "c" in daily_bar else daily_bar.get("close"))
    if daily_close not in (None, 0):
        return round(daily_close, 4)

    return None


def _max_contracts(risk_budget, contract_cost):
    if risk_budget in (None, 0) or contract_cost in (None, 0):
        return None
    return int(risk_budget // contract_cost)


def _expiry_window(received_at, dte_min, dte_max, trade_style="LOTTO"):
    base = _parse_datetime(received_at) or datetime.now(timezone.utc)
    normalized_style = str(trade_style or "").upper()
    if normalized_style == "LOTTO":
        target = _lotto_weekly_expiry(base.date())
        # FIX: was ±1 day which could return zero Alpaca results when the target
        # Friday had no listed contracts. ±2 gives a broader net while still
        # keeping the scorer anchored to the right weekly expiry.
        return (target - timedelta(days=2), target + timedelta(days=2))
    if normalized_style == "SWING":
        target = _swing_weekly_expiry(base.date(), dte_min, dte_max)
        return (target - timedelta(days=2), target + timedelta(days=2))
    return (base.date() + timedelta(days=dte_min), base.date() + timedelta(days=dte_max))


def _target_expiry(received_at, dte_min, dte_max, trade_style="LOTTO"):
    base = _parse_datetime(received_at) or datetime.now(timezone.utc)
    normalized_style = str(trade_style or "").upper()
    if normalized_style == "LOTTO":
        return _lotto_weekly_expiry(base.date())
    if normalized_style == "SWING":
        return _swing_weekly_expiry(base.date(), dte_min, dte_max)
    expiry_floor = base.date() + timedelta(days=dte_min)
    expiry_ceiling = base.date() + timedelta(days=dte_max)
    midpoint = expiry_floor + timedelta(days=((expiry_ceiling - expiry_floor).days // 2))
    days_to_friday = (4 - midpoint.weekday()) % 7
    return midpoint + timedelta(days=days_to_friday)


def _lotto_weekly_expiry(base_date):
    weekday = base_date.weekday()
    days_to_friday = (4 - weekday) % 7
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


def _strike_window(price):
    radius = max(price * 0.08, 5)
    return max(price - radius, 0.01), price + radius


def _swing_preferred_otm_distance(underlying_price):
    return max(1.0, underlying_price * 0.01)


def _swing_max_otm_distance(underlying_price):
    return max(3.0, underlying_price * 0.02)


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
        with request.urlopen(req, timeout=6.0) as response:  # raised from 2.5s — Alpaca can be slow at market open
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
        with request.urlopen(req, timeout=6.0) as response:  # raised from 2.5s — Alpaca can be slow at market open
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
