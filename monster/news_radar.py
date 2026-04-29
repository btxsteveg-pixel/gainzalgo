from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import threading
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
import xml.etree.ElementTree as ET


USER_AGENT = "GainzAlgoMonster/2.0"
DEFAULT_REFRESH_SECONDS = 90
DEFAULT_ITEM_LIMIT = 8

RSS_FEEDS = [
    {
        "source": "SEC Press",
        "mode": "official",
        "url": "https://www.sec.gov/news/pressreleases.rss",
    },
    {
        "source": "Nasdaq Markets",
        "mode": "official",
        "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    },
    {
        "source": "Nasdaq Stocks",
        "mode": "official",
        "url": "https://www.nasdaq.com/feed/rssoutbound?category=Stocks",
    },
]

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def get_news_radar(config):
    news_cfg = config.get("news") or {}
    if not news_cfg.get("enabled", True):
        return _empty_payload("News radar disabled.")

    refresh_seconds = max(30, int(news_cfg.get("refresh_seconds") or DEFAULT_REFRESH_SECONDS))
    cache_key = (
        bool(news_cfg.get("benzinga_api_key")),
        refresh_seconds,
    )
    now = datetime.now(timezone.utc)

    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and cached.get("expires_at") and cached["expires_at"] > now:
            return cached["payload"]

    payload = _build_payload(news_cfg)
    with _CACHE_LOCK:
        _CACHE[cache_key] = {
            "expires_at": now + timedelta(seconds=refresh_seconds),
            "payload": payload,
        }
    return payload


def _build_payload(news_cfg):
    items = []
    source_labels = []

    benzinga_key = news_cfg.get("benzinga_api_key")
    if benzinga_key:
        benzinga_items = _fetch_benzinga_news(benzinga_key)
        if benzinga_items:
            items.extend(benzinga_items)
            source_labels.append("Benzinga")

    for feed in RSS_FEEDS:
        feed_items = _fetch_rss(feed["url"], feed["source"], feed["mode"])
        if feed_items:
            items.extend(feed_items)
            source_labels.append(feed["source"])

    deduped = []
    seen = set()
    for item in sorted(items, key=lambda row: row.get("published_at") or "", reverse=True):
        signature = (item.get("title"), item.get("link"))
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(item)

    headlines = deduped[:DEFAULT_ITEM_LIMIT]
    latest = headlines[0] if headlines else None
    mode = "Premium + official" if benzinga_key else "Official feeds"
    note = "Faster tape with Benzinga key" if not benzinga_key else "Premium feed active"
    if not headlines:
        note = "No live headlines available right now."

    return {
        "mode": mode,
        "headline_count": len(headlines),
        "source_count": len(set(source_labels)),
        "last_published": latest.get("published_at") if latest else None,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "rows": headlines,
    }


def _empty_payload(note):
    return {
        "mode": "Disabled",
        "headline_count": 0,
        "source_count": 0,
        "last_published": None,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "rows": [],
    }


def _fetch_benzinga_news(api_key):
    params = {
        "token": api_key,
        "displayOutput": "headline",
        "pagesize": "8",
    }
    url = "https://api.benzinga.com/api/v2/news?" + urllib_parse.urlencode(params)
    payload = _get_json(url)
    items = payload if isinstance(payload, list) else payload.get("news", []) if isinstance(payload, dict) else []
    results = []
    for item in items or []:
        published_at = item.get("updated") or item.get("created")
        results.append(
            {
                "source": "Benzinga",
                "mode": "premium",
                "title": str(item.get("title") or "").strip(),
                "link": str(item.get("url") or "").strip(),
                "published_at": _normalize_datetime(published_at),
            }
        )
    return [item for item in results if item["title"] and item["link"]]


def _fetch_rss(url, source, mode):
    req = urllib_request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib_request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
    except Exception:
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    items = []
    for node in root.findall(".//item")[:8]:
        title = _node_text(node, "title")
        link = _node_text(node, "link")
        published = _node_text(node, "pubDate") or _node_text(node, "date")
        items.append(
            {
                "source": source,
                "mode": mode,
                "title": title,
                "link": link,
                "published_at": _normalize_datetime(published),
            }
        )
    return [item for item in items if item["title"] and item["link"]]


def _get_json(url):
    req = urllib_request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib_error.HTTPError, urllib_error.URLError, json.JSONDecodeError, TimeoutError):
        return {}


def _node_text(node, tag):
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return str(child.text).strip()


def _normalize_datetime(value):
    if not value:
        return None
    try:
        if "T" in str(value):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        return parsedate_to_datetime(str(value)).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return None
