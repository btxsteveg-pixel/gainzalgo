"""
monster/paper_trader.py
=======================
Paper execution engine for GainzAlgo Monster.

Hooks into the live alert pipeline after Discord sends and places
real orders on Alpaca's paper trading environment. Monitors every
open position for TP/SL hits and force-closes everything at 3:55 PM ET.

Flow per alert:
  1. execute_paper_trade(config, alert, trade_plan) called from app.py
  2. Places a market BUY on Alpaca paper for the selected option contract
  3. Background monitor thread wakes every 60s during market hours
  4. Checks underlying price vs TP/SL from the original alert
  5. Closes on TP hit, SL hit, or 3:55 PM ET force-close
  6. Sends a Discord exit notification to the same lane channel
  7. Records realized P&L to paper_state.json

Enable/disable with PAPER_TRADING_ENABLED=true/false in .env.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
PAPER_STATE_FILENAME = "paper_state.json"
MONITOR_INTERVAL_SECONDS = 60       # how often the monitor thread polls
FORCE_CLOSE_HOUR_ET = 15            # 3 PM hour in ET
FORCE_CLOSE_MINUTE_ET = 55          # 3:55 PM ET force-close trigger
MAX_CLOSED_HISTORY = 200            # cap closed positions in state file

# Singleton monitor thread — one per process
_monitor_thread = None
_monitor_lock = threading.Lock()    # guards thread creation
_state_lock = threading.Lock()      # guards state file reads/writes


# ═══════════════════════════════════════════════════════════════════════════
# EASTERN TIME HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _et_now():
    """Current datetime in Eastern Time. Falls back to UTC-5 if zoneinfo unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        from datetime import timedelta
        return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)


def _is_market_hours():
    """True between 9:30 AM and 4:00 PM ET on weekdays."""
    now = _et_now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    if h < 9 or (h == 9 and m < 30):
        return False
    if h >= 16:
        return False
    return True


def _should_force_close():
    """True at or after 3:55 PM ET — triggers end-of-day close sweep."""
    now = _et_now()
    return now.hour > FORCE_CLOSE_HOUR_ET or (
        now.hour == FORCE_CLOSE_HOUR_ET and now.minute >= FORCE_CLOSE_MINUTE_ET
    )


# ═══════════════════════════════════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def _state_path(config):
    return config["data_dir"] / PAPER_STATE_FILENAME


def _empty_state():
    return {
        "open_positions": [],
        "closed_positions": [],
        "stats": {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "lotto_pnl": 0.0,
            "swing_pnl": 0.0,
            "lotto_trades": 0,
            "swing_trades": 0,
        },
    }


def _load_state(config):
    path = _state_path(config)
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text())
    except Exception:
        return _empty_state()


def _save_state(config, state):
    try:
        _state_path(config).write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.error(f"Paper state save failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# ALPACA PAPER TRADING API
# All calls go to paper-api.alpaca.markets (set in ALPACA_TRADING_BASE_URL)
# ═══════════════════════════════════════════════════════════════════════════

def _alpaca_paper_call(config, method, path, body=None):
    """Make an authenticated request to the Alpaca paper trading API."""
    alpaca = config["alpaca"]
    url = f"{alpaca['trading_base_url']}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib_request.Request(
        url,
        data=data,
        headers={
            "APCA-API-KEY-ID": alpaca["api_key"],
            "APCA-API-SECRET-KEY": alpaca["secret_key"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "GainzAlgoMonster/2.0",
        },
        method=method,
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:300]
        logger.error(f"Alpaca paper {method} {path} → HTTP {exc.code}: {body_text}")
        return None
    except Exception as exc:
        logger.error(f"Alpaca paper {method} {path} → {exc}")
        return None


def _place_paper_order(config, option_symbol, qty, side="buy"):
    """Place a market order on the Alpaca paper account."""
    return _alpaca_paper_call(config, "POST", "/v2/orders", {
        "symbol": option_symbol,
        "qty": str(int(qty)),
        "side": side,
        "type": "market",
        "time_in_force": "day",
    })


def _get_paper_order(config, order_id):
    return _alpaca_paper_call(config, "GET", f"/v2/orders/{order_id}")


def _close_paper_position(config, option_symbol):
    """Send a market close order for the paper position."""
    encoded = urllib_parse.quote(option_symbol, safe="")
    return _alpaca_paper_call(config, "DELETE", f"/v2/positions/{encoded}")


# ═══════════════════════════════════════════════════════════════════════════
# PRICE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _live_underlying_price(config, symbol):
    """Fetch current stock price from Alpaca data feed."""
    try:
        from monster.options_data import fetch_stock_snapshots, _extract_stock_price
        snapshots = fetch_stock_snapshots(config, [symbol])
        snapshot = (snapshots or {}).get(symbol)
        return _extract_stock_price(snapshot)
    except Exception:
        return None


def _live_contract_price(config, option_symbol):
    """Fetch current option midpoint from Alpaca options feed."""
    try:
        from monster.options_data import fetch_option_snapshots, _extract_contract_price
        snapshots = fetch_option_snapshots(config, [option_symbol])
        snapshot = (snapshots or {}).get(option_symbol)
        price, _ = _extract_contract_price(snapshot, provider="alpaca")
        return price
    except Exception:
        return None


def _get_fill_price(config, order_id, fallback):
    """Poll for order fill price; returns fallback if not filled quickly."""
    if not order_id:
        return fallback
    time.sleep(2)
    order = _get_paper_order(config, order_id)
    if order and order.get("filled_avg_price"):
        try:
            return float(order["filled_avg_price"])
        except (TypeError, ValueError):
            pass
    return fallback


# ═══════════════════════════════════════════════════════════════════════════
# DISCORD EXIT NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def _send_exit_notification(config, position, reason, exit_price, pnl):
    """Send a paper trade exit embed to the appropriate Discord channel."""
    style = position.get("style", "LOTTO")
    webhook = (config["styles"].get(style) or {}).get("discord_webhook", "")
    if not webhook:
        return

    is_win = pnl >= 0
    color = 0x00E676 if is_win else 0xFF1744
    result_label = "PROFIT" if is_win else "LOSS"
    pnl_str = f"{'+'if pnl>=0 else ''}${abs(pnl):.2f}"

    # Calculate return %
    entry = position.get("entry_contract_price") or 0
    contracts = position.get("contracts", 1) or 1
    pct_str = ""
    if entry and exit_price:
        pct = ((exit_price - entry) / entry) * 100
        pct_str = f" ({'+' if pct>=0 else ''}{pct:.1f}%)"

    option_symbol = position.get("option_symbol", "N/A")
    # Format OCC symbol nicely if possible
    try:
        sym = option_symbol[2:] if option_symbol.startswith("O:") else option_symbol
        root = sym[:-15].strip() if len(sym) >= 15 else sym
        date_part = sym[-15:-9] if len(sym) >= 15 else ""
        side_code = sym[-9:-8] if len(sym) >= 9 else ""
        strike_raw = sym[-8:] if len(sym) >= 8 else ""
        month = int(date_part[2:4]) if len(date_part) >= 4 else 0
        day = int(date_part[4:6]) if len(date_part) >= 6 else 0
        strike = int(strike_raw) / 1000 if strike_raw else 0
        side_label = "Call" if side_code == "C" else "Put" if side_code == "P" else side_code
        strike_text = str(int(strike)) if float(strike).is_integer() else f"{strike:.1f}"
        friendly = f"{root} {strike_text} {side_label} {month}/{day}"
    except Exception:
        friendly = option_symbol

    payload = {
        "username": f"GainzAlgo {style} Paper",
        "embeds": [{
            "author": {"name": f"GainzAlgo Monster • {style} Paper Lane"},
            "title": f"{'✅' if is_win else '❌'} PAPER {result_label} — {position.get('symbol', '')} {position.get('side', '')}",
            "description": f"**{reason}**",
            "color": color,
            "fields": [
                {"name": "Contract", "value": friendly, "inline": True},
                {"name": "Entry Premium", "value": f"${entry:.2f}", "inline": True},
                {"name": "Exit Premium", "value": f"${exit_price:.2f}" if exit_price else "N/A", "inline": True},
                {"name": "Contracts", "value": str(contracts), "inline": True},
                {"name": "Realized P&L", "value": f"{pnl_str}{pct_str}", "inline": True},
                {"name": "Risk Budget", "value": f"${position.get('risk_budget', 0):.0f}", "inline": True},
            ],
            "footer": {"text": f"Paper Trade • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
        }],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        webhook, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=6):
            pass
    except Exception as exc:
        logger.error(f"Paper exit Discord send failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# POSITION CLOSE LOGIC
# ═══════════════════════════════════════════════════════════════════════════

def _close_position(config, position, reason):
    """
    Close a paper position:
    1. Send close order to Alpaca paper
    2. Get fill price (or fall back to live market price)
    3. Calculate realized P&L
    4. Send Discord exit notification
    Returns (closed_position_dict, realized_pnl)
    """
    option_symbol = position.get("option_symbol", "")
    exit_price = None

    if option_symbol:
        result = _close_paper_position(config, option_symbol)
        if result:
            order_id = result.get("id")
            if order_id:
                time.sleep(2)
                order = _get_paper_order(config, order_id)
                if order and order.get("filled_avg_price"):
                    try:
                        exit_price = float(order["filled_avg_price"])
                    except (TypeError, ValueError):
                        pass

        # Fallback: pull live market price
        if exit_price is None:
            exit_price = _live_contract_price(config, option_symbol)

    entry = position.get("entry_contract_price") or 0
    contracts = position.get("contracts", 1) or 1
    pnl = round((exit_price - entry) * 100 * contracts, 2) if exit_price is not None else 0.0

    closed = {
        **position,
        "status": "closed",
        "exit_contract_price": exit_price,
        "exit_reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "realized_pnl": pnl,
    }

    _send_exit_notification(config, position, reason, exit_price, pnl)
    logger.info(f"Paper position closed: {option_symbol} → {reason} | P&L ${pnl:+.2f}")
    return closed, pnl


def _update_stats(state, position, pnl):
    """Update cumulative P&L stats after a position closes."""
    stats = state.setdefault("stats", {
        "total_trades": 0, "wins": 0, "losses": 0,
        "total_pnl": 0.0, "lotto_pnl": 0.0, "swing_pnl": 0.0,
        "lotto_trades": 0, "swing_trades": 0,
    })
    stats["total_trades"] = stats.get("total_trades", 0) + 1
    if pnl > 0:
        stats["wins"] = stats.get("wins", 0) + 1
    else:
        stats["losses"] = stats.get("losses", 0) + 1
    stats["total_pnl"] = round(stats.get("total_pnl", 0.0) + pnl, 2)

    style = position.get("style", "LOTTO")
    if style == "LOTTO":
        stats["lotto_pnl"] = round(stats.get("lotto_pnl", 0.0) + pnl, 2)
        stats["lotto_trades"] = stats.get("lotto_trades", 0) + 1
    else:
        stats["swing_pnl"] = round(stats.get("swing_pnl", 0.0) + pnl, 2)
        stats["swing_trades"] = stats.get("swing_trades", 0) + 1


# ═══════════════════════════════════════════════════════════════════════════
# MONITOR THREAD
# Runs as a daemon — polls every 60 seconds during market hours
# ═══════════════════════════════════════════════════════════════════════════

def _monitor_loop(config):
    logger.info("Paper trader monitor thread started")
    while True:
        try:
            time.sleep(MONITOR_INTERVAL_SECONDS)

            if not _is_market_hours():
                continue

            with _state_lock:
                state = _load_state(config)
                open_positions = state.get("open_positions", [])

                if not open_positions:
                    continue

                force_close = _should_force_close()
                still_open = []
                newly_closed = []

                for pos in open_positions:
                    symbol = pos.get("symbol", "")
                    tp = pos.get("tp")
                    sl = pos.get("sl")
                    contract_side = pos.get("side", "CALL")  # CALL or PUT

                    # ── Force close at 3:55 PM ET ─────────────────────────
                    if force_close:
                        closed, pnl = _close_position(config, pos, "Force close 3:55 PM ET")
                        newly_closed.append(closed)
                        _update_stats(state, closed, pnl)
                        continue

                    # ── TP/SL check ───────────────────────────────────────
                    underlying = _live_underlying_price(config, symbol)
                    if underlying is None:
                        still_open.append(pos)
                        continue

                    hit_tp = hit_sl = False
                    if tp is not None and sl is not None:
                        if contract_side == "CALL":
                            hit_tp = underlying >= float(tp)
                            hit_sl = underlying <= float(sl)
                        else:  # PUT
                            hit_tp = underlying <= float(tp)
                            hit_sl = underlying >= float(sl)

                    if hit_tp:
                        closed, pnl = _close_position(
                            config, pos, f"TP hit — underlying @ ${underlying:.2f}"
                        )
                        newly_closed.append(closed)
                        _update_stats(state, closed, pnl)

                    elif hit_sl:
                        closed, pnl = _close_position(
                            config, pos, f"SL hit — underlying @ ${underlying:.2f}"
                        )
                        newly_closed.append(closed)
                        _update_stats(state, closed, pnl)

                    else:
                        # ── Update live prices on open positions ──────────
                        pos["current_underlying_price"] = round(underlying, 4)
                        opt_sym = pos.get("option_symbol")
                        if opt_sym:
                            contract_px = _live_contract_price(config, opt_sym)
                            if contract_px is not None:
                                pos["current_contract_price"] = contract_px
                                entry = pos.get("entry_contract_price") or 0
                                contracts = pos.get("contracts", 1) or 1
                                pos["unrealized_pnl"] = round(
                                    (contract_px - entry) * 100 * contracts, 2
                                )
                        still_open.append(pos)

                state["open_positions"] = still_open
                state["closed_positions"] = (
                    state.get("closed_positions", []) + newly_closed
                )[-MAX_CLOSED_HISTORY:]
                _save_state(config, state)

        except Exception as exc:
            logger.error(f"Paper monitor error: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def ensure_monitor_running(config):
    """Start the background monitor thread if it isn't already running."""
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(
                target=_monitor_loop,
                args=(config,),
                daemon=True,
                name="paper-monitor",
            )
            _monitor_thread.start()
            logger.info("Paper monitor thread launched")


def execute_paper_trade(config, alert, trade_plan):
    """
    Entry point called from app.py after Discord send.

    Places a paper market buy on Alpaca for the contract selected by
    the options picker, sized by the style's risk_pct config value.
    No-ops if paper trading is disabled or it's outside market hours.
    """
    if not config.get("paper_trading_enabled", True):
        return

    option_symbol = trade_plan.get("option_symbol")
    if not option_symbol:
        logger.info(f"Paper trade skipped — no contract for {alert.get('symbol')}")
        return

    if not _is_market_hours():
        logger.info("Paper trade skipped — outside market hours")
        return

    style = alert["trade_style"]
    style_cfg = config["styles"][style]

    # ── Size the position from config risk_pct ────────────────────────────
    account_size = config.get("paper_account_size", 10000)
    risk_budget = round(account_size * (style_cfg["risk_pct"] / 100.0), 2)
    contract_price = trade_plan.get("contract_price")

    if contract_price and float(contract_price) > 0:
        contracts = max(1, int(risk_budget / (float(contract_price) * 100)))
    else:
        contracts = 1

    # ── Place the order ───────────────────────────────────────────────────
    order = _place_paper_order(config, option_symbol, contracts, side="buy")
    if not order:
        logger.error(f"Paper order placement failed for {option_symbol}")
        return

    order_id = order.get("id")
    fill_price = _get_fill_price(config, order_id, fallback=contract_price)

    # ── Record the open position ──────────────────────────────────────────
    position = {
        "id": alert["signal_id"],
        "signal_id": alert["signal_id"],
        "symbol": alert["symbol"],
        "option_symbol": option_symbol,
        "side": trade_plan["contract_side"],  # CALL or PUT
        "style": style,
        "contracts": contracts,
        "entry_contract_price": float(fill_price) if fill_price else None,
        "entry_underlying_price": trade_plan.get("underlying_reference_price"),
        "current_underlying_price": trade_plan.get("underlying_reference_price"),
        "current_contract_price": float(fill_price) if fill_price else None,
        "unrealized_pnl": 0.0,
        "tp": alert.get("take_profit"),
        "sl": alert.get("stop_loss"),
        "target_expiry": trade_plan.get("target_expiry"),
        "risk_budget": risk_budget,
        "alpaca_order_id": order_id,
        "status": "open",
        "entered_at": datetime.now(timezone.utc).isoformat(),
    }

    with _state_lock:
        state = _load_state(config)
        # Prevent duplicate positions for the same signal
        existing_ids = {p["signal_id"] for p in state.get("open_positions", [])}
        if alert["signal_id"] in existing_ids:
            logger.info(f"Paper trade skipped — duplicate signal {alert['signal_id']}")
            return
        state["open_positions"].append(position)
        _save_state(config, state)

    ensure_monitor_running(config)
    logger.info(
        f"Paper position opened: {option_symbol} x{contracts} "
        f"@ ${fill_price:.2f if fill_price else 'N/A'} | budget ${risk_budget}"
    )


def get_paper_summary(config):
    """
    Returns paper trading data for the dashboard.
    Called by dashboard.py to render the paper P&L section.
    """
    try:
        state = _load_state(config)
        stats = state.get("stats", {})
        total = stats.get("total_trades", 0)
        wins = stats.get("wins", 0)
        return {
            "open_positions": state.get("open_positions", []),
            "recent_closed": state.get("closed_positions", [])[-10:][::-1],
            "stats": {
                "total_trades": total,
                "wins": wins,
                "losses": stats.get("losses", 0),
                "win_rate": round(wins / total * 100) if total else 0,
                "total_pnl": stats.get("total_pnl", 0.0),
                "lotto_pnl": stats.get("lotto_pnl", 0.0),
                "swing_pnl": stats.get("swing_pnl", 0.0),
                "lotto_trades": stats.get("lotto_trades", 0),
                "swing_trades": stats.get("swing_trades", 0),
            },
        }
    except Exception as exc:
        logger.error(f"Paper summary error: {exc}")
        return {"open_positions": [], "recent_closed": [], "stats": {}}
