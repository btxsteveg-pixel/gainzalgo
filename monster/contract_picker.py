from datetime import datetime, timezone
from html import escape
from urllib.parse import quote_plus

from monster.options_data import (
    alpaca_enabled,
    fetch_option_contracts,
    fetch_option_snapshots,
    fetch_stock_snapshots,
    _anchor_gap,
    _apply_contract_premium_cap,
    _directional_strike_gap,
    _expiry_window,
    _extract_contract_liquidity,
    _extract_stock_price,
    _lotto_delta_ok_strict,
    _lotto_pct_gap_ok,
    _otm_penalty,
    _parse_date,
    _resolve_underlying_reference_price,
    _safe_float,
    _safe_int,
    _signed_directional_gap,
    _strike_anchor,
    _strike_window,
    _swing_max_otm_distance,
    _swing_preferred_otm_distance,
    _target_expiry,
)
from monster.sidecar_universe import get_sidecar_themes


def render_contract_picker(config, public_base_url=None, params=None):
    params = params or {}
    symbol = str((params.get("symbol") or [""])[0]).strip().upper()
    trade_style = str((params.get("style") or ["LOTTO"])[0]).strip().upper()
    contract_side = str((params.get("contract_side") or ["CALL"])[0]).strip().upper()
    confidence_raw = str((params.get("confidence") or [""])[0]).strip()

    if trade_style not in {"LOTTO", "SWING"}:
        trade_style = "LOTTO"
    if contract_side not in {"CALL", "PUT"}:
        contract_side = "CALL"

    style_cfg = config.get("styles", {}).get(trade_style, {})
    default_conf = style_cfg.get("strong_setup_confidence") if trade_style == "SWING" else style_cfg.get("min_confidence")
    confidence = _safe_float(confidence_raw)
    if confidence is None:
        confidence = _safe_float(default_conf) or 70.0

    picker = None
    error_text = ""
    if symbol:
        picker, error_text = _contract_picker_payload(config, symbol, trade_style, contract_side, confidence)

    base_label = _route_label(public_base_url)
    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <meta http-equiv="refresh" content="90">
      <title>GainzAlgo Contract Picker</title>
      <style>
        :root {{ color-scheme: dark; }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          font-family: "Avenir Next", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at top left, rgba(126, 226, 255, 0.18), transparent 26%),
            radial-gradient(circle at top right, rgba(255, 145, 185, 0.12), transparent 24%),
            linear-gradient(180deg, #0d1016 0%, #121722 50%, #15131d 100%);
          color: #f7f7f8;
        }}
        main {{
          max-width: 1340px;
          margin: 0 auto;
          padding: 22px 18px 44px;
        }}
        a {{
          color: inherit;
          text-decoration: none;
        }}
        .topbar, .panel, .hero-card, .pick-card {{
          box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28);
        }}
        .topbar {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding: 14px 16px;
          border-radius: 18px;
          border: 1px solid rgba(128, 211, 255, 0.16);
          background: linear-gradient(135deg, rgba(18, 23, 33, 0.95), rgba(20, 18, 28, 0.94));
          margin-bottom: 16px;
        }}
        .brand {{
          display: flex;
          gap: 12px;
          align-items: center;
        }}
        .brand-mark {{
          width: 44px;
          height: 44px;
          border-radius: 12px;
          display: grid;
          place-items: center;
          font-size: 22px;
          background: linear-gradient(135deg, #78e1ff, #8ec5ff);
          color: #14202a;
          font-weight: 800;
        }}
        .brand-title {{
          font-size: 28px;
          font-weight: 800;
          letter-spacing: -0.03em;
        }}
        .brand-sub {{
          color: #c9d7e6;
          font-size: 13px;
          margin-top: 2px;
        }}
        .nav {{
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }}
        .pill {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 34px;
          padding: 0 12px;
          border-radius: 999px;
          border: 1px solid rgba(128, 211, 255, 0.16);
          background: rgba(255, 255, 255, 0.04);
          color: #e9f7ff;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.03em;
        }}
        .pill.active {{
          background: linear-gradient(135deg, rgba(120, 225, 255, 0.18), rgba(142, 197, 255, 0.18));
        }}
        .hero {{
          display: grid;
          grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
          gap: 16px;
          margin-bottom: 16px;
        }}
        .hero-card, .panel {{
          border-radius: 20px;
          border: 1px solid rgba(128, 211, 255, 0.11);
          background: linear-gradient(180deg, rgba(16, 21, 30, 0.96), rgba(15, 18, 28, 0.94));
          padding: 18px;
        }}
        .eyebrow {{
          color: #9fdfff;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 11px;
          font-weight: 800;
          margin-bottom: 10px;
        }}
        .hero-title {{
          font-size: 38px;
          line-height: 1.02;
          font-weight: 850;
          letter-spacing: -0.05em;
          margin-bottom: 10px;
        }}
        .hero-copy, .muted {{
          color: #d0dbe8;
          font-size: 14px;
          line-height: 1.55;
        }}
        form {{
          margin: 0;
        }}
        .form-grid {{
          display: grid;
          grid-template-columns: 1.2fr .9fr .9fr .8fr auto;
          gap: 10px;
          align-items: end;
        }}
        label {{
          display: block;
        }}
        .label {{
          display: block;
          color: #aab9ca;
          font-size: 11px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 8px;
          font-weight: 700;
        }}
        input, select {{
          width: 100%;
          min-height: 42px;
          border-radius: 12px;
          border: 1px solid rgba(128, 211, 255, 0.16);
          background: rgba(8, 11, 16, 0.9);
          color: #f5fbff;
          padding: 0 12px;
          font-size: 14px;
        }}
        button {{
          min-height: 42px;
          border-radius: 12px;
          border: 1px solid rgba(128, 211, 255, 0.16);
          background: linear-gradient(135deg, rgba(120, 225, 255, 0.22), rgba(142, 197, 255, 0.18));
          color: #f7fdff;
          padding: 0 16px;
          font-size: 14px;
          font-weight: 800;
          cursor: pointer;
        }}
        .summary-grid, .quick-grid, .pick-grid, .scout-grid {{
          display: grid;
          gap: 10px;
        }}
        .summary-grid {{
          grid-template-columns: repeat(4, minmax(0, 1fr));
          margin-top: 14px;
        }}
        .quick-grid {{
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 14px;
        }}
        .pick-grid {{
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-bottom: 16px;
        }}
        .scout-grid {{
          grid-template-columns: repeat(4, minmax(0, 1fr));
          margin-bottom: 16px;
        }}
        .summary-card, .pick-card {{
          border-radius: 16px;
          border: 1px solid rgba(128, 211, 255, 0.10);
          background: rgba(10, 13, 20, 0.88);
          padding: 14px;
        }}
        .theme-card {{
          border-radius: 16px;
          border: 1px solid rgba(128, 211, 255, 0.10);
          background: rgba(10, 13, 20, 0.88);
          padding: 14px;
        }}
        .theme-title {{
          color: #eefaff;
          font-size: 13px;
          font-weight: 800;
          letter-spacing: 0.03em;
          margin-bottom: 10px;
        }}
        .chip-cloud {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }}
        .value {{
          font-size: 30px;
          font-weight: 800;
          letter-spacing: -0.04em;
          color: #f3fbff;
        }}
        .value.small {{
          font-size: 22px;
        }}
        .section-head {{
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 12px;
          margin-bottom: 12px;
        }}
        .section-title {{
          font-size: 14px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #eefaff;
        }}
        .section-note {{
          color: #b9c8d8;
          font-size: 12px;
        }}
        .pick-card.primary {{
          border-color: rgba(120, 225, 255, 0.24);
        }}
        .pick-card.safer {{
          border-color: rgba(148, 255, 186, 0.22);
        }}
        .pick-card.aggressive {{
          border-color: rgba(255, 176, 148, 0.22);
        }}
        .pick-kind {{
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          font-weight: 800;
          margin-bottom: 10px;
        }}
        .pick-kind.primary {{ color: #9fdfff; }}
        .pick-kind.safer {{ color: #9affc2; }}
        .pick-kind.aggressive {{ color: #ffbe9f; }}
        .pick-title {{
          font-size: 24px;
          line-height: 1.1;
          font-weight: 850;
          letter-spacing: -0.04em;
          margin-bottom: 10px;
        }}
        .pick-meta {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
        }}
        .meta-box {{
          border-radius: 12px;
          border: 1px solid rgba(128, 211, 255, 0.08);
          background: rgba(255, 255, 255, 0.03);
          padding: 10px;
        }}
        .meta-label {{
          display: block;
          color: #aab9ca;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }}
        .meta-value {{
          color: #f3fbff;
          font-size: 15px;
          font-weight: 700;
        }}
        .table {{
          border-radius: 16px;
          overflow: hidden;
          border: 1px solid rgba(128, 211, 255, 0.12);
          background: rgba(11, 14, 22, 0.88);
        }}
        .table-head, .row {{
          display: grid;
          align-items: center;
          gap: 10px;
          padding: 12px 14px;
        }}
        .table-head {{
          color: #aebfd2;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          border-bottom: 1px solid rgba(128, 211, 255, 0.12);
        }}
        .row {{
          border-bottom: 1px solid rgba(128, 211, 255, 0.06);
        }}
        .row:last-child {{
          border-bottom: none;
        }}
        .candidate-table .table-head, .candidate-table .row {{
          grid-template-columns: minmax(0, 1.5fr) minmax(80px, .8fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(72px, .7fr);
        }}
        .chip {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 68px;
          padding: 7px 10px;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.04em;
          border: 1px solid rgba(128, 211, 255, 0.12);
          background: rgba(255, 255, 255, 0.05);
        }}
        .chip.lotto {{ color: #ffd38d; }}
        .chip.swing {{ color: #9fdfff; }}
        .chip.call {{ color: #8dffb0; }}
        .chip.put {{ color: #ff9aa6; }}
        .good {{ color: #8dffb0; }}
        .bad {{ color: #ff9aa6; }}
        .empty {{
          color: #c7d3df;
          padding: 18px 14px;
        }}
        @media (max-width: 1050px) {{
          .hero {{
            grid-template-columns: 1fr;
          }}
          .scout-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .pick-grid {{
            grid-template-columns: 1fr;
          }}
          .form-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
        }}
        @media (max-width: 760px) {{
          .topbar {{
            align-items: flex-start;
            flex-direction: column;
          }}
          .form-grid, .summary-grid, .quick-grid, .scout-grid {{
            grid-template-columns: 1fr;
          }}
          .candidate-table .table-head, .candidate-table .row {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
        }}
      </style>
    </head>
    <body>
      <main>
        <section class="topbar">
          <div class="brand">
            <div class="brand-mark">⚙</div>
            <div>
              <div class="brand-title">Contract Picker</div>
              <div class="brand-sub">Use the same live contract engine as GainzAlgo alerts • {escape(_route_label(public_base_url))}</div>
            </div>
          </div>
          <div class="nav">
            <a class="pill" href="/dashboard">Main Dashboard</a>
            <a class="pill" href="/morning-desk">Morning Desk</a>
            <a class="pill active" href="/contract-picker">Contract Picker</a>
          </div>
        </section>

        <section class="hero">
          <section class="hero-card">
            <div class="eyebrow">Picker Input</div>
            <div class="hero-title">Find the contract without guessing.</div>
            <div class="hero-copy">This page uses the same Alpaca contract engine, expiry window, and liquidity filters that your live LOTTO and SWING alerts already use. It is not capped to the current TradingView roster, so you can scout a broader sidecar universe without touching the live alert engine. Primary is the closest match to your live engine. Safer is the cleaner contract. Aggressive is the cheaper stretch.</div>
            <form method="get" action="/contract-picker">
              <div class="form-grid">
                <label>
                  <span class="label">Symbol</span>
                  <input type="text" name="symbol" value="{escape(symbol)}" placeholder="AAPL">
                </label>
                <label>
                  <span class="label">Lane</span>
                  <select name="style">
                    <option value="LOTTO"{" selected" if trade_style == "LOTTO" else ""}>LOTTO</option>
                    <option value="SWING"{" selected" if trade_style == "SWING" else ""}>SWING</option>
                  </select>
                </label>
                <label>
                  <span class="label">Bias</span>
                  <select name="contract_side">
                    <option value="CALL"{" selected" if contract_side == "CALL" else ""}>CALL</option>
                    <option value="PUT"{" selected" if contract_side == "PUT" else ""}>PUT</option>
                  </select>
                </label>
                <label>
                  <span class="label">Confidence</span>
                  <input type="number" min="0" max="100" step="1" name="confidence" value="{escape(str(int(confidence) if float(confidence).is_integer() else confidence))}">
                </label>
                <button type="submit">Pick Contract</button>
              </div>
            </form>
            <div class="summary-grid">
              <div class="summary-card">
                <span class="label">Lane</span>
                <div class="value small">{escape(trade_style)}</div>
              </div>
              <div class="summary-card">
                <span class="label">Bias</span>
                <div class="value small">{escape(contract_side)}</div>
              </div>
              <div class="summary-card">
                <span class="label">Confidence</span>
                <div class="value small">{escape(str(int(confidence) if float(confidence).is_integer() else confidence))}</div>
              </div>
              <div class="summary-card">
                <span class="label">Source</span>
                <div class="value small">Alpaca OPRA</div>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <div class="section-title">Quick Read</div>
              <div class="section-note">Live contract guidance only</div>
            </div>
            <div class="quick-grid">
              <div class="summary-card">
                <span class="label">Symbol</span>
                <div class="value small">{escape(picker["symbol"] if picker else (symbol or "Waiting"))}</div>
              </div>
              <div class="summary-card">
                <span class="label">Underlying</span>
                <div class="value small">{escape(_fmt_price(picker["underlying_price"]) if picker else "N/A")}</div>
              </div>
              <div class="summary-card">
                <span class="label">Target Expiry</span>
                <div class="value small">{escape(str(picker["target_expiry"]) if picker else "N/A")}</div>
              </div>
            </div>
            <div class="quick-grid">
              <div class="summary-card">
                <span class="label">Desk Note</span>
                <div class="muted">{escape(error_text or (picker["note"] if picker else "Run a symbol through the picker to get a live contract set."))}</div>
              </div>
              <div class="summary-card">
                <span class="label">Primary Read</span>
                <div class="muted">{escape(picker["primary_note"] if picker else "The primary pick is the contract closest to your live alert engine." )}</div>
              </div>
              <div class="summary-card">
                <span class="label">Use Case</span>
                <div class="muted">Primary for the normal entry, safer when you want cleaner delta/liquidity, aggressive when you want cheaper exposure and understand the trade-off.</div>
              </div>
            </div>
          </section>
        </section>

        <section class="panel">
          <div class="section-head">
            <div class="section-title">Scout Universe</div>
            <div class="section-note">Broader liquid names outside the live alert roster</div>
          </div>
          <div class="scout-grid">
            {_scout_sections(trade_style, contract_side, confidence)}
          </div>
        </section>

        <section class="pick-grid">
          {_pick_card("Primary", picker["primary"] if picker else None, "primary")}
          {_pick_card("Safer", picker["safer"] if picker else None, "safer")}
          {_pick_card("Aggressive", picker["aggressive"] if picker else None, "aggressive")}
        </section>

        <section class="panel">
          <div class="section-head">
            <div class="section-title">Candidate Board</div>
            <div class="section-note">Top live contracts after filtering and scoring</div>
          </div>
          <div class="table candidate-table">
            <div class="table-head">
              <span>Contract</span><span>Price</span><span>Delta</span><span>DTE</span><span>Spread</span><span>OI</span><span>Vol</span>
            </div>
            {_candidate_rows(picker["candidates"] if picker else [])}
          </div>
        </section>
      </main>
    </body>
    </html>
    """


def _contract_picker_payload(config, symbol, trade_style, contract_side, confidence):
    if not alpaca_enabled(config):
        return None, "Alpaca is not configured on the hosted app yet."

    stock_snapshots = fetch_stock_snapshots(config, [symbol])
    stock_snapshot = (stock_snapshots or {}).get(symbol) if isinstance(stock_snapshots, dict) else None
    live_underlying = _extract_stock_price(stock_snapshot)
    if live_underlying in (None, 0):
        return None, f"No live stock snapshot came back for {symbol}."

    side = "BUY" if contract_side == "CALL" else "SELL"
    received_at = datetime.now(timezone.utc).isoformat()
    style_cfg = config.get("styles", {}).get(trade_style, {})
    alert = {
        "trade_style": trade_style,
        "symbol": symbol,
        "side": side,
        "price": live_underlying,
        "confidence": confidence,
        "take_profit": None,
        "stop_loss": None,
        "received_at": received_at,
        "delta_target": "",
    }

    price, price_source = _resolve_underlying_reference_price(config, symbol, live_underlying)
    strike_anchor = _strike_anchor(alert, price, contract_side.lower(), trade_style)
    expiry_floor, expiry_ceiling = _expiry_window(received_at, style_cfg.get("dte_min", 0), style_cfg.get("dte_max", 7), trade_style)
    strike_low, strike_high = _strike_window(price)
    target_expiry = _target_expiry(received_at, style_cfg.get("dte_min", 0), style_cfg.get("dte_max", 7), trade_style)

    contracts = fetch_option_contracts(
        config,
        underlying_symbol=symbol,
        contract_type=contract_side.lower(),
        expiry_floor=expiry_floor,
        expiry_ceiling=expiry_ceiling,
        strike_low=strike_low,
        strike_high=strike_high,
    )
    if not contracts:
        return None, f"No live {contract_side.lower()} contracts came back for {symbol} in the current {trade_style} window."

    option_symbols = [contract.get("symbol") for contract in contracts if contract.get("symbol")]
    snapshots = fetch_option_snapshots(config, option_symbols)

    if trade_style == "LOTTO":
        candidates = _rank_lotto_candidates(config, contracts, snapshots, price, target_expiry, contract_side.lower(), strike_anchor, style_cfg)
    else:
        candidates = _rank_swing_candidates(config, contracts, snapshots, price, target_expiry, contract_side.lower(), strike_anchor, style_cfg, confidence)

    if not candidates:
        return None, f"No contracts survived the live {trade_style} filters for {symbol}."

    primary = candidates[0]
    safer = _select_safer(primary, candidates)
    aggressive = _select_aggressive(primary, candidates)

    return {
        "symbol": symbol,
        "underlying_price": price,
        "underlying_source": price_source,
        "target_expiry": target_expiry.isoformat() if hasattr(target_expiry, "isoformat") else str(target_expiry),
        "note": f"Using live Alpaca underlying price from {price_source}.",
        "primary_note": f"{primary['symbol']} is the closest live match to your {trade_style} alert engine right now.",
        "primary": primary,
        "safer": safer,
        "aggressive": aggressive,
        "candidates": candidates[:8],
    }, ""


def _scout_sections(trade_style, contract_side, confidence):
    sections = []
    for label, symbols in get_sidecar_themes():
        chips = []
        for symbol in symbols:
            href = (
                "/contract-picker"
                f"?symbol={quote_plus(symbol)}"
                f"&style={quote_plus(trade_style)}"
                f"&contract_side={quote_plus(contract_side)}"
                f"&confidence={quote_plus(str(int(confidence) if float(confidence).is_integer() else confidence))}"
            )
            chips.append(f"<a class='chip' href='{escape(href)}'>{escape(symbol)}</a>")
        sections.append(
            f"""
            <section class="theme-card">
              <div class="theme-title">{escape(label)}</div>
              <div class="chip-cloud">{''.join(chips)}</div>
            </section>
            """
        )
    return "".join(sections)


def _rank_lotto_candidates(config, contracts, snapshots, underlying_price, target_expiry, contract_type, strike_anchor, style):
    filtered = [
        c for c in contracts
        if _otm_penalty(_safe_float(c.get("strike_price")) or underlying_price, underlying_price, contract_type) == 0
    ]

    gap_pct_min = style.get("gap_pct_min", 0.005)
    gap_pct_max = style.get("gap_pct_max", 0.015)
    filtered = [
        c for c in filtered
        if _lotto_pct_gap_ok(
            _directional_strike_gap(_safe_float(c.get("strike_price")) or underlying_price, underlying_price, contract_type),
            underlying_price,
            gap_pct_min,
            gap_pct_max,
        )
    ]

    liquid = []
    for contract in filtered:
        snapshot = snapshots.get(contract.get("symbol")) or {}
        metrics = _extract_contract_liquidity(snapshot, contract, provider="alpaca")
        oi = metrics.get("open_interest") or 0
        vol = metrics.get("option_volume") or 0
        spread = metrics.get("bid_ask_spread_pct")
        if oi < style.get("min_open_interest", 50):
            continue
        if vol < style.get("min_option_volume", 5):
            continue
        if spread is not None and spread > style.get("max_bid_ask_spread_pct", 0.30):
            continue
        liquid.append(contract)
    if liquid:
        filtered = liquid

    has_greeks = any(
        (snapshots.get(contract.get("symbol")) or {}).get("greeks", {}).get("delta") is not None
        for contract in filtered
    )
    if has_greeks:
        delta_filtered = [
            contract for contract in filtered
            if _lotto_delta_ok_strict(
                snapshots.get(contract.get("symbol")),
                style.get("delta_min", 0.25),
                style.get("delta_max", 0.45),
            )
        ]
        if delta_filtered:
            filtered = delta_filtered

    filtered = _apply_contract_premium_cap(config, filtered, snapshots)

    ranked = []
    for contract in filtered:
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        directional_gap = _directional_strike_gap(strike, underlying_price, contract_type)
        metrics = _extract_contract_liquidity(snapshots.get(contract.get("symbol")) or {}, contract, provider="alpaca")
        score = (
            0 if contract.get("tradable", True) else 1000,
            _anchor_gap(strike, strike_anchor),
            abs((expiry - target_expiry).days),
            directional_gap,
            abs(strike - underlying_price),
            strike,
        )
        ranked.append(_contract_card(contract, metrics, underlying_price, expiry, directional_gap, contract_type, score))

    ranked.sort(key=lambda item: item["score"])
    return ranked


def _rank_swing_candidates(config, contracts, snapshots, underlying_price, target_expiry, contract_type, strike_anchor, style, confidence):
    contracts = _apply_contract_premium_cap(config, contracts, snapshots)
    delta_min = style.get("delta_min", 0.40)
    delta_target_max = style.get("delta_target_max", 0.55)
    delta_absolute_max = style.get("delta_absolute_max", 0.65)
    strong_setup_confidence = style.get("strong_setup_confidence", 80.0)
    max_distance = _swing_max_otm_distance(underlying_price)
    preferred_gap = _swing_preferred_otm_distance(underlying_price)
    preferred_delta = min(max((delta_min + delta_target_max) / 2.0, delta_min), delta_target_max)
    delta_ceiling = delta_absolute_max if _safe_float(confidence) and _safe_float(confidence) >= strong_setup_confidence else delta_target_max

    ranked = []
    for contract in contracts:
        strike = _safe_float(contract.get("strike_price")) or underlying_price
        expiry = _parse_date(contract.get("expiration_date")) or target_expiry
        snapshot = snapshots.get(contract.get("symbol")) or {}
        metrics = _extract_contract_liquidity(snapshot, contract, provider="alpaca")
        signed_gap = _signed_directional_gap(strike, underlying_price, contract_type)
        delta_abs = abs(metrics.get("delta")) if metrics.get("delta") is not None else None

        if signed_gap < 0 or signed_gap > max_distance:
            continue
        if delta_abs is None or delta_abs < delta_min or delta_abs > delta_ceiling:
            continue
        if metrics.get("open_interest", 0) < style.get("min_open_interest", 100):
            continue
        if metrics.get("option_volume", 0) < style.get("min_option_volume", 10):
            continue
        if metrics.get("bid_ask_spread_pct") is None or metrics.get("bid_ask_spread_pct") > style.get("max_bid_ask_spread_pct", 0.15):
            continue

        score = (
            0 if contract.get("tradable", True) else 1000,
            0 if delta_abs <= delta_target_max else round((delta_abs - delta_target_max) * 100, 4),
            abs(delta_abs - preferred_delta),
            abs(signed_gap - preferred_gap),
            metrics.get("bid_ask_spread_pct") or 0,
            abs((expiry - target_expiry).days),
            _anchor_gap(strike, strike_anchor),
            strike,
        )
        ranked.append(_contract_card(contract, metrics, underlying_price, expiry, signed_gap, contract_type, score))

    ranked.sort(key=lambda item: item["score"])
    return ranked


def _contract_card(contract, metrics, underlying_price, expiry, gap_value, contract_type, score):
    strike = _safe_float(contract.get("strike_price")) or underlying_price
    expiry_iso = expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry)
    dte = (expiry - datetime.now(timezone.utc).date()).days if hasattr(expiry, "isoformat") else None
    delta = metrics.get("delta")
    delta_abs = abs(delta) if delta is not None else None
    price = metrics.get("contract_price")
    spread_pct = metrics.get("bid_ask_spread_pct")
    contract_label = f"{contract.get('underlying_symbol') or ''} {strike:g} {'Call' if contract_type == 'call' else 'Put'} {expiry.month}/{expiry.day}" if hasattr(expiry, "month") else str(contract.get("symbol"))
    return {
        "symbol": contract.get("symbol"),
        "contract_label": contract_label.strip(),
        "contract_price": price,
        "delta": delta,
        "delta_abs": delta_abs,
        "expiry": expiry_iso,
        "dte": dte,
        "strike": strike,
        "open_interest": metrics.get("open_interest"),
        "option_volume": metrics.get("option_volume"),
        "bid_ask_spread_pct": spread_pct,
        "liquidity_score": metrics.get("liquidity_score"),
        "gap_value": gap_value,
        "score": score,
    }


def _select_safer(primary, candidates):
    if not primary:
        return None
    others = [item for item in candidates if item["symbol"] != primary["symbol"]]
    if not others:
        return primary
    ranked = sorted(
        others,
        key=lambda item: (
            -(item.get("delta_abs") or 0),
            item.get("bid_ask_spread_pct") if item.get("bid_ask_spread_pct") is not None else 9,
            -(item.get("open_interest") or 0),
            item.get("dte") if item.get("dte") is not None else 999,
        ),
    )
    return ranked[0]


def _select_aggressive(primary, candidates):
    if not primary:
        return None
    others = [item for item in candidates if item["symbol"] != primary["symbol"]]
    if not others:
        return primary
    ranked = sorted(
        others,
        key=lambda item: (
            item.get("contract_price") if item.get("contract_price") is not None else 999,
            item.get("delta_abs") if item.get("delta_abs") is not None else 999,
            -(item.get("gap_value") or 0),
        ),
    )
    return ranked[0]


def _pick_card(title, item, tone):
    if not item:
        return f"""
        <section class="pick-card {tone}">
          <div class="pick-kind {tone}">{escape(title)}</div>
          <div class="pick-title">No contract yet</div>
          <div class="muted">Run a symbol through the picker to populate this slot.</div>
        </section>
        """
    oi_vol_text = f"{_fmt_compact(item.get('open_interest'))} / {_fmt_compact(item.get('option_volume'))}"
    return f"""
    <section class="pick-card {tone}">
      <div class="pick-kind {tone}">{escape(title)}</div>
      <div class="pick-title">{escape(item['contract_label'])}</div>
      <div class="pick-meta">
        <div class="meta-box"><span class="meta-label">Price</span><div class="meta-value">{escape(_fmt_price(item.get('contract_price')))}</div></div>
        <div class="meta-box"><span class="meta-label">Delta</span><div class="meta-value">{escape(_fmt_delta(item.get('delta')))}</div></div>
        <div class="meta-box"><span class="meta-label">Expiry</span><div class="meta-value">{escape(_fmt_expiry(item.get('expiry')))}</div></div>
        <div class="meta-box"><span class="meta-label">DTE</span><div class="meta-value">{escape(str(item.get('dte')) if item.get('dte') is not None else 'N/A')}</div></div>
        <div class="meta-box"><span class="meta-label">Spread</span><div class="meta-value">{escape(_fmt_pct_ratio(item.get('bid_ask_spread_pct')))}</div></div>
        <div class="meta-box"><span class="meta-label">OI / Vol</span><div class="meta-value">{escape(oi_vol_text)}</div></div>
      </div>
    </section>
    """


def _candidate_rows(items):
    if not items:
        return "<div class='empty'>No contracts to compare yet.</div>"
    rows = []
    for item in items[:8]:
        rows.append(
            f"""
            <div class="row">
              <div>
                <div>{escape(item['contract_label'])}</div>
                <div class="muted">{escape(item['symbol'])}</div>
              </div>
              <div>{escape(_fmt_price(item.get('contract_price')))}</div>
              <div>{escape(_fmt_delta(item.get('delta')))}</div>
              <div>{escape(str(item.get('dte')) if item.get('dte') is not None else 'N/A')}</div>
              <div>{escape(_fmt_pct_ratio(item.get('bid_ask_spread_pct')))}</div>
              <div>{escape(_fmt_compact(item.get('open_interest')))}</div>
              <div>{escape(_fmt_compact(item.get('option_volume')))}</div>
            </div>
            """
        )
    return "".join(rows)


def _fmt_price(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_delta(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
        return f"{number:+.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct_ratio(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_compact(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(int(number))


def _fmt_expiry(value):
    if not value:
        return "N/A"
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        try:
            year, month, day = text[:10].split("-")
            return f"{int(month)}/{int(day)}/{year}"
        except ValueError:
            return text
    return text


def _route_label(public_base_url):
    base = str(public_base_url or "").strip()
    if "onrender.com" in base:
        return "Render Hosted"
    if "trycloudflare.com" in base:
        return "Cloudflare Tunnel"
    return "Hosted Desk"
