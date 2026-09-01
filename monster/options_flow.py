"""
GainzAlgo Monster — Options Flow Scanner

Purely additive unusual options flow scanner:
- reads option-chain and quote data from Tastytrade
- scans a fixed watchlist
- flags contracts with large premium
- posts directional calls to the bull Discord webhook and puts to the bear Discord webhook
- optionally detects seller-aggressed premium flow and routes it to sold-calls / sold-puts
"""

import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

import httpx


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
MIN_FLOW_VOLUME = int(os.getenv("FLOW_MIN_VOLUME", "3000"))
MIN_DTE = int(os.getenv("FLOW_MIN_DTE", "3"))
MAX_DTE = int(os.getenv("FLOW_MAX_DTE", "60"))
MAX_POSTS_PER_SCAN = int(os.getenv("FLOW_MAX_ALERTS", "8"))
MAX_POSTS_PER_SYMBOL = int(os.getenv("FLOW_MAX_ALERTS_PER_SYMBOL", "1"))
DAILY_MAX_ALERTS = int(os.getenv("FLOW_DAILY_MAX_ALERTS", "8"))
REPEAT_WINDOW_MINUTES = int(os.getenv("FLOW_REPEAT_WINDOW_MINUTES", "390"))
SYMBOL_REPEAT_WINDOW_MINUTES = int(os.getenv("FLOW_SYMBOL_REPEAT_WINDOW_MINUTES", "90"))
BULL_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_BULL", "")
BEAR_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_BEAR", "")
SOLD_CALLS_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_SOLD_CALLS", "")
SOLD_PUTS_WEBHOOK = os.getenv("FLOW_DISCORD_WEBHOOK_SOLD_PUTS", "")
SOLD_MIN_PREMIUM_USD = float(os.getenv("FLOW_SOLD_MIN_PREMIUM", "250000"))
SOLD_MIN_SELLER_SHARE = float(os.getenv("FLOW_SOLD_MIN_SELLER_SHARE", "0.55"))
SOLD_CANDIDATE_LIMIT = int(os.getenv("FLOW_SOLD_CANDIDATE_LIMIT", "40"))
SOLD_WINDOW_SECONDS = int(os.getenv("FLOW_SOLD_WINDOW_SECONDS", "30"))
SOLD_MAX_POSTS_PER_SCAN = int(os.getenv("FLOW_SOLD_MAX_ALERTS", "2"))
SOLD_MAX_POSTS_PER_SYMBOL = int(os.getenv("FLOW_SOLD_MAX_ALERTS_PER_SYMBOL", str(MAX_POSTS_PER_SYMBOL)))
SOLD_DAILY_MAX_ALERTS = int(os.getenv("FLOW_SOLD_DAILY_MAX_ALERTS", "12"))
SOLD_REPEAT_WINDOW_MINUTES = int(os.getenv("FLOW_SOLD_REPEAT_WINDOW_MINUTES", str(REPEAT_WINDOW_MINUTES)))
SOLD_SYMBOL_REPEAT_WINDOW_MINUTES = int(os.getenv("FLOW_SOLD_SYMBOL_REPEAT_WINDOW_MINUTES", str(SYMBOL_REPEAT_WINDOW_MINUTES)))
TT_CLIENT_ID = os.getenv("TASTYTRADE_CLIENT_ID", "").strip()
TT_CLIENT_SECRET = os.getenv("TASTYTRADE_CLIENT_SECRET", "").strip()
TT_REFRESH_TOKEN = os.getenv("TASTYTRADE_REFRESH_TOKEN", "").strip()
FLOW_ENABLED = os.getenv("FLOW_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
TASTYTRADE_API_ENABLED = os.getenv("TASTYTRADE_API_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

_BATCH_SIZE = 200
_STREAM_TIMEOUT_SECONDS = 12
_DISCORD_POST_DELAY_SECONDS = 0.35
_BASE_DIR = Path(__file__).resolve().parents[1]
_ENV_PATH = _BASE_DIR / ".env"
_FLOW_STATE_PATH = Path(os.getenv("DATA_DIR", str(_BASE_DIR / "data"))) / "flow_state.json"
_TT_API_URL = os.getenv("TASTYTRADE_API_BASE_URL", "https://api.tastyworks.com").strip()
_TT_USER_AGENT = "gainzalgo/1.0"
_OAUTH_TOKEN_CACHE = {
    "access_token": "",
    "expires_at": 0.0,
}


def run_flow_scan():
    if not FLOW_ENABLED:
        logger.warning("Options flow scan skipped: FLOW_ENABLED is false")
        return []
    try:
        return asyncio.run(_async_scan())
    except RuntimeError as exc:
        if "cannot be called from a running event loop" in str(exc).lower():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_scan())
                return future.result(timeout=300)
        raise


async def _async_scan():
    flow_state = _load_flow_state()
    flow_state["last_scan_started_at"] = _utc_iso()
    flow_state.pop("last_scan_error", None)
    _save_flow_state(flow_state)

    try:
        from tastytrade.dxfeed import Quote, Summary, TimeAndSale
        from tastytrade.instruments import NestedOptionChain
        from tastytrade.streamer import DXLinkStreamer
    except ImportError as exc:
        flow_state["last_scan_error"] = f"import_error: {exc}"
        flow_state["last_scan_completed_at"] = _utc_iso()
        _save_flow_state(flow_state)
        logger.error("Unable to import tastytrade package: %s", exc)
        return []

    if not TASTYTRADE_API_ENABLED or not TT_CLIENT_SECRET or not TT_REFRESH_TOKEN:
        flow_state["last_scan_error"] = "missing Tastytrade OAuth credentials"
        flow_state["last_scan_completed_at"] = _utc_iso()
        _save_flow_state(flow_state)
        logger.error("TASTYTRADE_API_ENABLED, TASTYTRADE_CLIENT_SECRET, and TASTYTRADE_REFRESH_TOKEN are required")
        return []

    if not any([BULL_WEBHOOK, BEAR_WEBHOOK, SOLD_CALLS_WEBHOOK, SOLD_PUTS_WEBHOOK]):
        flow_state["last_scan_error"] = "missing Discord flow webhooks"
        flow_state["last_scan_completed_at"] = _utc_iso()
        _save_flow_state(flow_state)
        logger.warning("Flow scan skipped: all Discord flow webhooks are empty")
        return []

    logger.info(
        "Options flow scan starting for %s symbols (threshold=%s, dte=%s-%s)",
        len(WATCHLIST),
        _fmt_premium(MIN_PREMIUM_USD),
        MIN_DTE,
        MAX_DTE,
    )

    try:
        session = await _create_tastytrade_session(
            client_secret=TT_CLIENT_SECRET,
            refresh_token=TT_REFRESH_TOKEN,
            client_id=TT_CLIENT_ID or None,
        )
    except Exception as exc:
        flow_state["last_scan_error"] = str(exc)
        flow_state["last_scan_completed_at"] = _utc_iso()
        _save_flow_state(flow_state)
        logger.error(
            "Tastytrade OAuth setup failed: %s. Verify TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN.",
            exc,
        )
        return []
    try:
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

        selected_alerts, selection_meta = _select_alerts_for_posting(alerts, flow_state)
        sold_candidates = []
        sold_selection_meta = {
            "ranked_by": "seller_premium_then_share",
            "max_alerts": SOLD_MAX_POSTS_PER_SCAN,
            "max_alerts_per_symbol": SOLD_MAX_POSTS_PER_SYMBOL,
            "daily_max_alerts": SOLD_DAILY_MAX_ALERTS,
            "remaining_today": _daily_alert_count(flow_state, namespace="sold"),
            "min_seller_premium": SOLD_MIN_PREMIUM_USD,
            "min_seller_share": SOLD_MIN_SELLER_SHARE,
            "candidate_limit": SOLD_CANDIDATE_LIMIT,
            "window_seconds": SOLD_WINDOW_SECONDS,
            "skipped": {},
        }
        selected_sold_alerts = []
        sold_posted = []

        if alerts and (SOLD_CALLS_WEBHOOK or SOLD_PUTS_WEBHOOK):
            sold_candidates = await _build_sold_flow_candidates(
                session=session,
                alerts=alerts,
                streamer_cls=DXLinkStreamer,
                time_and_sale_cls=TimeAndSale,
            )
            selected_sold_alerts, sold_selection_meta = _select_sold_alerts_for_posting(
                sold_candidates,
                flow_state,
            )

        posted = []
        for alert in selected_alerts:
            webhook = BULL_WEBHOOK if alert["opt_type"] == "C" else BEAR_WEBHOOK
            if _post_flow_alert(alert, webhook):
                posted.append(alert)
                _remember_post(flow_state, alert, namespace="flow")
                time.sleep(_DISCORD_POST_DELAY_SECONDS)

        for alert in selected_sold_alerts:
            webhook = SOLD_CALLS_WEBHOOK if alert["opt_type"] == "C" else SOLD_PUTS_WEBHOOK
            if _post_sold_flow_alert(alert, webhook):
                sold_posted.append(alert)
                _remember_post(flow_state, alert, namespace="sold")
                time.sleep(_DISCORD_POST_DELAY_SECONDS)

        flow_state["last_scan_candidate_count"] = len(alerts)
        flow_state["last_scan_selected_count"] = len(selected_alerts)
        flow_state["last_scan_posted_count"] = len(posted)
        flow_state["last_scan_selection"] = selection_meta
        flow_state["last_posted"] = [_snapshot_alert(alert) for alert in posted[:MAX_POSTS_PER_SCAN]]
        flow_state["last_sold_scan_candidate_count"] = len(sold_candidates)
        flow_state["last_sold_scan_selected_count"] = len(selected_sold_alerts)
        flow_state["last_sold_scan_posted_count"] = len(sold_posted)
        flow_state["last_sold_scan_selection"] = sold_selection_meta
        flow_state["last_sold_posted"] = [
            _snapshot_alert(alert, lane="sold") for alert in sold_posted[:SOLD_MAX_POSTS_PER_SCAN]
        ]
        flow_state["last_scan_completed_at"] = _utc_iso()
        _save_flow_state(flow_state)
        logger.info(
            "Options flow scan complete — %s directional alerts, %s sold-premium alerts posted",
            len(posted),
            len(sold_posted),
        )
        return posted + sold_posted
    finally:
        await session.aclose()


async def _create_tastytrade_session(
    client_secret=None,
    refresh_token=None,
    client_id=None,
):
    if not TASTYTRADE_API_ENABLED:
        raise RuntimeError("Tastytrade API access disabled; set TASTYTRADE_API_ENABLED=true only after compliance fixes are approved")

    access_token = await _get_oauth_access_token(
        client_secret=client_secret,
        refresh_token=refresh_token,
        client_id=client_id,
    )
    authed_headers = _base_headers()
    authed_headers["Authorization"] = f"Bearer {access_token}"

    sync_client = httpx.Client(base_url=_TT_API_URL, headers=authed_headers)
    async_client = httpx.AsyncClient(base_url=_TT_API_URL, headers=authed_headers)
    try:
        quote_response = await async_client.get("/quote-streamer-tokens", timeout=30)
        quote_data = _parse_tastytrade_response(quote_response, "quote streamer token fetch")

        return _DirectTastytradeSession(
            sync_client=sync_client,
            async_client=async_client,
            access_token=access_token,
            streamer_token=quote_data["token"],
            dxlink_url=quote_data["dxlink-url"],
        )
    except Exception:
        await async_client.aclose()
        sync_client.close()
        raise


def _base_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _TT_USER_AGENT,
    }


async def _get_oauth_access_token(client_secret=None, refresh_token=None, client_id=None):
    cached_token = _OAUTH_TOKEN_CACHE.get("access_token", "")
    if cached_token and time.time() < float(_OAUTH_TOKEN_CACHE.get("expires_at", 0.0)):
        return cached_token

    client_secret = (client_secret or "").strip()
    refresh_token = (refresh_token or "").strip()
    client_id = (client_id or "").strip()
    if not client_secret or not refresh_token:
        raise ValueError("TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN are required")

    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_secret": client_secret,
    }
    if client_id:
        body["client_id"] = client_id

    async with httpx.AsyncClient(base_url=_TT_API_URL, headers=_base_headers()) as auth_client:
        response = await auth_client.post("/oauth/token", json=body, timeout=30)
        data = _parse_oauth_response(response, "OAuth token refresh")

    access_token = (data.get("access_token") or data.get("access-token") or "").strip()
    if not access_token:
        raise RuntimeError("OAuth token refresh failed: missing access token")

    expires_in = _safe_float(data.get("expires_in"), _safe_float(data.get("expires-in"), 900.0))
    refresh_margin = min(120.0, max(30.0, expires_in * 0.2))
    _OAUTH_TOKEN_CACHE["access_token"] = access_token
    _OAUTH_TOKEN_CACHE["expires_at"] = time.time() + max(60.0, expires_in - refresh_margin)
    return access_token


def _parse_oauth_response(response, action):
    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code // 100 != 2:
        error_obj = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        code = error_obj.get("code") or payload.get("error") or response.status_code
        message = error_obj.get("message") or payload.get("error_description") or response.text
        raise RuntimeError(f"{action} failed ({code}): {message}")

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        return data
    return payload if isinstance(payload, dict) else {}


class _DirectTastytradeSession:
    def __init__(self, sync_client, async_client, access_token, streamer_token, dxlink_url):
        self.is_test = False
        self.proxy = None
        self.sync_client = sync_client
        self.async_client = async_client
        self.access_token = access_token
        self.session_token = access_token
        self.remember_token = ""
        self.streamer_token = streamer_token
        self.dxlink_url = dxlink_url

    async def _a_get(self, url, **kwargs):
        response = await self.async_client.get(url, timeout=30, **kwargs)
        return _parse_tastytrade_response(response, f"GET {url}")

    def _get(self, url, **kwargs):
        response = self.sync_client.get(url, timeout=30, **kwargs)
        return _parse_tastytrade_response(response, f"GET {url}")

    async def aclose(self):
        await self.async_client.aclose()
        self.sync_client.close()


def _parse_tastytrade_response(response, action):
    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code // 100 != 2:
        error_obj = payload.get("error") or {}
        code = error_obj.get("code", response.status_code)
        message = error_obj.get("message", response.text)
        raise RuntimeError(f"{action} failed ({code}): {message}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{action} failed: missing data payload")
    return data


async def _load_underlying_prices(session, symbols, streamer_cls, quote_cls):
    prices = {}
    if not symbols:
        return prices

    try:
        async with streamer_cls(session) as streamer:
            await streamer.subscribe(quote_cls, list(symbols))
            deadline = asyncio.get_running_loop().time() + 8
            while len(prices) < len(symbols) and asyncio.get_running_loop().time() < deadline:
                try:
                    event = await asyncio.wait_for(streamer.get_event(quote_cls), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                price = _quote_midpoint(event)
                if price > 0:
                    prices[getattr(event, "event_symbol", "")] = price
    except Exception as exc:
        logger.warning("Underlying quote stream error: %s", exc)

    return prices


async def _scan_symbol(session, symbol, stock_price, chain_cls, streamer_cls, summary_cls):
    today = date.today()
    meta_map = {}

    chain_items = chain_cls.get_chain(session, symbol)
    for chain in chain_items:
        for expiration in getattr(chain, "expirations", []):
            exp_date = expiration.expiration_date
            dte = getattr(expiration, "days_to_expiration", None)
            if dte is None:
                dte = (exp_date - today).days
            if dte < MIN_DTE or dte > MAX_DTE:
                continue

            expiry_str = exp_date.strftime("%m/%d/%Y")
            for strike in getattr(expiration, "strikes", []):
                strike_price = _safe_float(getattr(strike, "strike_price", 0))
                call_streamer_symbol = str(getattr(strike, "call_streamer_symbol", "") or "").strip()
                put_streamer_symbol = str(getattr(strike, "put_streamer_symbol", "") or "").strip()

                if call_streamer_symbol:
                    meta_map[call_streamer_symbol] = {
                        "contract_symbol": call_streamer_symbol,
                        "symbol": symbol,
                        "strike": strike_price,
                        "opt_type": "C",
                        "expiry_str": expiry_str,
                        "dte": int(dte),
                        "stock_price": stock_price,
                    }
                if put_streamer_symbol:
                    meta_map[put_streamer_symbol] = {
                        "contract_symbol": put_streamer_symbol,
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
                "contract_symbol": meta["contract_symbol"],
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


async def _load_summary_events(session, streamer_symbols, streamer_cls, summary_cls):
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
                        event = await asyncio.wait_for(streamer.get_event(summary_cls), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    event_symbol = str(getattr(event, "event_symbol", "") or "")
                    if event_symbol and event_symbol not in seen:
                        seen.add(event_symbol)
                        events[event_symbol] = event
        except Exception as exc:
            logger.warning("Summary stream batch failed (%s-%s): %s", start, start + len(batch), exc)

    return events


async def _build_sold_flow_candidates(session, alerts, streamer_cls, time_and_sale_cls):
    ranked = sorted(alerts, key=lambda item: (item["volume"], item["premium"]), reverse=True)
    candidates = ranked[: max(0, SOLD_CANDIDATE_LIMIT)]
    if not candidates:
        return []

    stats_by_symbol = await _load_time_and_sale_stats(
        session,
        [item["streamer_symbol"] for item in candidates],
        streamer_cls,
        time_and_sale_cls,
    )

    sold_candidates = []
    for alert in candidates:
        stats = stats_by_symbol.get(alert["streamer_symbol"])
        if not stats:
            continue

        seller_premium = float(stats.get("sell_premium", 0.0))
        buyer_premium = float(stats.get("buy_premium", 0.0))
        total_premium = float(stats.get("total_premium", 0.0))
        seller_share = seller_premium / total_premium if total_premium > 0 else 0.0

        if seller_premium < SOLD_MIN_PREMIUM_USD:
            continue
        if seller_share < SOLD_MIN_SELLER_SHARE:
            continue
        if seller_premium <= buyer_premium:
            continue

        sold_alert = dict(alert)
        sold_alert.update(
            {
                "flow_lane": "sold_calls" if alert["opt_type"] == "C" else "sold_puts",
                "seller_premium": round(seller_premium, 2),
                "buyer_premium": round(buyer_premium, 2),
                "seller_share": seller_share,
                "seller_volume": int(stats.get("sell_volume", 0)),
                "buyer_volume": int(stats.get("buy_volume", 0)),
                "seller_trades": int(stats.get("sell_trades", 0)),
                "buyer_trades": int(stats.get("buy_trades", 0)),
                "time_and_sale_events": int(stats.get("event_count", 0)),
            }
        )
        sold_candidates.append(sold_alert)

    return sold_candidates


async def _load_time_and_sale_stats(session, streamer_symbols, streamer_cls, time_and_sale_cls):
    stats = {}
    if not streamer_symbols:
        return stats

    for start in range(0, len(streamer_symbols), _BATCH_SIZE):
        batch = streamer_symbols[start : start + _BATCH_SIZE]
        try:
            async with streamer_cls(session) as streamer:
                await streamer.subscribe(time_and_sale_cls, batch, refresh_interval=0.2)
                deadline = asyncio.get_running_loop().time() + max(2, SOLD_WINDOW_SECONDS)
                while asyncio.get_running_loop().time() < deadline:
                    timeout = min(1.0, max(0.1, deadline - asyncio.get_running_loop().time()))
                    try:
                        event = await asyncio.wait_for(streamer.get_event(time_and_sale_cls), timeout=timeout)
                    except asyncio.TimeoutError:
                        continue

                    event_symbol = str(getattr(event, "event_symbol", "") or "")
                    if not event_symbol:
                        continue
                    if not _is_live_time_and_sale_event(event):
                        continue

                    price = _safe_float(getattr(event, "price", None))
                    size = int(_safe_float(getattr(event, "size", None)))
                    if price <= 0 or size <= 0:
                        continue

                    premium = price * size * 100.0
                    side = _classify_time_and_sale_side(event)

                    bucket = stats.setdefault(
                        event_symbol,
                        {
                            "event_count": 0,
                            "total_premium": 0.0,
                            "sell_premium": 0.0,
                            "buy_premium": 0.0,
                            "unknown_premium": 0.0,
                            "sell_volume": 0,
                            "buy_volume": 0,
                            "sell_trades": 0,
                            "buy_trades": 0,
                        },
                    )
                    bucket["event_count"] += 1
                    bucket["total_premium"] += premium

                    if side == "sell":
                        bucket["sell_premium"] += premium
                        bucket["sell_volume"] += size
                        bucket["sell_trades"] += 1
                    elif side == "buy":
                        bucket["buy_premium"] += premium
                        bucket["buy_volume"] += size
                        bucket["buy_trades"] += 1
                    else:
                        bucket["unknown_premium"] += premium
        except Exception as exc:
            logger.warning("Time-and-sale stream batch failed (%s-%s): %s", start, start + len(batch), exc)

    return stats


def _is_live_time_and_sale_event(event):
    valid_tick = getattr(event, "valid_tick", getattr(event, "validTick", True))
    if valid_tick is False:
        return False

    event_type = str(getattr(event, "type", "") or "").strip().lower()
    if event_type in {"1", "2", "correction", "cancellation", "cancel"}:
        return False
    return True


def _classify_time_and_sale_side(event):
    raw_side = str(
        getattr(event, "aggressor_side", "") or getattr(event, "aggressorSide", "")
    ).strip().upper()

    if raw_side in {"SELL", "S", "BID", "ATBID", "BELOW_BID", "BELOW BID"}:
        return "sell"
    if raw_side in {"BUY", "B", "ASK", "ATASK", "ABOVE_ASK", "ABOVE ASK"}:
        return "buy"

    price = _safe_float(getattr(event, "price", None))
    bid = _safe_float(getattr(event, "bid_price", None), _safe_float(getattr(event, "bidPrice", None)))
    ask = _safe_float(getattr(event, "ask_price", None), _safe_float(getattr(event, "askPrice", None)))

    if price > 0:
        if bid > 0 and price <= bid:
            return "sell"
        if ask > 0 and price >= ask:
            return "buy"
        if bid > 0 and ask > 0:
            midpoint = (bid + ask) / 2.0
            if price < midpoint:
                return "sell"
            if price > midpoint:
                return "buy"

    return ""


def _post_flow_alert(alert, webhook):
    if not webhook:
        return False

    is_call = alert["opt_type"] == "C"
    emoji = "🟢" if is_call else "🔴"
    color = 0x00E676 if is_call else 0xFF1744
    strike = _fmt_strike(alert["strike"])
    fire = " 🔥" if alert["open_interest"] > 0 and alert["volume"] > alert["open_interest"] * 2 else ""
    stock_line = f"${alert['stock_price']:.2f}" if alert.get("stock_price") is not None else "N/A"

    description_lines = [
        f"Contract:  {alert.get('contract_symbol') or alert['streamer_symbol']}",
        f"Premium:   {_fmt_premium(alert['premium'])}",
        f"Stock:     {stock_line}",
        f"Spot:      ${alert['spot']:.2f}",
        f"DTE:       {alert['dte']}",
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


def _post_sold_flow_alert(alert, webhook):
    if not webhook:
        return False

    is_call = alert["opt_type"] == "C"
    strike = _fmt_strike(alert["strike"])
    stock_line = f"${alert['stock_price']:.2f}" if alert.get("stock_price") is not None else "N/A"
    seller_share_pct = alert.get("seller_share", 0.0) * 100.0
    seller_volume = int(alert.get("seller_volume", 0))
    buyer_volume = int(alert.get("buyer_volume", 0))
    seller_trades = int(alert.get("seller_trades", 0))
    buyer_trades = int(alert.get("buyer_trades", 0))

    payload = {
        "username": "GainzAlgo Sold Flow",
        "embeds": [
            {
                "title": (
                    f"{'🟠' if is_call else '🟣'} {alert['symbol']} ${strike} {alert['opt_type']} | "
                    f"{alert['expiry_str']} • {'Sold Calls' if is_call else 'Sold Puts'}"
                ),
                "description": "\n".join(
                    [
                        f"Contract:      {alert.get('contract_symbol') or alert['streamer_symbol']}",
                        f"Seller Prem:   {_fmt_premium(alert.get('seller_premium', 0.0))}",
                        f"Buyer Prem:    {_fmt_premium(alert.get('buyer_premium', 0.0))}",
                        f"Seller Share:  {seller_share_pct:.0f}%",
                        f"Stock:         {stock_line}",
                        f"Spot:          ${alert['spot']:.2f}",
                        f"DTE:           {alert['dte']}",
                        f"Sell / Buy Vol:{seller_volume:,} / {buyer_volume:,}",
                        f"Sell / Buy T&S:{seller_trades:,} / {buyer_trades:,}",
                    ]
                ),
                "color": 0xFB8C00 if is_call else 0x8E24AA,
                "footer": {"text": "GainzAlgo Monster • Sold Premium Flow"},
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
        logger.error("Discord HTTP error for %s sold flow alert: %s %s", alert["symbol"], exc.code, exc.reason)
    except Exception as exc:
        logger.error("Discord post error for %s sold flow alert: %s", alert["symbol"], exc)
    return False


def _pick_summary_price(summary):
    for attr in ("prev_day_close_price", "day_close_price", "last_price"):
        value = _safe_float(getattr(summary, attr, None))
        if value > 0:
            return value
    return 0.0


def _quote_midpoint(event):
    bid = _safe_float(getattr(event, "bid_price", None))
    ask = _safe_float(getattr(event, "ask_price", None))
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    return round(bid or ask or 0.0, 2)


def _safe_float(value, default=0.0):
    if value is None:
        return float(default)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt_premium(value):
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def _fmt_strike(value):
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _select_alerts_for_posting(alerts, flow_state):
    ranked = sorted(alerts, key=lambda item: (item["volume"], item["premium"]), reverse=True)
    return _select_posting_candidates(
        ranked,
        flow_state,
        namespace="flow",
        max_posts_per_scan=MAX_POSTS_PER_SCAN,
        max_posts_per_symbol=MAX_POSTS_PER_SYMBOL,
        daily_max_alerts=DAILY_MAX_ALERTS,
        min_volume=MIN_FLOW_VOLUME,
        rank_label="volume_then_premium",
        extra_meta={},
    )


def _select_sold_alerts_for_posting(alerts, flow_state):
    ranked = sorted(
        alerts,
        key=lambda item: (item.get("seller_premium", 0.0), item.get("seller_share", 0.0), item["volume"]),
        reverse=True,
    )
    return _select_posting_candidates(
        ranked,
        flow_state,
        namespace="sold",
        max_posts_per_scan=SOLD_MAX_POSTS_PER_SCAN,
        max_posts_per_symbol=SOLD_MAX_POSTS_PER_SYMBOL,
        daily_max_alerts=SOLD_DAILY_MAX_ALERTS,
        min_volume=MIN_FLOW_VOLUME,
        rank_label="seller_premium_then_share",
        extra_meta={
            "candidate_limit": SOLD_CANDIDATE_LIMIT,
            "min_seller_premium": SOLD_MIN_PREMIUM_USD,
            "min_seller_share": SOLD_MIN_SELLER_SHARE,
            "window_seconds": SOLD_WINDOW_SECONDS,
        },
    )


def _select_posting_candidates(
    ranked,
    flow_state,
    *,
    namespace,
    max_posts_per_scan,
    max_posts_per_symbol,
    daily_max_alerts,
    min_volume,
    rank_label,
    extra_meta,
):
    daily_count = _daily_alert_count(flow_state, namespace=namespace)
    remaining_today = max(0, daily_max_alerts - daily_count)
    selected = []
    per_symbol_counts = {}
    skipped = {
        "daily_limit": 0,
        "below_volume_threshold": 0,
        "recently_sent": 0,
        "symbol_cooldown": 0,
        "per_symbol_limit": 0,
    }

    if remaining_today <= 0:
        skipped["daily_limit"] = len(ranked)
        return [], {
            "ranked_by": rank_label,
            "max_alerts": max_posts_per_scan,
            "max_alerts_per_symbol": max_posts_per_symbol,
            "daily_max_alerts": daily_max_alerts,
            "remaining_today": 0,
            "min_volume": min_volume,
            "symbol_cooldown_minutes": _symbol_repeat_window_minutes(namespace),
            "skipped": skipped,
            **extra_meta,
        }

    for alert in ranked:
        if alert["volume"] < min_volume:
            skipped["below_volume_threshold"] += 1
            continue

        if _was_sent_recently(flow_state, alert["streamer_symbol"], namespace=namespace):
            skipped["recently_sent"] += 1
            continue

        if _was_symbol_sent_recently(flow_state, alert["symbol"], namespace=namespace):
            skipped["symbol_cooldown"] += 1
            continue

        symbol_count = per_symbol_counts.get(alert["symbol"], 0)
        if symbol_count >= max_posts_per_symbol:
            skipped["per_symbol_limit"] += 1
            continue

        selected.append(alert)
        per_symbol_counts[alert["symbol"]] = symbol_count + 1
        if len(selected) >= min(max_posts_per_scan, remaining_today):
            break

    return selected, {
        "ranked_by": rank_label,
        "max_alerts": max_posts_per_scan,
        "max_alerts_per_symbol": max_posts_per_symbol,
        "daily_max_alerts": daily_max_alerts,
        "remaining_today": remaining_today,
        "min_volume": min_volume,
        "symbol_cooldown_minutes": _symbol_repeat_window_minutes(namespace),
        "skipped": skipped,
        **extra_meta,
    }


def _load_flow_state():
    if not _FLOW_STATE_PATH.exists():
        payload = {}
        _ensure_namespace_state(payload, "flow")
        _ensure_namespace_state(payload, "sold")
        return payload

    try:
        payload = json.loads(_FLOW_STATE_PATH.read_text())
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    _ensure_namespace_state(payload, "flow")
    _ensure_namespace_state(payload, "sold")
    _refresh_daily_count(payload, namespace="flow")
    _refresh_daily_count(payload, namespace="sold")
    _prune_recent_contracts(payload, namespace="flow")
    _prune_recent_contracts(payload, namespace="sold")
    _prune_recent_symbols(payload, namespace="flow")
    _prune_recent_symbols(payload, namespace="sold")
    return payload


def _save_flow_state(flow_state):
    _FLOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ensure_namespace_state(flow_state, "flow")
    _ensure_namespace_state(flow_state, "sold")
    _refresh_daily_count(flow_state, namespace="flow")
    _refresh_daily_count(flow_state, namespace="sold")
    _prune_recent_contracts(flow_state, namespace="flow")
    _prune_recent_contracts(flow_state, namespace="sold")
    _prune_recent_symbols(flow_state, namespace="flow")
    _prune_recent_symbols(flow_state, namespace="sold")
    _FLOW_STATE_PATH.write_text(json.dumps(flow_state, indent=2, sort_keys=True))


def _ensure_namespace_state(flow_state, namespace):
    keys = _namespace_keys(namespace)
    flow_state.setdefault(keys["recent_contracts"], {})
    flow_state.setdefault(keys["recent_symbols"], {})
    flow_state.setdefault(keys["last_posted"], [])


def _namespace_keys(namespace):
    if namespace == "flow":
        return {
            "recent_contracts": "recent_contracts",
            "recent_symbols": "recent_symbols",
            "last_posted": "last_posted",
            "daily_alert_day": "daily_alert_day",
            "daily_alert_count": "daily_alert_count",
        }
    return {
        "recent_contracts": f"{namespace}_recent_contracts",
        "recent_symbols": f"{namespace}_recent_symbols",
        "last_posted": f"{namespace}_last_posted",
        "daily_alert_day": f"{namespace}_daily_alert_day",
        "daily_alert_count": f"{namespace}_daily_alert_count",
    }


def _repeat_window_minutes(namespace):
    return SOLD_REPEAT_WINDOW_MINUTES if namespace == "sold" else REPEAT_WINDOW_MINUTES


def _symbol_repeat_window_minutes(namespace):
    return SOLD_SYMBOL_REPEAT_WINDOW_MINUTES if namespace == "sold" else SYMBOL_REPEAT_WINDOW_MINUTES


def _was_sent_recently(flow_state, contract_symbol, namespace="flow"):
    _prune_recent_contracts(flow_state, namespace=namespace)
    return contract_symbol in (flow_state.get(_namespace_keys(namespace)["recent_contracts"]) or {})


def _remember_post(flow_state, alert, namespace="flow"):
    now_iso = _utc_iso()
    keys = _namespace_keys(namespace)
    _refresh_daily_count(flow_state, namespace=namespace)
    recent = flow_state.setdefault(keys["recent_contracts"], {})
    recent_symbols = flow_state.setdefault(keys["recent_symbols"], {})
    recent[alert["streamer_symbol"]] = {
        "posted_at": now_iso,
        "symbol": alert["symbol"],
        "contract_symbol": alert.get("contract_symbol") or alert["streamer_symbol"],
        "opt_type": alert["opt_type"],
    }
    recent_symbols[str(alert["symbol"]).strip().upper()] = {
        "posted_at": now_iso,
        "symbol": alert["symbol"],
        "contract_symbol": alert.get("contract_symbol") or alert["streamer_symbol"],
        "opt_type": alert["opt_type"],
    }
    posts = flow_state.setdefault(keys["last_posted"], [])
    posts.insert(0, _snapshot_alert(alert, posted_at=now_iso, lane=namespace if namespace != "flow" else None))
    flow_state[keys["last_posted"]] = posts[:25]
    flow_state[keys["daily_alert_count"]] = int(flow_state.get(keys["daily_alert_count"], 0)) + 1


def _prune_recent_contracts(flow_state, namespace="flow"):
    recent_key = _namespace_keys(namespace)["recent_contracts"]
    recent = flow_state.setdefault(recent_key, {})
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_repeat_window_minutes(namespace))
    keep = {}
    for contract_symbol, payload in recent.items():
        posted_at = _parse_iso(payload.get("posted_at"))
        if posted_at is None or posted_at >= cutoff:
            keep[contract_symbol] = payload
    flow_state[recent_key] = keep


def _was_symbol_sent_recently(flow_state, symbol, namespace="flow"):
    if _symbol_repeat_window_minutes(namespace) <= 0:
        return False
    _prune_recent_symbols(flow_state, namespace=namespace)
    symbol_key = _namespace_keys(namespace)["recent_symbols"]
    return str(symbol or "").strip().upper() in (flow_state.get(symbol_key) or {})


def _prune_recent_symbols(flow_state, namespace="flow"):
    recent_key = _namespace_keys(namespace)["recent_symbols"]
    recent = flow_state.setdefault(recent_key, {})
    if _symbol_repeat_window_minutes(namespace) <= 0:
        flow_state[recent_key] = recent
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_symbol_repeat_window_minutes(namespace))
    keep = {}
    for symbol, payload in recent.items():
        posted_at = _parse_iso(payload.get("posted_at"))
        if posted_at is None or posted_at >= cutoff:
            keep[str(symbol).strip().upper()] = payload
    flow_state[recent_key] = keep


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _snapshot_alert(alert, posted_at=None, lane=None):
    payload = {
        "posted_at": posted_at or _utc_iso(),
        "symbol": alert["symbol"],
        "contract_symbol": alert.get("contract_symbol") or alert["streamer_symbol"],
        "opt_type": alert["opt_type"],
        "expiry": alert["expiry_str"],
        "strike": _fmt_strike(alert["strike"]),
        "volume": int(alert["volume"]),
        "open_interest": int(alert["open_interest"]),
        "premium": round(float(alert["premium"]), 2),
    }
    if lane:
        payload["lane"] = lane
    if lane == "sold":
        payload["seller_premium"] = round(float(alert.get("seller_premium", 0.0)), 2)
        payload["buyer_premium"] = round(float(alert.get("buyer_premium", 0.0)), 2)
        payload["seller_share"] = round(float(alert.get("seller_share", 0.0)), 4)
    return payload


def _daily_alert_count(flow_state, namespace="flow"):
    keys = _namespace_keys(namespace)
    _refresh_daily_count(flow_state, namespace=namespace)
    return int(flow_state.get(keys["daily_alert_count"], 0))


def _refresh_daily_count(flow_state, namespace="flow"):
    keys = _namespace_keys(namespace)
    today = datetime.now(timezone.utc).date().isoformat()
    if flow_state.get(keys["daily_alert_day"]) == today and keys["daily_alert_count"] in flow_state:
        return

    inferred_count = 0
    for item in flow_state.get(keys["last_posted"], []):
        posted_at = str((item or {}).get("posted_at") or "")
        if posted_at.startswith(today):
            inferred_count += 1

    flow_state[keys["daily_alert_day"]] = today
    flow_state[keys["daily_alert_count"]] = inferred_count
