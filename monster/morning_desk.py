from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from monster.news_radar import get_news_radar
from monster.options_data import alpaca_enabled, fetch_stock_snapshots, _extract_stock_price
from monster.sidecar_universe import get_sidecar_symbols


HIDDEN_SYMBOLS = {"BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"}
EASTERN_TZ = ZoneInfo("America/New_York")


def render_morning_desk(config, public_base_url=None):
    board = _build_board(config)
    news = get_news_radar(config)
    base_label = _route_label(public_base_url)
    phase = _desk_phase()
    updated_at = datetime.now(timezone.utc).astimezone(EASTERN_TZ)

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <meta http-equiv="refresh" content="45">
      <title>GainzAlgo Morning Desk</title>
      <style>
        :root {{
          color-scheme: dark;
        }}
        * {{
          box-sizing: border-box;
        }}
        body {{
          margin: 0;
          font-family: "Avenir Next", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at top left, rgba(255, 184, 108, 0.22), transparent 28%),
            radial-gradient(circle at top right, rgba(253, 121, 168, 0.16), transparent 24%),
            linear-gradient(180deg, #0f1116 0%, #141821 45%, #171219 100%);
          color: #f8f4ee;
        }}
        main {{
          max-width: 1320px;
          margin: 0 auto;
          padding: 22px 18px 44px;
        }}
        a {{
          color: inherit;
          text-decoration: none;
        }}
        .topbar, .panel, .hero-card, .summary-card {{
          box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28);
        }}
        .topbar {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          padding: 14px 16px;
          border-radius: 18px;
          border: 1px solid rgba(255, 195, 113, 0.18);
          background: linear-gradient(135deg, rgba(30, 24, 26, 0.95), rgba(20, 23, 31, 0.94));
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
          background: linear-gradient(135deg, #ffb663, #ff7e6b);
          color: #241511;
          font-weight: 800;
        }}
        .brand-title {{
          font-size: 28px;
          font-weight: 800;
          letter-spacing: -0.03em;
        }}
        .brand-sub {{
          color: #d8c0b4;
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
          border: 1px solid rgba(255, 195, 113, 0.18);
          background: rgba(255, 255, 255, 0.04);
          color: #fff3df;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.03em;
        }}
        .pill.active {{
          background: linear-gradient(135deg, rgba(255, 182, 99, 0.18), rgba(255, 126, 107, 0.18));
        }}
        .hero {{
          display: grid;
          grid-template-columns: minmax(0, 1.3fr) minmax(340px, 0.9fr);
          gap: 16px;
          margin-bottom: 16px;
        }}
        .hero-card, .panel {{
          border-radius: 20px;
          border: 1px solid rgba(255, 195, 113, 0.12);
          background: linear-gradient(180deg, rgba(24, 18, 20, 0.96), rgba(17, 20, 28, 0.94));
          padding: 18px;
        }}
        .eyebrow {{
          color: #ffcb91;
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
        .hero-copy {{
          color: #e4d1c4;
          font-size: 15px;
          line-height: 1.55;
          max-width: 60ch;
        }}
        .hero-strip, .summary-grid, .watch-grid, .quick-grid {{
          display: grid;
          gap: 10px;
        }}
        .hero-strip {{
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 16px;
        }}
        .summary-grid {{
          grid-template-columns: repeat(4, minmax(0, 1fr));
        }}
        .watch-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
          margin-bottom: 16px;
        }}
        .quick-grid {{
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 14px;
        }}
        .summary-card, .stat-card, .watch-card {{
          border-radius: 16px;
          border: 1px solid rgba(255, 195, 113, 0.10);
          background: rgba(12, 14, 20, 0.88);
          padding: 14px;
        }}
        .label {{
          color: #bfa89b;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          margin-bottom: 8px;
          display: block;
        }}
        .value {{
          font-size: 30px;
          font-weight: 800;
          letter-spacing: -0.04em;
          color: #fff5e8;
        }}
        .value.small {{
          font-size: 22px;
        }}
        .muted {{
          color: #d7c4b8;
          font-size: 13px;
          line-height: 1.45;
        }}
        .status-line {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 10px;
        }}
        .status-chip {{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border-radius: 999px;
          padding: 7px 10px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 195, 113, 0.10);
          color: #fff0dc;
          font-size: 12px;
          font-weight: 700;
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
          color: #fff3e0;
        }}
        .section-note {{
          color: #cdb6a6;
          font-size: 12px;
        }}
        .watch-list {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 10px;
        }}
        .watch-chip {{
          display: inline-flex;
          align-items: center;
          gap: 8px;
          border-radius: 999px;
          padding: 7px 10px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 195, 113, 0.10);
          color: #fff5e8;
          font-size: 12px;
          font-weight: 700;
        }}
        .watch-chip span {{
          color: #d1b79d;
          font-weight: 600;
        }}
        .layout {{
          display: grid;
          grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
          gap: 16px;
          margin-bottom: 16px;
        }}
        .table {{
          border-radius: 16px;
          overflow: hidden;
          border: 1px solid rgba(255, 195, 113, 0.12);
          background: rgba(11, 13, 18, 0.88);
        }}
        .table-head, .row {{
          display: grid;
          align-items: center;
          gap: 10px;
          padding: 12px 14px;
        }}
        .table-head {{
          color: #bea699;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          border-bottom: 1px solid rgba(255, 195, 113, 0.12);
        }}
        .row {{
          border-bottom: 1px solid rgba(255, 195, 113, 0.06);
        }}
        .row:last-child {{
          border-bottom: none;
        }}
        .movers .table-head, .movers .row {{
          grid-template-columns: minmax(0, 1.1fr) minmax(72px, 0.7fr) minmax(72px, 0.7fr) minmax(82px, 0.8fr) minmax(90px, 0.8fr) minmax(0, 1fr);
        }}
        .news .table-head, .news .row {{
          grid-template-columns: minmax(0, 1.45fr) minmax(96px, 0.8fr) minmax(96px, 0.8fr);
        }}
        .symbol {{
          font-size: 15px;
          font-weight: 800;
          color: #fff5e8;
        }}
        .subline {{
          color: #cbb6aa;
          font-size: 12px;
          line-height: 1.45;
          margin-top: 3px;
        }}
        .good {{
          color: #8dffb0;
        }}
        .bad {{
          color: #ff9aa6;
        }}
        .flat {{
          color: #fbd696;
        }}
        .lane-tag {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 68px;
          padding: 7px 10px;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.04em;
          border: 1px solid rgba(255, 195, 113, 0.14);
          background: rgba(255, 255, 255, 0.05);
        }}
        .lane-tag.lotto {{
          color: #ffd38d;
        }}
        .lane-tag.swing {{
          color: #a7d8ff;
        }}
        .lane-tag.both {{
          color: #ffdbe7;
        }}
        .lane-tag.watch {{
          color: #cbb6aa;
        }}
        .headline-link:hover {{
          text-decoration: underline;
          color: #ffffff;
        }}
        .empty {{
          color: #cab7ab;
          padding: 18px 14px;
        }}
        @media (max-width: 980px) {{
          .hero, .layout {{
            grid-template-columns: 1fr;
          }}
          .summary-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
        }}
        @media (max-width: 760px) {{
          .topbar {{
            align-items: flex-start;
            flex-direction: column;
          }}
          .hero-strip, .watch-grid, .quick-grid, .summary-grid {{
            grid-template-columns: 1fr;
          }}
          .movers .table-head, .movers .row,
          .news .table-head, .news .row {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
        }}
      </style>
    </head>
    <body>
      <main>
        <section class="topbar">
          <div class="brand">
            <div class="brand-mark">☀</div>
            <div>
              <div class="brand-title">Morning Desk</div>
              <div class="brand-sub">Pre-bell watchboard for GainzAlgo • advisory only • {escape(base_label)}</div>
            </div>
          </div>
          <div class="nav">
            <a class="pill" href="/dashboard">Main Dashboard</a>
            <a class="pill active" href="/morning-desk">Morning Desk</a>
            <a class="pill" href="/contract-picker">Contract Picker</a>
            <div class="pill">{escape(phase["label"])}</div>
          </div>
        </section>

        <section class="hero">
          <section class="hero-card">
            <div class="eyebrow">Desk Bias</div>
            <div class="hero-title">{escape(board["bias_title"])}</div>
            <div class="hero-copy">{escape(board["bias_copy"])}</div>
            <div class="hero-strip">
              <div class="summary-card">
                <span class="label">Open Style</span>
                <div class="value small">{escape(board["open_style"])}</div>
              </div>
              <div class="summary-card">
                <span class="label">Best Lane</span>
                <div class="value small">{escape(board["best_lane"])}</div>
              </div>
              <div class="summary-card">
                <span class="label">Updated</span>
                <div class="value small">{escape(updated_at.strftime("%I:%M %p ET").lstrip("0"))}</div>
              </div>
            </div>
            <div class="status-line">
              <div class="status-chip">Universe {board["universe_count"]}</div>
              <div class="status-chip">Gap Up {board["gap_up_count"]}</div>
              <div class="status-chip">Gap Down {board["gap_down_count"]}</div>
              <div class="status-chip">Hot Tape {board["hot_tape_count"]}</div>
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <div class="section-title">Desk Pulse</div>
              <div class="section-note">{escape(phase["note"])}</div>
            </div>
            <div class="summary-grid">
              <div class="stat-card">
                <span class="label">Focus Queue</span>
                <div class="value small">{escape(str(board["focus_count"]))}</div>
              </div>
              <div class="stat-card">
                <span class="label">LOTTO Bench</span>
                <div class="value small">{escape(str(board["lotto_count"]))}</div>
              </div>
              <div class="stat-card">
                <span class="label">SWING Bench</span>
                <div class="value small">{escape(str(board["swing_count"]))}</div>
              </div>
              <div class="stat-card">
                <span class="label">Headlines</span>
                <div class="value small">{escape(str(news["headline_count"]))}</div>
              </div>
            </div>
            <div class="quick-grid">
              <div class="summary-card">
                <span class="label">Desk Note</span>
                <div class="muted">{escape(board["desk_note"])}</div>
              </div>
              <div class="summary-card">
                <span class="label">Opening Plan</span>
                <div class="muted">{escape(board["plan"])}</div>
              </div>
              <div class="summary-card">
                <span class="label">News Mode</span>
                <div class="muted">{escape(news["mode"])}</div>
              </div>
            </div>
          </section>
        </section>

        <section class="watch-grid">
          <section class="watch-card">
            <div class="section-head">
              <div class="section-title">LOTTO Watch</div>
              <div class="section-note">Fast names with real motion</div>
            </div>
            <div class="watch-list">{board["lotto_chips"]}</div>
            <div class="muted">{escape(board["lotto_note"])}</div>
          </section>
          <section class="watch-card">
            <div class="section-head">
              <div class="section-title">SWING Watch</div>
              <div class="section-note">Cleaner continuation names</div>
            </div>
            <div class="watch-list">{board["swing_chips"]}</div>
            <div class="muted">{escape(board["swing_note"])}</div>
          </section>
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-head">
              <div class="section-title">Mover Board</div>
              <div class="section-note">Advisory only • broader sidecar universe • does not filter live alerts</div>
            </div>
            <div class="table movers">
              <div class="table-head">
                <span>Symbol</span><span>Last</span><span>Gap</span><span>Volume</span><span>Lane</span><span>Read</span>
              </div>
              {board["rows"]}
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <div class="section-title">News Radar</div>
              <div class="section-note">{escape(news["note"])}</div>
            </div>
            <div class="table news">
              <div class="table-head">
                <span>Headline</span><span>Source</span><span>Time</span>
              </div>
              {_news_rows(news["rows"])}
            </div>
          </section>
        </section>
      </main>
    </body>
    </html>
    """


def _build_board(config):
    records = []
    symbols = [
        symbol for symbol in get_sidecar_symbols(config, limit=72)
        if symbol not in HIDDEN_SYMBOLS
    ]

    if alpaca_enabled(config) and symbols:
        try:
            snapshots = fetch_stock_snapshots(config, symbols)
        except Exception:
            snapshots = {}
        for symbol in symbols:
            record = _premarket_record(symbol, (snapshots or {}).get(symbol) or {})
            if record:
                records.append(record)

    movers = sorted(
        records,
        key=lambda item: (
            abs(item.get("gap_pct") or 0.0),
            item.get("dollar_volume") or 0.0,
            item.get("volume") or 0,
        ),
        reverse=True,
    )[:12]
    lotto_candidates = sorted(
        [item for item in records if item.get("lotto_score", 0) >= 2],
        key=lambda item: (
            item.get("lotto_score", 0),
            abs(item.get("gap_pct") or 0.0),
            item.get("dollar_volume") or 0.0,
        ),
        reverse=True,
    )[:6]
    swing_candidates = sorted(
        [item for item in records if item.get("swing_score", 0) >= 2],
        key=lambda item: (
            item.get("swing_score", 0),
            item.get("dollar_volume") or 0.0,
            abs(item.get("gap_pct") or 0.0),
        ),
        reverse=True,
    )[:6]

    hot_tape_count = sum(
        1 for item in records
        if abs(item.get("gap_pct") or 0.0) >= 1.0 and (item.get("volume") or 0) >= 250000
    )
    gap_up_count = sum(1 for item in records if (item.get("gap_pct") or 0.0) >= 1.0)
    gap_down_count = sum(1 for item in records if (item.get("gap_pct") or 0.0) <= -1.0)
    focus_symbols = _merge_focus_lists(lotto_candidates, swing_candidates, movers)

    bias_title, bias_copy, open_style, best_lane, desk_note, plan = _bias_package(
        hot_tape_count,
        gap_up_count,
        gap_down_count,
        len(lotto_candidates),
        len(swing_candidates),
    )

    return {
        "universe_count": len(records),
        "gap_up_count": gap_up_count,
        "gap_down_count": gap_down_count,
        "hot_tape_count": hot_tape_count,
        "lotto_count": len(lotto_candidates),
        "swing_count": len(swing_candidates),
        "focus_count": len(focus_symbols),
        "bias_title": bias_title,
        "bias_copy": bias_copy,
        "open_style": open_style,
        "best_lane": best_lane,
        "desk_note": desk_note,
        "plan": plan,
        "lotto_note": _lane_note("LOTTO", lotto_candidates),
        "swing_note": _lane_note("SWING", swing_candidates),
        "lotto_chips": _watch_chips("LOTTO", lotto_candidates, empty_text="Waiting on tape"),
        "swing_chips": _watch_chips("SWING", swing_candidates, empty_text="Waiting on tape"),
        "rows": "".join(_mover_row(item) for item in movers) or (
            "<div class='empty'>Morning Desk needs Alpaca stock snapshots and live market data.</div>"
        ),
    }


def _premarket_record(symbol, snapshot):
    price = _extract_stock_price(snapshot)
    if price in (None, 0):
        return None

    prev_daily = snapshot.get("prevDailyBar") or snapshot.get("prev_daily_bar") or {}
    prev_close = _safe_float(prev_daily.get("c") if "c" in prev_daily else prev_daily.get("close"))
    if prev_close in (None, 0):
        return None

    daily_bar = snapshot.get("dailyBar") or snapshot.get("daily_bar") or {}
    minute_bar = snapshot.get("minuteBar") or snapshot.get("minute_bar") or {}
    volume = _safe_int(daily_bar.get("v") if "v" in daily_bar else daily_bar.get("volume")) or 0
    minute_volume = _safe_int(minute_bar.get("v") if "v" in minute_bar else minute_bar.get("volume")) or 0
    gap_pct = round(((float(price) - float(prev_close)) / float(prev_close)) * 100.0, 2)
    dollar_volume = round(float(price) * float(volume), 2) if volume else 0.0

    lotto_score = 0
    if abs(gap_pct) >= 1.25:
        lotto_score += 1
    if abs(gap_pct) >= 2.5:
        lotto_score += 1
    if volume >= 250000:
        lotto_score += 1
    if dollar_volume >= 15000000:
        lotto_score += 1

    swing_score = 0
    if 0.75 <= abs(gap_pct) <= 4.5:
        swing_score += 1
    if volume >= 500000:
        swing_score += 1
    if dollar_volume >= 25000000:
        swing_score += 1
    if float(price) >= 20:
        swing_score += 1

    return {
        "symbol": symbol,
        "price": price,
        "gap_pct": gap_pct,
        "volume": volume,
        "minute_volume": minute_volume,
        "dollar_volume": dollar_volume,
        "lotto_score": lotto_score,
        "swing_score": swing_score,
        "lane_fit": _lane_fit_label(lotto_score, swing_score),
        "read": _mover_read(gap_pct, minute_volume, lotto_score, swing_score),
    }


def _lane_fit_label(lotto_score, swing_score):
    if lotto_score >= 3 and swing_score >= 3:
        return "BOTH"
    if lotto_score >= swing_score and lotto_score >= 2:
        return "LOTTO"
    if swing_score >= 2:
        return "SWING"
    return "WATCH"


def _mover_read(gap_pct, minute_volume, lotto_score, swing_score):
    gap_pct = float(gap_pct or 0.0)
    minute_volume = int(minute_volume or 0)
    if lotto_score >= 3 and gap_pct >= 0:
        return "Fast upside tape"
    if lotto_score >= 3 and gap_pct < 0:
        return "Fast downside tape"
    if swing_score >= 3 and minute_volume >= 5000:
        return "Clean continuation"
    if abs(gap_pct) < 1.0:
        return "Watch for ignition"
    return "Keep on radar"


def _mover_row(item):
    gap_text = _fmt_signed_pct(item.get("gap_pct"))
    gap_class = _pnl_class(item.get("gap_pct"))
    lane_fit = str(item.get("lane_fit") or "WATCH").upper()
    lane_class = lane_fit.lower()
    picker_style = "SWING" if lane_fit == "SWING" else "LOTTO"
    picker_href = _picker_href(str(item.get("symbol") or ""), picker_style, item.get("gap_pct"))
    return f"""
    <div class="row">
      <div>
        <div class="symbol"><a class="headline-link" href="{escape(picker_href)}">{escape(str(item.get("symbol") or "N/A"))}</a></div>
        <div class="subline">Min {_fmt_compact_int(item.get("minute_volume"))} • DV {_fmt_money_compact(item.get("dollar_volume"))}</div>
      </div>
      <div>{escape(_fmt(item.get("price")))}</div>
      <div><strong class="{gap_class}">{escape(gap_text)}</strong></div>
      <div>{escape(_fmt_compact_int(item.get("volume")))}</div>
      <div><span class="lane-tag {lane_class}">{escape(lane_fit)}</span></div>
      <div class="subline">{escape(str(item.get("read") or "Watchlist"))}</div>
    </div>
    """


def _bias_package(hot_tape_count, gap_up_count, gap_down_count, lotto_count, swing_count):
    if gap_up_count >= gap_down_count + 4 and hot_tape_count >= 5:
        return (
            "Risk-On Opening Tape",
            "Breadth is leaning higher and enough names are actually moving. This is the kind of board where fast upside names deserve early attention, but you still want the contract to be clean.",
            "Open-drive focus",
            "LOTTO" if lotto_count >= swing_count else "BOTH",
            "Plenty of motion. Let the best names separate instead of forcing second-tier setups.",
            "Favor the first clean break or reclaim on names already holding premarket strength.",
        )
    if gap_down_count >= gap_up_count + 4 and hot_tape_count >= 5:
        return (
            "Risk-Off Opening Tape",
            "Pressure is broad enough that downside continuation can matter right away. Treat weak bounces as suspect and let the tape prove when buyers are actually stepping back in.",
            "Fade weak bounces",
            "LOTTO" if lotto_count >= swing_count else "BOTH",
            "Downside participation is real. Stick with cleaner leaders instead of random catches.",
            "Prioritize failed bounces and weak relative names rather than bottom fishing the first flush.",
        )
    if hot_tape_count >= 6:
        return (
            "Fast Two-Way Tape",
            "There is enough motion for opportunity, but it is not cleanly one-sided. This is usually a better environment for disciplined picks than broad aggression.",
            "Selective aggression",
            "BOTH",
            "Tape has energy, but it is mixed. Respect confirms and avoid chasing the third move.",
            "Use the watchlists to narrow focus and let one or two clean names do the work.",
        )
    if swing_count > lotto_count:
        return (
            "Calmer Continuation Board",
            "The tape is not lighting up with huge gaps, but there are enough orderly names to keep a swing mindset on the table. This is where patience matters more than speed.",
            "Continuation setups",
            "SWING",
            "Cleaner names matter more than raw speed here. Avoid forcing lotto behavior onto a quieter board.",
            "Wait for orderly pullbacks and continuation entries instead of hunting excitement.",
        )
    return (
        "Selective Open",
        "The board is not hot enough to justify spraying alerts across the screen. A smaller focus list and better entries will usually beat chasing every little move.",
        "Patience first",
        "LOTTO" if lotto_count else "WATCH",
        "Quiet tape. Let the first real leader prove itself before scaling into anything aggressive.",
        "Focus on the best two or three names and ignore the rest until volume actually shows up.",
    )


def _lane_note(lane, items):
    if not items:
        if lane == "LOTTO":
            return "No standout fast names yet. Let the open print before forcing a lotto read."
        return "No clean continuation names yet. Better to stay patient than manufacture a swing."

    leader = items[0]
    if lane == "LOTTO":
        return (
            f"{leader['symbol']} is pacing the fast board with {abs(leader.get('gap_pct') or 0):.2f}% motion "
            "and enough participation to matter."
        )
    return (
        f"{leader['symbol']} has the cleanest continuation mix right now with "
        f"{_fmt_money_compact(leader.get('dollar_volume'))} of dollar volume behind it."
    )


def _watch_chips(lane, items, empty_text):
    if not items:
        return f"<div class='watch-chip'>{escape(empty_text)}</div>"
    chips = []
    for item in items:
        href = _picker_href(item["symbol"], lane, item.get("gap_pct"))
        chips.append(
            f"<a class='watch-chip' href='{escape(href)}'>{escape(item['symbol'])}<span>{escape(_fmt_signed_pct(item.get('gap_pct')))}</span></a>"
        )
    return "".join(chips)


def _merge_focus_lists(lotto_candidates, swing_candidates, movers):
    seen = []
    for pool in (lotto_candidates, swing_candidates, movers):
        for item in pool:
            symbol = str(item.get("symbol") or "").strip().upper()
            if symbol and symbol not in seen:
                seen.append(symbol)
    return seen[:10]


def _picker_href(symbol, lane, gap_pct):
    lane = "SWING" if str(lane or "").upper() == "SWING" else "LOTTO"
    contract_side = "PUT" if float(gap_pct or 0.0) < 0 else "CALL"
    return f"/contract-picker?symbol={escape(str(symbol or '').upper())}&style={lane}&contract_side={contract_side}"


def _news_rows(items):
    if not items:
        return "<div class='empty'>No live headlines available yet.</div>"
    rows = []
    for item in items[:8]:
        rows.append(
            f"""
            <div class="row">
              <div><a class="headline-link" href="{escape(str(item.get('link') or '#'))}" target="_blank" rel="noopener noreferrer">{escape(str(item.get('title') or 'Untitled headline'))}</a></div>
              <div>{escape(str(item.get('source') or 'News'))}</div>
              <div>{escape(_short_time(item.get('published_at')))}</div>
            </div>
            """
        )
    return "".join(rows)


def _route_label(public_base_url):
    base = str(public_base_url or "").strip()
    if "onrender.com" in base:
        return "Render Hosted"
    if "trycloudflare.com" in base:
        return "Cloudflare Tunnel"
    return "Hosted Desk"


def _desk_phase():
    now_et = datetime.now(timezone.utc).astimezone(EASTERN_TZ)
    minutes = now_et.hour * 60 + now_et.minute
    if minutes < (9 * 60 + 30):
        return {"label": "Pre-Bell", "note": "Use this to narrow the watchlist, not to chase."}
    if minutes < (10 * 60 + 30):
        return {"label": "Open Drive", "note": "Let the first clean names prove they can hold."}
    if minutes < (15 * 60):
        return {"label": "Live Session", "note": "Stay selective. The board matters more than random noise."}
    return {"label": "After Hours", "note": "Use this to prep tomorrow's focus names."}


def _fmt(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_signed_pct(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
        return f"{number:+.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_compact_int(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(int(number))


def _fmt_money_compact(value):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000_000:
        return f"${number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"${number / 1_000:.1f}K"
    return f"${number:.0f}"


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
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _short_time(value):
    if not value:
        return "Never"
    text = str(value)
    if "T" in text:
        text = text.replace("T", " ")
    return text[:19]


def _pnl_class(value):
    if value is None:
        return "flat"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "flat"
    if number > 0:
        return "good"
    if number < 0:
        return "bad"
    return "flat"
