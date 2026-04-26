"""
GainzAlgo Monster — Options Flow Scanner

Purely additive unusual options flow scanner:
- reads option-chain and quote data from Tastytrade
- scans a fixed 20-name watchlist
- flags contracts with >= $1M premium
- posts calls to the BULL Discord webhook and puts to the BEAR webhook
"""

import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

try:
    from monster.config import _load_dotenv

    _load_dotenv()
except Exception:
    pass

WATCHLIST = [
    "SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "AMZN",
    "META", "MSFT", "GOOGL", "PLTR", "MSTR", "COIN", "BABA",
    "BAC", "F", "SOFI", "IWM", "XLF", "ARKK",
]

MIN_PREMIUM_USD = float(os.getenv("FLOW_MIN_PREMIUM", "1000000"))
MAX_DTE = int(os.getenv("FLOW_MAX_DTE", "60"))
BULL_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_BULL", "")
BEAR_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_BEAR", "")
TT_USERNAME = os.getenv("TASTYTRADE_USERNAME", "")
TT_PASSWORD = os.getenv("TASTYTRADE_PASSWORD", "")
SCAN_SECRET = os.getenv("FLOW_SCAN_SECRET", "")

_BATCH_SIZE = 200
_STREAM_TIMEOUT_SECONDS = 12
_DISCORD_POST_DELAY_SECONDS = 0.35


def run_flow_scan() -> list:
    """Sync wrapper — safe to call from a thread. Internally uses asyncio.run()."""
    try:
        return asyncio.run(_async_scan())
    except RuntimeError as exc:
        # Defensive fallback for environments that already own an event loop.
        if "cannot be called from a running event loop" in str(exc).lower():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_scan())
                return future.result(timeout=300)
        raise


async def _async_scan() -> list:
    try:
        from tastytrade import Session
        from tastytrade.dxfeed import Quote, Summary
        from tastytrade.instruments import NestedOptionChain
        from tastytrade.streamer import DXLinkStreamer
    except ImportError as exc:
        logger.error("Unable to import tastytrade package: %s", exc)
        return []

    if not TT_USERNAME or not TT_PASSWORD:
        logger.error("TASTYTRADE_USERNAME / TASTYTRADE_PASSWORD missing")
        return []

    if not BULL_WEBHOOK and not BEAR_WEBHOOK:
        logger.warning("Flow scan skipped: both Discord flow webhooks are empty")
        return []

    logger.info(
        "Options flow scan starting for %s symbols (threshold=%s, max_dte=%s)",
        len(WATCHLIST),
        _fmt_premium(MIN_PREMIUM_USD),
        MAX_DTE,
    )

    session = Session(TT_USERNAME, TT_PASSWORD)
    stock_prices = await _load_underlying_prices(session, WATCHLIST, DXLinkStreamer, Quote)

    alerts = []
    for symbol in WATCHLIST:
        try:
            alerts.extend(
                await _scan_symbol(
                    session=session,
                    symbol=symbol,
                    stock_price=stock_prices.get(symbol),
                    chain_cls=NestedOptionChain,
                    streamer_cls=DXLinkStreamer,
                    summary_cls=Summary,
                )
            )
        except Exception as exc:
            logger.warning("[%s] flow scan error: %s", symbol, exc)

    alerts.sort(key=lambda item: item["premium"], reverse=True)

    posted = []
    for alert in alerts:
        webhook = BULL_WEBHOOK if alert["opt_type"] == "C" else BEAR_WEBHOOK
        if _post_flow_alert(alert, webhook):
            posted.append(alert)
            time.sleep(_DISCORD_POST_DELAY_SECONDS)

    logger.info("Options flow scan complete — %s alerts posted", len(posted))
    return posted


async def _load_underlying_prices(session, symbols, streamer_cls, quote_cls) -> dict:
    prices = {}
    if not symbols:
        return prices

    try:
        async with streamer_cls(session) as streamer:
            await streamer.subscribe(quote_cls, list(symbols))
            deadline = asyncio.get_running_loop().time() + 8
            while len(prices) < len(symbols) and asyncio.get_running_loop().time() < deadline:
                try:
                    event = await asyncio.wait_for(streamer.listen(quote_cls), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                price = _quote_midpoint(event)
                if price > 0:
                    prices[getattr(event, "event_symbol", "")] = price
    except Exception as exc:
        logger.warning("Underlying quote stream error: %s", exc)

    return prices


async def _scan_symbol(session, symbol, stock_price, chain_cls, streamer_cls, summary_cls) -> list:
    today = date.today()
    meta_map = {}

    chain_items = chain_cls.get(session, symbol)
    for chain in chain_items:
        for expiration in getattr(chain, "expirations", []):
            exp_date = expiration.expiration_date
            dte = getattr(expiration, "days_to_expiration", None)
            if dte is None:
                dte = (exp_date - today).days
            if dte < 0 or dte > MAX_DTE:
                continue

            expiry_str = exp_date.strftime("%m/%d/%Y")
            for strike in getattr(expiration, "strikes", []):
                strike_price = _safe_float(getattr(strike, "strike_price", 0))
                call_streamer_symbol = str(getattr(strike, "call_streamer_symbol", "") or "").strip()
                put_streamer_symbol = str(getattr(strike, "put_streamer_symbol", "") or "").strip()

                if call_streamer_symbol:
                    meta_map[call_streamer_symbol] = {
                        "symbol": symbol,
                        "strike": strike_price,
                        "opt_type": "C",
                        "expiry_str": expiry_str,
                        "dte": int(dte),
                        "stock_price": stock_price,
                    }
                if put_streamer_symbol:
                    meta_map[put_streamer_symbol] = {
                        "symbol": symbol,
                        "strike": strike_price,
                        "opt_type": "P",
                        "expiry_str": expiry_str,
                        "dte": int(dte),
                        "stock_price": stock_price,
                    }

    if not meta_map:
        return []

    summary_events = await _load_summary_events(session, list(meta_map.keys()), streamer_cls, summary_cls)

    alerts = []
    for streamer_symbol, meta in meta_map.items():
        summary = summary_events.get(streamer_symbol)
        if summary is None:
            continue

        volume = _safe_float(
            getattr(summary, "day_volume", None),
            _safe_float(getattr(summary, "prev_day_volume", None)),
        )
        open_interest = _safe_float(getattr(summary, "open_interest", None))
        price = _pick_summary_price(summary)

        if volume <= 0 or price <= 0:
            continue

        premium = volume * price * 100.0
        if premium < MIN_PREMIUM_USD:
            continue

        alerts.append(
            {
                "streamer_symbol": streamer_symbol,
                "symbol": meta["symbol"],
                "strike": meta["strike"],
                "opt_type": meta["opt_type"],
                "expiry_str": meta["expiry_str"],
                "dte": meta["dte"],
                "volume": int(volume),
                "open_interest": int(open_interest) if open_interest > 0 else 0,
                "spot": round(price, 2),
                "stock_price": round(stock_price, 2) if stock_price else None,
                "premium": premium,
            }
        )

    return alerts


async def _load_summary_events(session, streamer_symbols, streamer_cls, summary_cls) -> dict:
    events = {}
    for start in range(0, len(streamer_symbols), _BATCH_SIZE):
        batch = streamer_symbols[start : start + _BATCH_SIZE]
        try:
            async with streamer_cls(session) as streamer:
                await streamer.subscribe(summary_cls, batch)
                deadline = asyncio.get_running_loop().time() + _STREAM_TIMEOUT_SECONDS
                seen = set()
                while len(seen) < len(batch) and asyncio.get_running_loop().time() < deadline:
                    try:
                        event = await asyncio.wait_for(streamer.listen(summary_cls), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    event_symbol = str(getattr(event, "event_symbol", "") or "")
                    if event_symbol and event_symbol not in seen:
                        seen.add(event_symbol)
                        events[event_symbol] = event
        except Exception as exc:
            logger.warning("Summary stream batch failed (%s-%s): %s", start, start + len(batch), exc)

    return events


def _post_flow_alert(alert, webhook) -> bool:
    if not webhook:
        return False

    is_call = alert["opt_type"] == "C"
    emoji = "🟢" if is_call else "🔴"
    color = 0x00E676 if is_call else 0xFF1744
    strike = _fmt_strike(alert["strike"])
    fire = " 🔥" if alert["open_interest"] > 0 and alert["volume"] > alert["open_interest"] * 2 else ""
    stock_line = f"${alert['stock_price']:.2f}" if alert.get("stock_price") is not None else "N/A"

    description_lines = [
        f"Premium:   {_fmt_premium(alert['premium'])}",
        f"Stock:     {stock_line}",
        f"Spot:      ${alert['spot']:.2f}",
        f"Vol / OI:  {alert['volume']:,} / {alert['open_interest']:,}{fire}",
    ]
    payload = {
        "username": "GainzAlgo Flow",
        "embeds": [
            {
                "title": f"{emoji} {alert['symbol']} ${strike} {alert['opt_type']} | {alert['expiry_str']}",
                "description": "\n".join(description_lines),
                "color": color,
                "footer": {"text": "GainzAlgo Monster • Options Flow"},
                "timestamp": _utc_iso(),
            }
        ],
    }

    req = urllib_request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "GainzAlgoMonster/1.0",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=8) as response:
            return 200 <= response.status < 300
    except urllib_error.HTTPError as exc:
        logger.error("Discord HTTP error for %s flow alert: %s %s", alert["symbol"], exc.code, exc.reason)
    except Exception as exc:
        logger.error("Discord post error for %s flow alert: %s", alert["symbol"], exc)
    return False


def _pick_summary_price(summary) -> float:
    for attr in ("prev_day_close_price", "day_close_price", "last_price"):
        value = _safe_float(getattr(summary, attr, None))
        if value > 0:
            return value
    return 0.0


def _quote_midpoint(event) -> float:
    bid = _safe_float(getattr(event, "bid_price", None))
    ask = _safe_float(getattr(event, "ask_price", None))
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    return round(bid or ask or 0.0, 2)


def _safe_float(value, default=0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt_premium(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def _fmt_strike(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    results = run_flow_scan()
    print(f"Flow scan complete — {len(results)} alerts posted")
    for item in results:
        print(
            f"{item['symbol']} ${_fmt_strike(item['strike'])} {item['opt_type']} | "
            f"{item['expiry_str']} | {_fmt_premium(item['premium'])}"
        )
