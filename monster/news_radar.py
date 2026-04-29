from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import threading
import time
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
_MONITOR_THREAD = None
_MONITOR_LOCK = threading.Lock()
NEWS_STATE_FILENAME = "news_radar_state.json"


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


def ensure_news_monitor_running(config):
    global _MONITOR_THREAD
    with _MONITOR_LOCK:
        if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
            return
        _MONITOR_THREAD = threading.Thread(target=_news_monitor_loop, args=(config,), daemon=True)
        _MONITOR_THREAD.start()


def post_news_radar(config):
    news_cfg = config.get("news") or {}
    if not news_cfg.get("enabled", True):
        return {"posted": 0, "reason": "disabled"}

    webhook = str(news_cfg.get("discord_webhook") or "").strip()
    if not webhook:
        return {"posted": 0, "reason": "webhook_missing"}

    payload = get_news_radar(config)
    headlines = payload.get("rows") or []
    state = _load_post_state(config)
    posted_signatures = set(state.get("posted_signatures") or [])
    to_post = []
    for item in headlines:
        signature = _headline_signature(item)
        if not signature or signature in posted_signatures:
            continue
        if not _is_recent_headline(item.get("published_at")):
            continue
        to_post.append(item)

    posted = 0
    for item in to_post[:2]:
        if _post_headline(webhook, item):
            signature = _headline_signature(item)
            posted_signatures.add(signature)
            state["posted_signatures"] = list(posted_signatures)[-250:]
            state["last_posted_at"] = datetime.now(timezone.utc).isoformat()
            posted += 1

    _save_post_state(config, state)
    return {"posted": posted, "reason": "ok" if posted else "no_new_items"}


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


def _news_monitor_loop(config):
    while True:
        try:
            post_news_radar(config)
        except Exception:
            pass
        refresh_seconds = max(30, int((config.get("news") or {}).get("refresh_seconds") or DEFAULT_REFRESH_SECONDS))
        time.sleep(refresh_seconds)


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


def _headline_signature(item):
    if not item:
        return None
    title = str(item.get("title") or "").strip()
    link = str(item.get("link") or "").strip()
    if not title or not link:
        return None
    return f"{title}|{link}"


def _state_path(config):
    return Path(config["data_dir"]) / NEWS_STATE_FILENAME


def _load_post_state(config):
    path = _state_path(config)
    if not path.exists():
        return {"posted_signatures": [], "last_posted_at": None}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"posted_signatures": [], "last_posted_at": None}


def _save_post_state(config, state):
    try:
        _state_path(config).write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _is_recent_headline(value, max_age_hours=6):
    parsed = _parse_datetime(value)
    if not parsed:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    return parsed >= cutoff


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _post_headline(webhook, item):
    title = str(item.get("title") or "").strip()
    link = str(item.get("link") or "").strip()
    source = str(item.get("source") or "News")
    published_at = _short_time(item.get("published_at"))
    payload = {
        "username": "GainzAlgo News",
        "embeds": [
            {
                "author": {"name": "GainzAlgo Monster • News Radar"},
                "title": title[:256],
                "url": link,
                "description": f"{source} • {published_at}",
                "color": 0x4FC3F7,
                "footer": {"text": "Official feeds" if item.get("mode") == "official" else "Premium feed"},
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        webhook,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            return 200 <= getattr(resp, "status", 204) < 300
    except Exception:
        return False


def _short_time(value):
    if not value:
        return "Unknown time"
    text = str(value).replace("T", " ")
    return text[:16]


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
