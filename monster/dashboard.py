from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import re

from monster.options_data import attach_live_pnl, alpaca_enabled, fetch_stock_snapshots, _extract_stock_price
from monster.news_radar import get_news_radar
from monster.store import load_all_states
try:
    from monster.paper_trader import get_paper_summary
    _PAPER_TRADER_AVAILABLE = True
except Exception:
    _PAPER_TRADER_AVAILABLE = False
    def get_paper_summary(config):
        return {"open_positions": [], "recent_closed": [], "all_closed_positions": [], "stats": {}}


DASHBOARD_HIDDEN_SYMBOLS = {"BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"}


def render_dashboard(config, public_base_url=None):
    states = load_all_states(config)
    states = attach_live_pnl(config, states)
    display_states = _dashboard_states(states)
    paper = get_paper_summary(config) if _PAPER_TRADER_AVAILABLE else {"open_positions": [], "recent_closed": [], "all_closed_positions": [], "stats": {}}
    paper_closed_positions = paper.get("all_closed_positions") or []
    paper_open_positions = paper.get("open_positions") or []
    paper_stats = paper.get("stats") or {}

    alerts = _collect_alerts(display_states)
    latest_alert = alerts[-1] if alerts else None
    last_sent_alert = _latest_discord_alert(alerts)
    latest_error = _latest_webhook_error(states)
    latest_paper_error = _latest_paper_error(states)
    today = _summary_window(alerts, paper_closed_positions, timedelta(days=1))
    week = _summary_window(alerts, paper_closed_positions, timedelta(days=7))
    leaderboard = _leaderboard(alerts, paper_closed_positions)
    risk = _risk_snapshot(states, alerts, paper_closed_positions)
    lane_analytics = _lane_analytics(alerts, paper_open_positions, paper_closed_positions)
    execution_funnel = _execution_funnel(alerts, paper_open_positions, paper_closed_positions)
    webhook_base_url = _public_webhook_base_url(config, public_base_url)
    flow_diagnostics = _flow_diagnostics(config)
    ops_rows = _ops_health_rows(
        config,
        alerts,
        paper_open_positions,
        paper_closed_positions,
        latest_error,
        latest_paper_error,
        webhook_base_url,
        flow_diagnostics,
    )
    settings_rows = _settings_rows(config)
    premarket = _premarket_advisory(config)
    news = get_news_radar(config)
    audit_rows = _alert_audit_rows(states, paper_open_positions, paper_closed_positions)
    swing_monitor = _swing_trigger_monitor(states, paper_open_positions, paper_closed_positions)
    health = _health_snapshot(config, display_states, webhook_base_url)
    focus_list = _focus_list(alerts, leaderboard)

    total_alerts = len(alerts)
    total_sent = sum(1 for alert in alerts if alert.get("discord_sent"))
    total_closed_pnl = float(paper_stats.get("total_pnl", 0.0) or 0.0)
    last_seen = max(
        (
            item.get("time")
            for item in alerts
            if item.get("time")
        ),
        default="Never",
    )

    style_cards = "".join(
        _style_card(style, state, lane_analytics.get(style, {}))
        for style, state in display_states.items()
    )
    recent_closed_for_dashboard = paper.get("recent_closed") or []
    closed_rows = "".join(_closed_trade_row(item) for item in recent_closed_for_dashboard[:8]) or (
        "<div class='empty'>No closed trades yet</div>"
    )
    leaderboard_rows = "".join(_leaderboard_row(item) for item in leaderboard) or (
        "<div class='empty'>Leaderboard wakes up after more alerts land</div>"
    )
    lane_rows = "".join(_lane_analytics_row(item) for item in lane_analytics.values()) or (
        "<div class='empty'>Lane analytics will populate after paper trades close.</div>"
    )
    recap_lines = _recap_lines(today, week, latest_alert, risk)

    hero = _hero(latest_alert)

    paper_section = _paper_section(paper)

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <meta http-equiv="refresh" content="15">
      <title>GainzAlgo Monster</title>
      <style>
        :root {{
          color-scheme: dark;
          --bg: #08090b;
          --panel: rgba(18, 19, 23, 0.9);
          --panel-strong: rgba(23, 24, 29, 0.96);
          --line: rgba(255, 255, 255, 0.1);
          --line-red: rgba(226, 34, 62, 0.24);
          --text: #f7f7f8;
          --muted: #aaa2a7;
          --red: #ff3f5d;
          --red-soft: rgba(255, 63, 93, 0.16);
          --green: #55f08a;
          --amber: #ffbf47;
          --cyan: #7bd7ff;
        }}
        * {{
          box-sizing: border-box;
        }}
        body {{
          margin: 0;
          font-family: Inter, Arial, sans-serif;
          background:
            linear-gradient(115deg, rgba(226, 34, 62, 0.16), transparent 34%),
            linear-gradient(245deg, rgba(123, 215, 255, 0.08), transparent 30%),
            linear-gradient(180deg, #07080a 0%, #101116 46%, #08090b 100%);
          color: var(--text);
        }}
        body::before {{
          content: "";
          position: fixed;
          inset: 0;
          pointer-events: none;
          background-image:
            linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.026) 1px, transparent 1px);
          background-size: 56px 56px;
          mask-image: linear-gradient(180deg, rgba(0,0,0,.72), transparent 78%);
        }}
        main {{
          display: flex;
          flex-direction: column;
          position: relative;
          z-index: 1;
          max-width: 1280px;
          margin: 0 auto;
          padding: 18px 18px 52px;
        }}
        .topbar, .panel, .hero-card, .card, .summary div {{
          box-shadow: 0 18px 42px rgba(0, 0, 0, 0.38);
        }}
        .topbar {{
          position: sticky;
          top: 10px;
          z-index: 5;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 16px;
          padding: 14px 16px;
          background:
            linear-gradient(90deg, rgba(255, 63, 93, 0.12), transparent 42%),
            rgba(15, 16, 20, 0.92);
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 8px;
          backdrop-filter: blur(10px);
        }}
        .topbar::before {{
          content: "";
          position: absolute;
          inset: 0;
          border-radius: inherit;
          border-top: 1px solid rgba(255, 255, 255, 0.2);
          pointer-events: none;
        }}
        .brand {{
          display: flex;
          align-items: center;
          gap: 12px;
        }}
        .brand-mark {{
          width: 36px;
          height: 36px;
          border-radius: 8px;
          background:
            linear-gradient(135deg, #ff465f 0%, #9c1026 100%);
          box-shadow: 0 0 0 1px rgba(255,255,255,.15), 0 10px 28px rgba(255, 63, 93, 0.3);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 17px;
          font-weight: 800;
          color: white;
        }}
        .sub {{
          margin-top: 8px;
          color: var(--muted);
          font-size: 14px;
        }}
        .ticker-strip, .health-row, .desk-status {{
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }}
        .ticker-pill, .chip, .status-pill {{
          padding: 6px 10px;
          border-radius: 8px;
          background: rgba(255, 255, 255, 0.055);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: #f4e8eb;
          font-size: 12px;
          text-decoration: none;
        }}
        a.ticker-pill:hover {{
          border-color: rgba(255, 63, 93, 0.45);
          background: rgba(255, 63, 93, 0.12);
        }}
        .chip.good {{ color: var(--green); border-color: rgba(85,240,138,.28); }}
        .chip.warn {{ color: var(--amber); border-color: rgba(255,191,71,.28); }}
        .chip.bad {{ color: #ff9aa7; border-color: rgba(255,154,167,.28); }}
        .status-pill {{
          color: #f6d9de;
        }}
        .status-pill strong {{
          color: #ffffff;
          font-weight: 700;
        }}
        .hero {{
          display: grid;
          grid-template-columns: 1.35fr 1fr;
          gap: 16px;
          margin-bottom: 16px;
        }}
        .cockpit {{
          display: grid;
          grid-template-columns: repeat(12, minmax(0, 1fr));
          gap: 12px;
          margin-bottom: 16px;
        }}
        .metric-card {{
          grid-column: span 2;
          position: relative;
          overflow: hidden;
          background:
            linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.02)),
            var(--panel-strong);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 15px 16px;
          min-height: 104px;
        }}
        .metric-card::before {{
          content: "";
          position: absolute;
          inset: 0 0 auto;
          height: 3px;
          background: rgba(255, 255, 255, 0.16);
        }}
        .metric-card.primary {{
          grid-column: span 2;
          border-color: rgba(85, 240, 138, 0.35);
          background:
            linear-gradient(135deg, rgba(85,240,138,.16), transparent 52%),
            linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.02)),
            var(--panel-strong);
        }}
        .metric-card.primary::before {{
          background: linear-gradient(90deg, var(--green), rgba(85,240,138,.2));
        }}
        .metric-card.warning {{
          border-color: rgba(255, 191, 71, 0.34);
        }}
        .metric-card.warning::before {{
          background: linear-gradient(90deg, var(--amber), rgba(255,191,71,.15));
        }}
        .metric-card.win::before {{
          background: linear-gradient(90deg, var(--cyan), rgba(123,215,255,.12));
        }}
        .metric-card.compact {{
          grid-column: span 2;
        }}
        .metric-card.compact .metric-value {{
          font-size: 26px;
        }}
        .metric-label {{
          color: #bdb6ba;
          font-size: 11px;
          line-height: 1.25;
          margin-bottom: 8px;
          text-transform: uppercase;
        }}
        .metric-value {{
          display: block;
          color: #ffffff;
          font-size: 26px;
          font-weight: 800;
          line-height: 1.05;
          overflow-wrap: anywhere;
        }}
        .metric-note {{
          color: #9f969b;
          font-size: 11px;
          line-height: 1.35;
          margin-top: 7px;
        }}
        .hero-card, .panel, .card, .summary div {{
          background:
            linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.018)),
            var(--panel);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 16px;
          backdrop-filter: blur(12px);
        }}
        .hero-card {{
          position: relative;
          overflow: hidden;
          min-height: 250px;
          background:
            linear-gradient(135deg, rgba(255,63,93,.22), rgba(18,19,23,.98) 42%),
            var(--panel-strong);
          border-color: rgba(255, 63, 93, 0.3);
        }}
        .hero-card::after {{
          content: "";
          position: absolute;
          inset: auto 16px 14px 16px;
          height: 1px;
          background: linear-gradient(90deg, rgba(255,63,93,.65), transparent);
        }}
        .hero-title {{
          font-size: 13px;
          text-transform: uppercase;
          letter-spacing: .05em;
          color: #f0c4cb;
          margin-bottom: 8px;
        }}
        .hero-symbol {{
          font-size: 48px;
          font-weight: 800;
          line-height: 1;
          margin-bottom: 10px;
        }}
        .hero-meta {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 12px;
        }}
        .hero-grid, .summary {{
          display: grid;
          gap: 10px;
        }}
        .hero-grid {{
          grid-template-columns: repeat(4, minmax(0, 1fr));
        }}
        .summary {{
          grid-template-columns: repeat(3, minmax(120px, 1fr));
        }}
        .summary span, .stat span, .grid-stat span, .table-head span {{
          display: block;
          color: #b8a5aa;
          font-size: 12px;
          margin-bottom: 6px;
          text-transform: uppercase;
        }}
        .summary strong {{
          font-size: 22px;
        }}
        .stat, .grid-stat {{
          background: rgba(8, 9, 12, 0.72);
          border: 1px solid rgba(255, 255, 255, 0.075);
          border-radius: 8px;
          padding: 12px;
        }}
        .grid-stat strong {{
          font-size: 18px;
        }}
        .layout {{
          display: grid;
          grid-template-columns: 1.2fr 1fr;
          gap: 16px;
          margin-bottom: 16px;
        }}
        .grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
          gap: 16px;
          margin-bottom: 16px;
        }}
        .card {{
          position: relative;
          overflow: hidden;
        }}
        .card.lotto {{
          border-top: 3px solid var(--red);
          background:
            linear-gradient(135deg, rgba(255,63,93,.1), transparent 42%),
            var(--panel);
        }}
        .card.swing {{
          border-top: 3px solid var(--cyan);
          background:
            linear-gradient(135deg, rgba(123,215,255,.09), transparent 42%),
            var(--panel);
        }}
        .card-head {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 14px;
          gap: 10px;
        }}
        .eyebrow {{
          color: #d6b0b7;
          font-size: 12px;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }}
        .headline {{
          font-size: 28px;
          font-weight: 700;
        }}
        .tag {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 64px;
          height: 28px;
          padding: 0 10px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 700;
          background: rgba(255, 255, 255, 0.09);
          color: #f4f4f5;
          border: 1px solid rgba(255,255,255,.08);
        }}
        .tag.buy {{ background: rgba(255, 63, 93, 0.18); color: #ff9caa; border-color: rgba(255,63,93,.22); }}
        .tag.sell {{ background: rgba(123, 215, 255, 0.13); color: #d9f4ff; border-color: rgba(123,215,255,.2); }}
        .metrics, .strip, .position-grid {{
          display: grid;
          gap: 8px;
          margin-bottom: 12px;
        }}
        .metrics {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
        .strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
        .position-grid {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
        .metrics div, .strip div, .position-grid div, .hero-grid div {{
          background: rgba(8, 9, 12, 0.72);
          border: 1px solid rgba(255, 255, 255, 0.075);
          border-radius: 8px;
          padding: 10px;
        }}
        .metrics span, .strip span, .position-grid span, .hero-grid span {{
          display: block;
          color: #a99ba1;
          font-size: 11px;
          margin-bottom: 6px;
          text-transform: uppercase;
        }}
        .metrics strong {{
          font-size: 18px;
        }}
        strong.up {{ color: #67ff95; }}
        strong.down {{ color: #ff8b9a; }}
        strong.warn {{ color: #ffd37e; }}
        .section-title {{
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 700;
          margin-bottom: 8px;
          color: #fff2f4;
          text-transform: uppercase;
          letter-spacing: .04em;
        }}
        .section-title::before {{
          content: "";
          display: inline-block;
          width: 4px;
          height: 14px;
          border-radius: 8px;
          background: linear-gradient(180deg, var(--red), var(--amber));
        }}
        .table {{
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 8px;
          overflow: hidden;
          background: rgba(6, 7, 10, 0.78);
        }}
        .table-head, .row {{
          display: grid;
          gap: 8px;
          align-items: center;
          padding: 10px 12px;
        }}
        .table-head {{
          color: #b9aeb2;
          font-size: 11px;
          text-transform: uppercase;
          border-bottom: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.035);
        }}
        .row {{
          border-bottom: 1px solid rgba(255,255,255,0.055);
          transition: background .16s ease, transform .16s ease;
        }}
        .row:hover {{
          background: rgba(255, 255, 255, 0.035);
        }}
        .row:last-child {{
          border-bottom: none;
        }}
        .alert-table .table-head, .alert-table .row {{
          grid-template-columns: minmax(0, 1.8fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr);
        }}
        .closed-table .table-head, .closed-table .row {{
          grid-template-columns: minmax(0, 1.2fr) minmax(72px, .8fr) minmax(88px, .9fr) minmax(72px, .8fr) minmax(92px, .9fr);
        }}
        .leader-table .table-head, .leader-table .row {{
          grid-template-columns: minmax(0, 1.2fr) minmax(72px, .8fr) minmax(72px, .8fr) minmax(92px, .9fr);
        }}
        .audit-table .table-head, .audit-table .row {{
          grid-template-columns: minmax(0, 1.1fr) minmax(72px, .7fr) minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1.1fr) minmax(96px, .8fr);
        }}
        .monitor-symbol-table .table-head, .monitor-symbol-table .row {{
          grid-template-columns: minmax(0, 1.2fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(72px, .7fr);
        }}
        .reject-table .table-head, .reject-table .row {{
          grid-template-columns: minmax(0, 1.6fr) minmax(72px, .7fr) minmax(96px, .8fr);
        }}
        .scanner-table .table-head, .scanner-table .row {{
          grid-template-columns: minmax(0, 1.2fr) minmax(72px, .7fr) minmax(72px, .7fr) minmax(96px, .8fr) minmax(0, 1fr);
        }}
        .news-table .table-head, .news-table .row {{
          grid-template-columns: minmax(0, 1.4fr) minmax(96px, .8fr) minmax(96px, .8fr);
        }}
        .flow-post-table .table-head, .flow-post-table .row {{
          grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr) minmax(96px, .8fr) minmax(96px, .8fr) minmax(0, 1fr);
        }}
        .alert-meta, .muted {{
          color: #aaa0a5;
          font-size: 12px;
        }}
        .audit-flow {{
          color: #f3dfe3;
          font-size: 12px;
          line-height: 1.45;
        }}
        .audit-note {{
          color: #c1a6ab;
          font-size: 12px;
          line-height: 1.4;
        }}
        .alert-symbol {{
          font-size: 14px;
          font-weight: 700;
        }}
        .recap-box {{
          white-space: pre-wrap;
          line-height: 1.5;
          font-size: 14px;
          color: #eee7ea;
        }}
        .diagnostics {{
          order: 50;
          margin-top: 4px;
          margin-bottom: 16px;
          border: 1px solid rgba(255, 255, 255, 0.09);
          border-radius: 8px;
          background: rgba(20, 20, 25, 0.82);
        }}
        .diagnostics summary {{
          cursor: pointer;
          padding: 14px 16px;
          color: #fff2f4;
          font-size: 13px;
          font-weight: 700;
          letter-spacing: .04em;
          text-transform: uppercase;
        }}
        .diagnostics .diagnostic-body {{
          padding: 0 16px 16px;
        }}
        .paper-stat-cards {{
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 10px;
          margin-bottom: 16px;
        }}
        .paper-lane-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
          gap: 16px;
        }}
        .paper-lane-metrics {{
          display: grid;
          grid-template-columns: repeat(6, 1fr);
          gap: 8px;
          margin-bottom: 14px;
        }}
        .controls {{
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 10px;
        }}
        .controls form {{
          margin: 0;
        }}
        .controls button {{
          appearance: none;
          border: 1px solid rgba(206, 17, 38, 0.22);
          background: rgba(30, 30, 36, 0.96);
          color: #f4f4f5;
          border-radius: 8px;
          padding: 8px 10px;
          font-size: 12px;
          cursor: pointer;
        }}
        .controls button:hover {{
          background: rgba(206, 17, 38, 0.16);
        }}
        .empty {{
          color: #a99da2;
          padding: 14px 12px;
        }}
        @media (max-width: 940px) {{
          .hero, .layout {{
            grid-template-columns: 1fr;
          }}
          .summary {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .cockpit {{
            grid-template-columns: repeat(6, minmax(0, 1fr));
          }}
          .metric-card, .metric-card.primary, .metric-card.warning, .metric-card.compact {{
            grid-column: span 2;
          }}
          .paper-stat-cards {{
            grid-template-columns: repeat(3, minmax(0, 1fr));
          }}
          .paper-lane-metrics {{
            grid-template-columns: repeat(3, minmax(0, 1fr));
          }}
        }}
        @media (max-width: 760px) {{
          .topbar {{
            align-items: flex-start;
            flex-direction: column;
          }}
          .metrics, .strip, .position-grid, .hero-grid, .summary {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .cockpit {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .metric-card, .metric-card.primary, .metric-card.warning, .metric-card.compact {{
            grid-column: span 1;
          }}
          .paper-stat-cards,
          .paper-lane-metrics {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .paper-lane-grid {{
            grid-template-columns: 1fr;
          }}
          .hero-symbol {{
            font-size: 34px;
          }}
          .alert-table .table-head, .alert-table .row,
          .closed-table .table-head, .closed-table .row,
          .leader-table .table-head, .leader-table .row,
          .audit-table .table-head, .audit-table .row,
          .monitor-symbol-table .table-head, .monitor-symbol-table .row,
          .reject-table .table-head, .reject-table .row,
          .scanner-table .table-head, .scanner-table .row,
          .news-table .table-head, .news-table .row {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
        }}
        .news-link {{
          color: #f7e8eb;
          text-decoration: none;
        }}
        .news-link:hover {{
          text-decoration: underline;
          color: #ffffff;
        }}
      </style>
    </head>
    <body>
      <main>
        <section class="topbar">
          <div class="brand">
            <div class="brand-mark">G</div>
            <div>
              <div style="font-weight:700;">GainzAlgo Monster</div>
              <div class="sub" style="margin:2px 0 0 0;">Clutch-time signal board</div>
            </div>
          </div>
          <div class="ticker-strip">
            <div class="ticker-pill">LOTTO • red zone</div>
            <div class="ticker-pill">SWING • control pace</div>
            <div class="ticker-pill">{escape(_route_label(webhook_base_url))}</div>
            <a class="ticker-pill" href="/morning-desk">Morning Desk</a>
            <a class="ticker-pill" href="/contract-picker">Contract Picker</a>
            <div class="ticker-pill">{escape(focus_list)}</div>
          </div>
        </section>

        <section class="cockpit">
          <div class="metric-card primary">
            <div class="metric-label">Total Paper P&amp;L</div>
            <strong class="metric-value {_pnl_class(total_closed_pnl)}">{escape(_fmt_money(total_closed_pnl))}</strong>
            <div class="metric-note">All closed paper trades</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Today P&amp;L</div>
            <strong class="metric-value {_pnl_class(today['pnl'])}">{escape(_fmt_money(today['pnl']))}</strong>
            <div class="metric-note">{today['closed']} closed today</div>
          </div>
          <div class="metric-card win">
            <div class="metric-label">Overall Win Rate</div>
            <strong class="metric-value">{escape(_fmt_pct(paper_stats.get('win_rate')))}</strong>
            <div class="metric-note">{paper_stats.get('wins', 0)}W / {paper_stats.get('losses', 0)}L</div>
          </div>
          <div class="metric-card win">
            <div class="metric-label">LOTTO Win Rate</div>
            <strong class="metric-value">{escape(_fmt_pct((lane_analytics.get('LOTTO') or {}).get('win_rate')))}</strong>
            <div class="metric-note">{(lane_analytics.get('LOTTO') or {}).get('closed', 0)} closed trades</div>
          </div>
          <div class="metric-card compact">
            <div class="metric-label">Open Paper Trades</div>
            <strong class="metric-value">{len(paper_open_positions)}</strong>
            <div class="metric-note">Live positions right now</div>
          </div>
          <div class="metric-card warning">
            <div class="metric-label">Risk Status</div>
            <strong class="metric-value {risk['status_class']}">{escape(risk['status'])}</strong>
            <div class="metric-note">{escape(risk['note'])}</div>
          </div>
        </section>

        <section class="hero">
          <section class="hero-card">
            <div class="hero-title">Last Confirmed Signal</div>
            {hero}
          </section>
          <section class="panel">
            <div class="section-title">Desk Snapshot</div>
            <div class="summary">
              <div><span>Total Alerts</span><strong>{total_alerts}</strong></div>
              <div><span>Discord Sent</span><strong>{total_sent}</strong></div>
              <div><span>Paper Realized P&amp;L</span><strong class="{_pnl_class(total_closed_pnl)}">{escape(_fmt_money(total_closed_pnl))}</strong></div>
              <div><span>Last Seen</span><strong>{escape(_short_time(last_seen))}</strong></div>
              <div><span>Last Discord</span><strong>{escape(_short_time((last_sent_alert or {}).get("time")))}</strong></div>
              <div><span>Last Reject</span><strong>{escape(_short_time((latest_error or {}).get("time")))}</strong></div>
            </div>
            <div class="section-title" style="margin-top:14px;">Desk Status</div>
            <div class="desk-status">{_desk_status(webhook_base_url, latest_alert, total_sent, last_sent_alert, latest_error)}</div>
            <div class="section-title" style="margin-top:14px;">Health</div>
            <div class="health-row">{health}</div>
            <div class="section-title" style="margin-top:14px;">Signal Flow</div>
            <div class="recap-box">{escape(_signal_flow_text(last_sent_alert, latest_error))}</div>
          </section>
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">Performance</div>
            <div class="hero-grid">
              <div class="grid-stat"><span>Today Alerts</span><strong>{today['alerts']}</strong></div>
              <div class="grid-stat"><span>Today Closed</span><strong>{today['closed']}</strong></div>
              <div class="grid-stat"><span>Today P&amp;L</span><strong class="{_pnl_class(today['pnl'])}">{escape(_fmt_money(today['pnl']))}</strong></div>
              <div class="grid-stat"><span>Week Alerts</span><strong>{week['alerts']}</strong></div>
              <div class="grid-stat"><span>Week Closed</span><strong>{week['closed']}</strong></div>
              <div class="grid-stat"><span>Week P&amp;L</span><strong class="{_pnl_class(week['pnl'])}">{escape(_fmt_money(week['pnl']))}</strong></div>
            </div>
          </section>
          <section class="panel">
            <div class="section-title">Risk Manager</div>
            <div class="hero-grid">
              <div class="grid-stat"><span>Status</span><strong class="{risk['status_class']}">{escape(risk['status'])}</strong></div>
              <div class="grid-stat"><span>Loss Streak</span><strong>{risk['loss_streak']}</strong></div>
              <div class="grid-stat"><span>1H Alert Load</span><strong>{risk['recent_alerts']}</strong></div>
              <div class="grid-stat"><span>Today P&amp;L</span><strong class="{_pnl_class(risk['today_pnl'])}">{escape(_fmt_money(risk['today_pnl']))}</strong></div>
              <div class="grid-stat" style="grid-column: span 2;"><span>Note</span><strong>{escape(risk['note'])}</strong></div>
            </div>
          </section>
        </section>

        <details class="diagnostics">
          <summary>System Details</summary>
          <div class="diagnostic-body">
        <section class="panel" style="margin-bottom:16px;">
          <div class="section-title">Ops Center</div>
          <div class="table leader-table">
            <div class="table-head">
              <span>Module</span><span>Status</span><span>Detail</span><span>Last Seen</span>
            </div>
            {ops_rows}
          </div>
        </section>

        <section class="panel" style="margin-bottom:16px;">
          <div class="section-title">Live Settings Snapshot</div>
          <div class="table leader-table">
            <div class="table-head">
              <span>Area</span><span>Setting</span><span>Value</span><span>Purpose</span>
            </div>
            {settings_rows}
          </div>
        </section>

        <section class="panel" style="margin-bottom:16px;">
          <div class="card-head" style="margin-bottom:10px;">
            <div class="section-title" style="margin-bottom:0;">Options Flow Diagnostics</div>
            <div class="muted">{escape(flow_diagnostics['headline'])}</div>
          </div>
          <div class="hero-grid" style="margin-bottom:14px;">
            <div class="grid-stat"><span>Last Started</span><strong>{escape(_short_time(flow_diagnostics['last_started']))}</strong></div>
            <div class="grid-stat"><span>Last Completed</span><strong>{escape(_short_time(flow_diagnostics['last_completed']))}</strong></div>
            <div class="grid-stat"><span>Directional Posted Today</span><strong>{flow_diagnostics['directional_today']}</strong></div>
            <div class="grid-stat"><span>Sold Posted Today</span><strong>{flow_diagnostics['sold_today']}</strong></div>
            <div class="grid-stat"><span>Directional Scan</span><strong>{escape(flow_diagnostics['directional_scan'])}</strong></div>
            <div class="grid-stat"><span>Sold Scan</span><strong>{escape(flow_diagnostics['sold_scan'])}</strong></div>
          </div>
          <div class="strip" style="margin-bottom:14px;">
            <div><span>Directional Note</span><strong>{escape(flow_diagnostics['directional_note'])}</strong></div>
            <div><span>Sold Note</span><strong>{escape(flow_diagnostics['sold_note'])}</strong></div>
            <div><span>Last Error</span><strong class="{flow_diagnostics['error_class']}">{escape(flow_diagnostics['last_error'])}</strong></div>
          </div>
          <div class="layout" style="margin-bottom:0;">
            <section>
              <div class="section-title">Recent Bulls / Bears Posts</div>
              <div class="table flow-post-table">
                <div class="table-head">
                  <span>Symbol</span><span>Contract</span><span>Premium</span><span>Posted</span><span>Note</span>
                </div>
                {flow_diagnostics['directional_rows']}
              </div>
            </section>
            <section>
              <div class="section-title">Recent Sold Premium Posts</div>
              <div class="table flow-post-table">
                <div class="table-head">
                  <span>Symbol</span><span>Contract</span><span>Premium</span><span>Posted</span><span>Note</span>
                </div>
                {flow_diagnostics['sold_rows']}
              </div>
            </section>
          </div>
        </section>

        <section class="panel" style="margin-bottom:16px;">
          <div class="card-head" style="margin-bottom:10px;">
            <div class="section-title" style="margin-bottom:0;">Premarket Advisory</div>
            <div class="muted">Advisory only • this does not filter LOTTO or SWING alerts</div>
          </div>
          <div class="hero-grid" style="margin-bottom:14px;">
            <div class="grid-stat"><span>Universe</span><strong>{premarket['universe_count']}</strong></div>
            <div class="grid-stat"><span>Gap Up</span><strong>{premarket['gap_up_count']}</strong></div>
            <div class="grid-stat"><span>Gap Down</span><strong>{premarket['gap_down_count']}</strong></div>
            <div class="grid-stat"><span>Hot Tape</span><strong>{premarket['hot_tape_count']}</strong></div>
          </div>
          <div class="strip">
            <div><span>LOTTO Watch</span><strong>{escape(premarket['lotto_watch'])}</strong></div>
            <div><span>SWING Watch</span><strong>{escape(premarket['swing_watch'])}</strong></div>
            <div><span>Desk Note</span><strong>{escape(premarket['note'])}</strong></div>
          </div>
          <div class="table scanner-table" style="margin-top:14px;">
            <div class="table-head">
              <span>Symbol</span><span>Last</span><span>Gap</span><span>Volume</span><span>Lane Fit</span>
            </div>
            {premarket['rows']}
          </div>
        </section>

        <section class="panel" style="margin-bottom:16px;">
          <div class="card-head" style="margin-bottom:10px;">
            <div class="section-title" style="margin-bottom:0;">News Radar</div>
            <div class="muted">{escape(news['mode'])}</div>
          </div>
          <div class="hero-grid" style="margin-bottom:14px;">
            <div class="grid-stat"><span>Headlines</span><strong>{news['headline_count']}</strong></div>
            <div class="grid-stat"><span>Sources</span><strong>{news['source_count']}</strong></div>
            <div class="grid-stat"><span>Last Published</span><strong>{escape(_short_time(news['last_published']))}</strong></div>
            <div class="grid-stat"><span>Last Checked</span><strong>{escape(_short_time(news['last_checked']))}</strong></div>
          </div>
          <div class="recap-box" style="margin-bottom:14px;">{escape(news['note'])}</div>
          <div class="table news-table">
            <div class="table-head">
              <span>Headline</span><span>Source</span><span>Time</span>
            </div>
            {_news_rows(news['rows'])}
          </div>
        </section>

        <section class="panel" style="margin-bottom:16px;">
          <div class="section-title">Alert Audit</div>
          <div class="table audit-table">
            <div class="table-head">
              <span>Signal</span><span>Lane</span><span>Lifecycle</span><span>Paper</span><span>Outcome</span><span>Time</span>
            </div>
            {audit_rows}
          </div>
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">SWING Trigger Monitor</div>
            <div class="hero-grid" style="margin-bottom:14px;">
              <div class="grid-stat"><span>Raw Received</span><strong>{swing_monitor['raw_received']}</strong></div>
              <div class="grid-stat"><span>Accepted</span><strong>{swing_monitor['accepted']}</strong></div>
              <div class="grid-stat"><span>Rejected</span><strong>{swing_monitor['rejected']}</strong></div>
              <div class="grid-stat"><span>Real Contracts</span><strong>{swing_monitor['matched']}</strong></div>
              <div class="grid-stat"><span>Discord Sent</span><strong>{swing_monitor['discord_sent']}</strong></div>
              <div class="grid-stat"><span>Paper Entered</span><strong>{swing_monitor['paper_entered']}</strong></div>
            </div>
            <div class="table monitor-symbol-table">
              <div class="table-head">
                <span>Symbol</span><span>Raw</span><span>Accepted</span><span>Rejected</span><span>Paper</span>
              </div>
              {swing_monitor['symbol_rows']}
            </div>
          </section>
          <section class="panel">
            <div class="section-title">SWING Reject Reasons</div>
            <div class="table reject-table">
              <div class="table-head">
                <span>Reason</span><span>Count</span><span>Last Seen</span>
              </div>
              {swing_monitor['reject_rows']}
            </div>
          </section>
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">Execution Funnel</div>
            <div class="hero-grid">
              <div class="grid-stat"><span>Alerts Received</span><strong>{execution_funnel['alerts']}</strong></div>
              <div class="grid-stat"><span>Real Contracts</span><strong>{execution_funnel['matched']}</strong></div>
              <div class="grid-stat"><span>Discord Sent</span><strong>{execution_funnel['discord_sent']}</strong></div>
              <div class="grid-stat"><span>Paper Entered</span><strong>{execution_funnel['paper_entered']}</strong></div>
              <div class="grid-stat"><span>Match Rate</span><strong>{escape(_fmt_pct(execution_funnel['match_rate']))}</strong></div>
              <div class="grid-stat"><span>Entries / Contract</span><strong>{escape(_fmt_pct(execution_funnel['paper_entry_rate']))}</strong></div>
            </div>
          </section>
          <section class="panel">
            <div class="section-title">Lane Analytics</div>
            <div class="table leader-table">
              <div class="table-head">
                <span>Lane</span><span>Alerts</span><span>Closed</span><span>P&amp;L</span>
              </div>
              {lane_rows}
            </div>
          </section>
        </section>
          </div>
        </details>

        <section class="grid">
          {style_cards}
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">Recent Closed Paper Trades</div>
            <div class="table closed-table">
              <div class="table-head">
                <span>Trade</span><span>Lane</span><span>Result</span><span>Price</span><span>Closed</span>
              </div>
              {closed_rows}
            </div>
          </section>
          <section class="panel">
            <div class="section-title">Ticker Leaderboard</div>
            <div class="table leader-table">
              <div class="table-head">
                <span>Symbol</span><span>Alerts</span><span>Closed</span><span>P&amp;L</span>
              </div>
              {leaderboard_rows}
            </div>
          </section>
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">Trader Recap</div>
            <div class="recap-box">{escape(recap_lines)}</div>
          </section>
          <section class="panel">
            <div class="section-title">Before The Next Trade</div>
            <div class="recap-box">1. Tape in sync with the lane?\n2. Current price still near the callout?\n3. Contract sits where you actually want to play it?\n4. Stop and target still make sense?\n5. If this loses, will the next trade still be clean?</div>
          </section>
        </section>

        {paper_section}
      </main>
    </body>
    </html>
    """


def _style_card(style, state, lane_stats):
    alerts = state.get("recent_alerts", [])
    last = state.get("last_alert") or {}
    open_position = dict(lane_stats.get("open_position") or {})
    last_webhook_error = state.get("last_webhook_error") or {}
    win_rate = _fmt_pct(lane_stats.get("win_rate"))
    tracked_closures = lane_stats.get("closed", 0)
    paper_pnl = lane_stats.get("pnl", 0.0)
    matched_alerts = lane_stats.get("matched_alerts", 0)
    paper_entries = lane_stats.get("paper_entries", 0)
    sent_alerts = lane_stats.get("discord_sent", 0)
    total_alerts = lane_stats.get("alerts", 0)

    rows = []
    for alert in reversed(alerts[-5:]):
        side_class = "buy" if alert.get("side") == "BUY" else "sell"
        direction = "Bullish" if alert.get("side") == "BUY" else "Bearish"
        rows.append(
            f"""
            <div class="row">
              <div>
                <div class="alert-symbol">{escape(str(alert.get('symbol', '')))}</div>
                <div class="alert-meta">{escape(_short_time(alert.get('time')))} • {escape(direction)}</div>
              </div>
              <div><span class="tag {side_class}">{escape(str(alert.get('side', '')))}</span></div>
              <div>{escape(_fmt(alert.get('price')))}</div>
              <div>{escape(_fmt(alert.get('confidence')))}%</div>
            </div>
            """
        )
    alert_rows = "".join(rows) or "<div class='empty'>No alerts yet</div>"

    last_symbol = escape(str(last.get("symbol") or "None"))
    last_side = escape(str(last.get("side") or "N/A"))
    last_sent = "Sent" if last.get("discord_sent") else "Pending"
    position_symbol = escape(str(open_position.get("symbol") or "None"))
    position_side = escape(str(open_position.get("side") or "N/A"))
    position_entry = escape(_fmt(open_position.get("entry_underlying_price", open_position.get("entry_price"))))
    position_stop = escape(_fmt(open_position.get("stop")))
    position_tp1 = escape(_fmt(open_position.get("tp1")))
    option_symbol = escape(_fmt_contract(open_position.get("option_symbol")))
    option_entry = escape(_fmt_money(open_position.get("entry_contract_price")))
    option_mark = escape(_fmt_money(open_position.get("current_contract_price")))
    pricing_badge = escape(_pricing_badge(open_position))
    position_status = escape(str(open_position.get("status") or "N/A"))
    status_class = _status_class(open_position.get("status"))
    style_class = style.lower()
    webhook_error_block = ""
    error_symbol = str(last_webhook_error.get("symbol") or "").strip().upper()
    if last_webhook_error.get("message") and error_symbol not in DASHBOARD_HIDDEN_SYMBOLS:
        error_symbol = last_webhook_error.get("symbol") or "Unknown"
        error_time = _short_time(last_webhook_error.get("time"))
        webhook_error_block = f"""
      <div class="strip">
        <div><span>Last Webhook Error</span><strong class="negative">{escape(str(last_webhook_error.get("message")))}</strong></div>
        <div><span>Symbol</span><strong>{escape(str(error_symbol))}</strong></div>
        <div><span>Time</span><strong>{escape(error_time)}</strong></div>
      </div>
        """

    return f"""
    <section class="card {style_class}">
      <div class="card-head">
        <div>
          <div class="eyebrow">{style}</div>
          <div class="headline">{last_symbol}</div>
        </div>
        <span class="tag {'buy' if last.get('side') == 'BUY' else 'sell' if last.get('side') == 'SELL' else ''}">{last_side}</span>
      </div>

      <div class="metrics">
        <div><span>Alerts</span><strong>{total_alerts}</strong></div>
        <div><span>Sent</span><strong>{sent_alerts}</strong></div>
        <div><span>Matched</span><strong>{matched_alerts}</strong></div>
        <div><span>Entered</span><strong>{paper_entries}</strong></div>
      </div>

      <div class="strip">
        <div><span>Last Update</span><strong>{escape(_short_time(state.get("last_updated")))}</strong></div>
        <div><span>Discord</span><strong>{escape(last_sent)}</strong></div>
        <div><span>Win Rate</span><strong>{escape(win_rate)}</strong></div>
      </div>

      <div class="strip">
        <div><span>Tracked Closures</span><strong>{tracked_closures}</strong></div>
        <div><span>Paper P&amp;L</span><strong class="{_pnl_class(paper_pnl)}">{escape(_fmt_money(paper_pnl))}</strong></div>
        <div><span>Status</span><strong class="{status_class}">{position_status}</strong></div>
      </div>
      {webhook_error_block}

      <div class="position">
        <div class="section-title">Open Paper Position</div>
        <div class="position-grid">
          <div><span>Symbol</span><strong>{position_symbol}</strong></div>
          <div><span>Side</span><strong>{position_side}</strong></div>
          <div><span>Entry</span><strong>{position_entry}</strong></div>
          <div><span>Stop</span><strong>{position_stop}</strong></div>
          <div><span>Underlying TP1</span><strong>{position_tp1}</strong></div>
          <div><span>Option Idea</span><strong>{option_symbol}</strong></div>
          <div><span>Entry Premium</span><strong>{option_entry}</strong></div>
          <div><span>Live Premium</span><strong>{option_mark}</strong></div>
          <div><span>Source</span><strong>{pricing_badge}</strong></div>
          <div><span>Live P&amp;L %</span><strong class="{_pnl_class(open_position.get('live_pnl'))}">{escape(_fmt_pct(open_position.get("live_pnl_pct")))}</strong></div>
        </div>
      </div>

      <div class="section-title">Recent Tape</div>
      <div class="table alert-table">
        <div class="table-head">
          <span>Signal</span><span>Bias</span><span>Price</span><span>Conf</span>
        </div>
        {alert_rows}
      </div>
    </section>
    """


def _hero(latest_alert):
    if not latest_alert:
        return "<div class='hero-symbol'>No alerts yet</div><div class='muted'>Waiting on the next signal.</div>"

    side = latest_alert.get("side") or "N/A"
    style = latest_alert.get("trade_style") or "N/A"
    contract = _fmt_contract(latest_alert.get("option_symbol"))
    price = _fmt(latest_alert.get("price"))
    target = _fmt(latest_alert.get("tp1"))
    second_target = _fmt(latest_alert.get("tp2"))
    stop = _fmt(latest_alert.get("stop"))
    confidence = _fmt(latest_alert.get("confidence"))
    timeframe = latest_alert.get("timeframe") or "N/A"
    target_expiry = latest_alert.get("target_expiry") or "N/A"
    entry_premium = _fmt_money(latest_alert.get("contract_price"))
    reward_to_risk = _fmt(latest_alert.get("reward_to_risk"))
    direction_chip = f"<span class='tag {'buy' if side == 'BUY' else 'sell'}'>{escape(side)}</span>"
    return f"""
      <div class="hero-title">{escape(style)} Lane</div>
      <div class="hero-symbol">{escape(str(latest_alert.get('symbol') or 'N/A'))}</div>
      <div class="hero-meta">
        {direction_chip}
        <span class="chip">{escape(_fmt_timeframe(timeframe))}</span>
        <span class="chip">{escape(contract)}</span>
        <span class="chip">{escape(_short_time(latest_alert.get('time')))}</span>
      </div>
      <div class="hero-grid">
        <div><span>Current Price</span><strong>{escape(price)}</strong></div>
        <div><span>Entry Premium</span><strong>{escape(entry_premium)}</strong></div>
        <div><span>Target Expiry</span><strong>{escape(str(target_expiry))}</strong></div>
        <div><span>Reward / Risk</span><strong>{escape(reward_to_risk)}</strong></div>
        <div><span>Underlying TP1</span><strong>{escape(target)}</strong></div>
        <div><span>Underlying TP2</span><strong>{escape(second_target)}</strong></div>
        <div><span>Stop</span><strong>{escape(stop)}</strong></div>
        <div><span>Confidence</span><strong>{escape(confidence)}%</strong></div>
        <div><span>Source</span><strong>{escape(str(latest_alert.get('pricing_source') or 'Estimated').title())}</strong></div>
        <div><span>Mode</span><strong>{escape('Contract Match' if latest_alert.get('option_symbol') else 'Signal Only')}</strong></div>
      </div>
    """


def _trade_style(item, fallback=None):
    if not item:
        return str(fallback or "").upper()
    return str(item.get("trade_style") or item.get("style") or fallback or "").upper()


def _collect_raw_alerts(states, style=None):
    items = []
    wanted_style = str(style or "").upper() or None
    for lane, state in states.items():
        for alert in state.get("recent_alerts") or []:
            row = dict(alert)
            row["trade_style"] = _trade_style(row, lane)
            if wanted_style and row["trade_style"] != wanted_style:
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol in DASHBOARD_HIDDEN_SYMBOLS:
                continue
            if not row.get("time"):
                continue
            items.append(row)
    items.sort(key=lambda item: item.get("time") or "")
    return items


def _collect_webhook_errors(states, style=None):
    items = []
    seen = set()
    wanted_style = str(style or "").upper() or None
    for lane, state in states.items():
        lane_style = str(lane or "").upper()
        if wanted_style and lane_style != wanted_style:
            continue
        history = list(state.get("recent_webhook_errors") or [])
        if not history and state.get("last_webhook_error"):
            history = [state.get("last_webhook_error")]
        for error in history:
            row = dict(error or {})
            row["trade_style"] = _trade_style(row, lane_style)
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol in DASHBOARD_HIDDEN_SYMBOLS:
                continue
            signature = (
                row.get("time"),
                row.get("message"),
                row.get("symbol"),
                row.get("signal_id"),
                row.get("trade_style"),
            )
            if signature in seen:
                continue
            seen.add(signature)
            items.append(row)
    items.sort(key=lambda item: item.get("time") or "")
    return items


def _paper_signal_maps(open_positions, closed_positions, style=None):
    open_map = {}
    closed_map = {}
    wanted_style = str(style or "").upper() or None

    for position in open_positions or []:
        lane = _trade_style(position)
        if wanted_style and lane != wanted_style:
            continue
        signal_id = position.get("signal_id")
        if signal_id:
            open_map[signal_id] = position

    sorted_closed = sorted(closed_positions or [], key=lambda item: item.get("closed_at") or "")
    for position in sorted_closed:
        lane = _trade_style(position)
        if wanted_style and lane != wanted_style:
            continue
        signal_id = position.get("signal_id")
        if signal_id:
            closed_map[signal_id] = position

    return open_map, closed_map


def _alert_audit_rows(states, open_positions, closed_positions):
    events = _alert_audit_events(states, open_positions, closed_positions)
    if not events:
        return "<div class='empty'>Audit trail fills as alerts and rejects land.</div>"
    return "".join(_audit_row(item) for item in events[:12])


def _alert_audit_events(states, open_positions, closed_positions):
    alerts = _collect_raw_alerts(states)
    errors = _collect_webhook_errors(states)
    paper_errors = _collect_paper_errors(states)
    open_map, closed_map = _paper_signal_maps(open_positions, closed_positions)
    events = []

    for alert in alerts:
        signal_id = alert.get("signal_id")
        events.append(
            {
                "kind": "alert",
                "time": alert.get("time"),
                "trade_style": _trade_style(alert),
                "symbol": alert.get("symbol"),
                "signal_id": signal_id,
                "alert": alert,
                "open_position": open_map.get(signal_id),
                "closed_position": closed_map.get(signal_id),
                "paper_error": paper_errors.get(signal_id),
            }
        )

    for error in errors:
        events.append(
            {
                "kind": "reject",
                "time": error.get("time"),
                "trade_style": _trade_style(error),
                "symbol": error.get("symbol"),
                "signal_id": error.get("signal_id"),
                "message": error.get("message"),
            }
        )

    events.sort(key=lambda item: item.get("time") or "", reverse=True)
    return events


def _audit_row(item):
    if item.get("kind") == "reject":
        symbol = escape(str(item.get("symbol") or "Unknown"))
        signal_meta = escape(str(item.get("signal_id") or "Rejected before signal log"))
        lifecycle = "Received -> Rejected"
        paper_html = "<div class='audit-note'>No paper trade</div>"
        outcome_html = (
            f"<div><strong class='down'>Rejected</strong>"
            f"<div class='audit-note'>{escape(str(item.get('message') or 'Unknown error'))}</div></div>"
        )
        return f"""
        <div class="row">
          <div>
            <div class="alert-symbol">{symbol}</div>
            <div class="alert-meta">{signal_meta}</div>
          </div>
          <div><strong>{escape(str(item.get('trade_style') or 'N/A'))}</strong></div>
          <div class="audit-flow">{escape(lifecycle)}</div>
          <div>{paper_html}</div>
          <div>{outcome_html}</div>
          <div>{escape(_short_time(item.get('time')))}</div>
        </div>
        """

    alert = item.get("alert") or {}
    open_position = item.get("open_position") or {}
    closed_position = item.get("closed_position") or {}
    paper_error = item.get("paper_error") or {}
    contract = _fmt_contract(alert.get("option_symbol"))
    if contract == "N/A":
        contract = str(alert.get("signal_id") or "No contract logged")
    lifecycle = _audit_lifecycle(alert, open_position, closed_position, paper_error)
    paper_html = _audit_paper_cell(open_position, closed_position)
    outcome_html = _audit_outcome_cell(alert, open_position, closed_position, paper_error)
    return f"""
    <div class="row">
      <div>
        <div class="alert-symbol">{escape(str(alert.get('symbol') or 'Unknown'))} • {escape(str(alert.get('side') or 'N/A'))}</div>
        <div class="alert-meta">{escape(contract)}</div>
      </div>
      <div><strong>{escape(_trade_style(alert))}</strong></div>
      <div class="audit-flow">{escape(lifecycle)}</div>
      <div>{paper_html}</div>
      <div>{outcome_html}</div>
      <div>{escape(_short_time(item.get('time')))}</div>
    </div>
    """


def _audit_lifecycle(alert, open_position, closed_position, paper_error=None):
    steps = ["Received"]
    if _has_real_contract_reference(alert):
        steps.append("Contract matched")
    else:
        steps.append("Contract incomplete")

    steps.append("Discord sent" if alert.get("discord_sent") else "Discord blocked")

    if closed_position:
        steps.append("Paper closed")
    elif open_position:
        steps.append("Paper live")
    elif paper_error:
        steps.append("Paper failed")
    elif _has_real_contract_reference(alert) and alert.get("discord_sent"):
        steps.append("Paper pending")

    return " -> ".join(steps)


def _audit_paper_cell(open_position, closed_position):
    if closed_position:
        pnl = closed_position.get("realized_pnl")
        reason = closed_position.get("exit_reason") or "Closed"
        return (
            f"<div><strong class='{_pnl_class(pnl)}'>{escape(_fmt_money(pnl))}</strong>"
            f"<div class='audit-note'>{escape(str(reason))}</div></div>"
        )
    if open_position:
        pnl = open_position.get("unrealized_pnl")
        pct = open_position.get("live_pnl_pct")
        pct_text = _fmt_pct(pct) if pct not in (None, "") else "Live"
        return (
            f"<div><strong class='{_pnl_class(pnl)}'>{escape(_fmt_money(pnl))}</strong>"
            f"<div class='audit-note'>{escape(pct_text)}</div></div>"
        )
    return "<div class='audit-note'>No paper entry</div>"


def _audit_outcome_cell(alert, open_position, closed_position, paper_error=None):
    if closed_position:
        reason = closed_position.get("exit_reason") or "Paper trade closed"
        return f"<div class='audit-note'>{escape(str(reason))}</div>"
    if open_position:
        status = open_position.get("status") or "OPEN"
        return f"<div><strong class='warn'>{escape(str(status))}</strong><div class='audit-note'>Paper position active</div></div>"
    if paper_error:
        return (
            f"<div><strong class='down'>Paper Failed</strong>"
            f"<div class='audit-note'>{escape(str(paper_error.get('message') or 'Unknown paper error'))}</div></div>"
        )
    if not _has_real_contract_reference(alert):
        return f"<div><strong class='down'>Filtered</strong><div class='audit-note'>{escape(_contract_gap_reason(alert))}</div></div>"
    if not alert.get("discord_sent"):
        return "<div><strong class='down'>Blocked</strong><div class='audit-note'>Discord send failed or was suppressed</div></div>"
    return "<div><strong class='warn'>Waiting</strong><div class='audit-note'>No paper entry recorded yet</div></div>"


def _contract_gap_reason(alert):
    if not alert.get("option_symbol"):
        return "No option symbol matched"
    contract_price = alert.get("contract_price")
    if contract_price in (None, "", 0):
        return "No contract premium matched"
    pricing_source = str(alert.get("pricing_source") or "").strip().lower()
    if pricing_source == "estimated":
        return "Estimated contract blocked from Discord"
    return "Contract reference incomplete"


def _swing_trigger_monitor(states, open_positions, closed_positions):
    style = "SWING"
    swing_alerts = _collect_raw_alerts(states, style)
    swing_errors = _collect_webhook_errors(states, style)
    open_map, closed_map = _paper_signal_maps(open_positions, closed_positions, style)
    paper_signal_ids = set(open_map) | set(closed_map)

    symbol_totals = defaultdict(lambda: {"raw": 0, "accepted": 0, "rejected": 0, "paper": 0})
    for alert in swing_alerts:
        symbol = str(alert.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        symbol_totals[symbol]["raw"] += 1
        symbol_totals[symbol]["accepted"] += 1
        if alert.get("signal_id") in paper_signal_ids:
            symbol_totals[symbol]["paper"] += 1

    for error in swing_errors:
        symbol = str(error.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        symbol_totals[symbol]["raw"] += 1
        symbol_totals[symbol]["rejected"] += 1

    matched = sum(1 for alert in swing_alerts if _has_real_contract_reference(alert))
    discord_sent = sum(1 for alert in swing_alerts if alert.get("discord_sent"))
    paper_entered = sum(1 for alert in swing_alerts if alert.get("signal_id") in paper_signal_ids)
    symbol_rows = _swing_symbol_rows(symbol_totals)
    reject_rows = _swing_reject_rows(swing_errors)

    return {
        "raw_received": len(swing_alerts) + len(swing_errors),
        "accepted": len(swing_alerts),
        "rejected": len(swing_errors),
        "matched": matched,
        "discord_sent": discord_sent,
        "paper_entered": paper_entered,
        "symbol_rows": symbol_rows,
        "reject_rows": reject_rows,
    }


def _swing_symbol_rows(symbol_totals):
    if not symbol_totals:
        return "<div class='empty'>Symbol counts will populate after SWING alerts hit the hosted route.</div>"

    ordered = sorted(
        symbol_totals.items(),
        key=lambda item: (
            item[1]["raw"],
            item[1]["accepted"],
            item[1]["paper"],
            item[0],
        ),
        reverse=True,
    )
    rows = []
    for symbol, stats in ordered[:8]:
        rows.append(
            f"""
            <div class="row">
              <div><strong>{escape(symbol)}</strong></div>
              <div>{stats['raw']}</div>
              <div>{stats['accepted']}</div>
              <div>{stats['rejected']}</div>
              <div>{stats['paper']}</div>
            </div>
            """
        )
    return "".join(rows)


def _swing_reject_rows(errors):
    if not errors:
        return "<div class='empty'>No SWING rejects recorded yet.</div>"

    reason_counts = Counter()
    last_seen = {}
    for error in errors:
        message = str(error.get("message") or "Unknown error").strip()
        reason_counts[message] += 1
        current_time = error.get("time")
        previous_time = last_seen.get(message)
        if not previous_time or str(current_time or "") > str(previous_time or ""):
            last_seen[message] = current_time

    rows = []
    for message, count in reason_counts.most_common(8):
        rows.append(
            f"""
            <div class="row">
              <div class="audit-note">{escape(message)}</div>
              <div>{count}</div>
              <div>{escape(_short_time(last_seen.get(message)))}</div>
            </div>
            """
        )
    return "".join(rows)


def _premarket_advisory(config):
    records = []
    symbols = [
        symbol for symbol in (config.get("allowed_symbols") or [])
        if symbol not in DASHBOARD_HIDDEN_SYMBOLS
    ][:40]
    if alpaca_enabled(config) and symbols:
        try:
            snapshots = fetch_stock_snapshots(config, symbols)
        except Exception:
            snapshots = {}
        for symbol in symbols:
            item = _premarket_record(symbol, (snapshots or {}).get(symbol) or {})
            if item:
                records.append(item)

    movers = sorted(
        records,
        key=lambda item: (
            abs(item.get("gap_pct") or 0.0),
            item.get("dollar_volume") or 0.0,
            item.get("volume") or 0,
        ),
        reverse=True,
    )[:10]
    rows = "".join(_premarket_row(item) for item in movers) or (
        "<div class='empty'>Premarket advisory needs Alpaca stock snapshots and fresh market data.</div>"
    )

    lotto_candidates = sorted(
        [item for item in records if item.get("lotto_score", 0) >= 2],
        key=lambda item: (
            item.get("lotto_score", 0),
            abs(item.get("gap_pct") or 0.0),
            item.get("dollar_volume") or 0.0,
        ),
        reverse=True,
    )[:5]
    swing_candidates = sorted(
        [item for item in records if item.get("swing_score", 0) >= 2],
        key=lambda item: (
            item.get("swing_score", 0),
            item.get("dollar_volume") or 0.0,
            abs(item.get("gap_pct") or 0.0),
        ),
        reverse=True,
    )[:5]

    hot_tape_count = sum(
        1 for item in records
        if abs(item.get("gap_pct") or 0.0) >= 1.0 and (item.get("volume") or 0) >= 250000
    )
    gap_up_count = sum(1 for item in records if (item.get("gap_pct") or 0.0) >= 1.0)
    gap_down_count = sum(1 for item in records if (item.get("gap_pct") or 0.0) <= -1.0)

    note = "No live advisory data yet."
    if records:
        if hot_tape_count >= 8:
            note = "Tape is active. Let the scanner narrow the watchlist, not the trigger logic."
        elif hot_tape_count >= 4:
            note = "Decent motion on the board. Focus on clean names with real participation."
        else:
            note = "Quiet tape. Favor selectivity over forcing fresh names."

    return {
        "universe_count": len(records),
        "gap_up_count": gap_up_count,
        "gap_down_count": gap_down_count,
        "hot_tape_count": hot_tape_count,
        "lotto_watch": _watch_text(lotto_candidates),
        "swing_watch": _watch_text(swing_candidates),
        "note": note,
        "rows": rows,
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
    }


def _lane_fit_label(lotto_score, swing_score):
    if lotto_score >= 3 and swing_score >= 3:
        return "BOTH"
    if lotto_score >= swing_score and lotto_score >= 2:
        return "LOTTO"
    if swing_score >= 2:
        return "SWING"
    return "WATCH"


def _watch_text(items):
    if not items:
        return "Waiting on tape"
    return " / ".join(item["symbol"] for item in items)


def _premarket_row(item):
    gap_pct = item.get("gap_pct")
    gap_text = _fmt_signed_pct(gap_pct)
    gap_class = _pnl_class(gap_pct)
    lane_fit = item.get("lane_fit") or "WATCH"
    volume_text = _fmt_compact_int(item.get("volume"))
    note = f"Min { _fmt_compact_int(item.get('minute_volume')) } • ${_fmt_compact_int(item.get('dollar_volume'))} DV"
    return f"""
    <div class="row">
      <div>
        <div class="alert-symbol">{escape(str(item.get('symbol') or 'N/A'))}</div>
        <div class="alert-meta">{escape(note)}</div>
      </div>
      <div>{escape(_fmt(item.get('price')))}</div>
      <div><strong class="{gap_class}">{escape(gap_text)}</strong></div>
      <div>{escape(volume_text)}</div>
      <div><strong>{escape(lane_fit)}</strong><div class="audit-note">Advisory only</div></div>
    </div>
    """


def _news_rows(items):
    if not items:
        return "<div class='empty'>No live headlines available yet.</div>"
    rows = []
    for item in items[:8]:
        rows.append(
            f"""
            <div class="row">
              <div><a class="news-link" href="{escape(str(item.get('link') or '#'))}" target="_blank" rel="noopener noreferrer">{escape(str(item.get('title') or 'Untitled headline'))}</a></div>
              <div>{escape(str(item.get('source') or 'News'))}</div>
              <div>{escape(_short_time(item.get('published_at')))}</div>
            </div>
            """
        )
    return "".join(rows)


def _collect_alerts(states):
    alerts = []
    for state in states.values():
        alerts.extend(state.get("recent_alerts") or [])
    alerts.sort(key=lambda item: item.get("time") or "")
    return alerts


def _dashboard_states(states):
    return {style: _dashboard_state(state) for style, state in states.items()}


def _dashboard_state(state):
    view = dict(state or {})
    recent_alerts = [
        dict(item)
        for item in (state.get("recent_alerts") or [])
        if _include_dashboard_alert(item)
    ]
    closed_positions = [
        dict(item)
        for item in (state.get("closed_positions") or [])
        if _include_dashboard_position(item)
    ]
    open_position = state.get("open_position")

    view["recent_alerts"] = recent_alerts
    view["closed_positions"] = closed_positions
    view["open_position"] = dict(open_position) if _include_dashboard_position(open_position) else None
    view["last_alert"] = recent_alerts[-1] if recent_alerts else None
    return view


def _include_dashboard_alert(item):
    return bool(item and item.get("time") and _has_real_contract_reference(item))


def _include_dashboard_position(item):
    return _has_real_contract_reference(item)


def _has_real_contract_reference(item):
    if not item:
        return False
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol or symbol in DASHBOARD_HIDDEN_SYMBOLS:
        return False
    if not item.get("option_symbol"):
        return False
    contract_price = item.get("contract_price")
    if contract_price in (None, ""):
        contract_price = item.get("entry_contract_price")
    if contract_price in (None, "", 0):
        return False
    pricing_source = str(item.get("pricing_source") or "").strip().lower()
    if pricing_source == "estimated":
        return False
    return True


def _collect_closed_positions(states):
    items = []
    for style, state in states.items():
        for position in state.get("closed_positions") or []:
            row = dict(position)
            row["trade_style"] = style
            items.append(row)
    items.sort(key=lambda item: item.get("closed_at") or "", reverse=False)
    return items


def _summary_window(alerts, closed_positions, delta):
    cutoff = datetime.now(timezone.utc) - delta
    alert_count = 0
    closed_count = 0
    pnl = 0.0

    for alert in alerts:
        parsed = _parse_iso(alert.get("time"))
        if parsed and parsed >= cutoff:
            alert_count += 1

    for item in closed_positions:
        parsed = _parse_iso(item.get("closed_at"))
        if parsed and parsed >= cutoff:
            closed_count += 1
            value = _trade_pnl(item)
            if value is not None:
                pnl += float(value)

    return {"alerts": alert_count, "closed": closed_count, "pnl": round(pnl, 2)}


def _leaderboard(alerts, closed_positions):
    counts = Counter()
    closed_counts = Counter()
    pnl_map = defaultdict(float)

    for alert in alerts:
        symbol = alert.get("symbol")
        if symbol:
            counts[symbol] += 1

    for trade in closed_positions:
        symbol = trade.get("symbol")
        if not symbol:
            continue
        closed_counts[symbol] += 1
        value = _trade_pnl(trade)
        if value is not None:
            pnl_map[symbol] += float(value)

    rows = []
    for symbol, total in counts.most_common(6):
        rows.append(
            {
                "symbol": symbol,
                "alerts": total,
                "closed": closed_counts[symbol],
                "pnl": round(pnl_map[symbol], 2),
            }
        )
    return rows


def _lane_analytics(alerts, open_positions, closed_positions):
    lanes = {}
    for style in ("LOTTO", "SWING"):
        lane_alerts = [item for item in alerts if str(item.get("trade_style") or "").upper() == style]
        lane_closed = [item for item in closed_positions if str(item.get("style") or item.get("trade_style") or "").upper() == style]
        lane_open = [item for item in open_positions if str(item.get("style") or item.get("trade_style") or "").upper() == style]
        lane_sent = sum(1 for item in lane_alerts if item.get("discord_sent"))
        wins = sum(1 for item in lane_closed if (_trade_pnl(item) or 0) > 0)
        losses = sum(1 for item in lane_closed if (_trade_pnl(item) or 0) <= 0)
        matched = sum(1 for item in lane_alerts if _has_real_contract_reference(item))
        pnl = round(sum(float(_trade_pnl(item) or 0.0) for item in lane_closed), 2)
        lanes[style] = {
            "style": style,
            "alerts": len(lane_alerts),
            "discord_sent": lane_sent,
            "matched_alerts": matched,
            "paper_entries": len(lane_open) + len(lane_closed),
            "open": len(lane_open),
            "closed": len(lane_closed),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / len(lane_closed)) * 100, 2) if lane_closed else None,
            "pnl": pnl,
            "open_position": lane_open[-1] if lane_open else None,
        }
    return lanes


def _execution_funnel(alerts, open_positions, closed_positions):
    alerts_total = len(alerts)
    matched = sum(1 for item in alerts if _has_real_contract_reference(item))
    discord_sent = sum(1 for item in alerts if item.get("discord_sent"))
    entered = len(open_positions) + len(closed_positions)
    return {
        "alerts": alerts_total,
        "matched": matched,
        "discord_sent": discord_sent,
        "paper_entered": entered,
        "match_rate": _rate(matched, alerts_total),
        "paper_entry_rate": _rate(entered, matched),
    }


def _ops_health_rows(config, alerts, open_positions, closed_positions, latest_error, latest_paper_error, webhook_base_url, flow_diagnostics):
    last_alert_time = alerts[-1].get("time") if alerts else None
    last_closed_time = closed_positions[-1].get("closed_at") if closed_positions else None
    rows = [
        _ops_row(
            "TradingView Webhook",
            "LIVE" if webhook_base_url else "OFFLINE",
            "Hosted route ready" if webhook_base_url else "No public webhook route",
            last_alert_time,
        ),
        _ops_row(
            "Discord Alerts",
            "LIVE" if _discord_ready(config) else "BLOCKED",
            _discord_detail(config),
            last_alert_time,
        ),
        _ops_row(
            "Alpaca Contracts",
            "LIVE" if _alpaca_ready(config) else "BLOCKED",
            "Contract matching + live contract marks" if _alpaca_ready(config) else "Missing Alpaca API keys",
            last_alert_time,
        ),
        _ops_row(
            "Paper Trader",
            "LIVE" if config.get("paper_trading_enabled", True) else "OFF",
            (
                latest_paper_error.get("message")
                if latest_paper_error
                else f"{len(open_positions)} open / {len(closed_positions)} closed"
            ),
            latest_paper_error.get("time") if latest_paper_error else last_closed_time,
        ),
        _ops_row(
            "Options Flow",
            "LIVE" if _flow_ready(config) else "BLOCKED",
            _flow_detail(config),
            flow_diagnostics.get("last_completed") or flow_diagnostics.get("last_started"),
        ),
        _ops_row(
            "Sold Premium Flow",
            "LIVE" if _sold_flow_ready(config) else "BLOCKED",
            _sold_flow_detail(config),
            flow_diagnostics.get("last_completed") or flow_diagnostics.get("last_started"),
        ),
        _ops_row(
            "Heatmap",
            "LIVE" if _heatmap_ready(config) else "BLOCKED",
            _heatmap_detail(config),
            None,
        ),
        _ops_row(
            "Reject Monitor",
            "WATCHING" if latest_error else "CLEAR",
            latest_error.get("message") if latest_error else "No recent webhook rejects",
            latest_error.get("time") if latest_error else None,
        ),
    ]
    return "".join(rows)


def _settings_rows(config):
    flow = config.get("flow") or {}
    styles = config.get("styles") or {}
    rows = [
        _settings_row("LOTTO", "Confidence Floor", _fmt(styles.get("LOTTO", {}).get("min_confidence")), "Minimum score before a LOTTO alert is accepted"),
        _settings_row("LOTTO", "DTE Window", _dte_window(styles.get("LOTTO", {})), "Target expiry band for contract matching"),
        _settings_row("LOTTO", "Risk %", _fmt_pct(styles.get("LOTTO", {}).get("risk_pct")), "Paper-account sizing per trade"),
        _settings_row("LOTTO", "Force Close", "3:55 PM ET", "LOTTO positions are closed before the bell"),
        _settings_row("SWING", "Confidence Floor", _fmt(styles.get("SWING", {}).get("min_confidence")), "Minimum score before a SWING alert is accepted"),
        _settings_row("SWING", "DTE Window", _dte_window(styles.get("SWING", {})), "Target expiry band for swing contracts"),
        _settings_row("SWING", "Risk %", _fmt_pct(styles.get("SWING", {}).get("risk_pct")), "Paper-account sizing per trade"),
        _settings_row("SWING", "Force Close", "Disabled", "SWING positions can hold overnight until stop, trail, or max-hold exit"),
        _settings_row("SWING", "Trail Stop", _fmt_ratio_pct(styles.get("SWING", {}).get("trailing_stop_pct")), "Trailing stop after TP1 when enabled"),
        _settings_row("FLOW", "Min Premium", _fmt_money(flow.get("min_premium")), "Minimum unusual-flow premium to qualify"),
        _settings_row("FLOW", "Max DTE", str(flow.get("max_dte", "N/A")), "Maximum expiry distance for flow candidates"),
        _settings_row("SYSTEM", "Paper Account", _fmt_money(config.get("paper_account_size")), "Hosted paper account size for sizing and P&L"),
    ]
    return "".join(rows)


def _risk_snapshot(states, alerts, closed_positions):
    today = _summary_window(alerts, closed_positions, timedelta(days=1))
    recent_alerts = _summary_window(alerts, closed_positions, timedelta(hours=1))["alerts"]
    loss_streak = _loss_streak(closed_positions)

    status = "Clear"
    status_class = "up"
    note = "Pace is healthy."

    if today["pnl"] < -300 or loss_streak >= 3:
        status = "Cool Off"
        status_class = "down"
        note = "Loss streak is getting loud. Tighten up and protect the day."
    elif recent_alerts >= 6:
        status = "Crowded Tape"
        status_class = ""
        note = "Alert flow is busy. Filter harder and skip marginal setups."
    elif today["pnl"] > 250:
        status = "Locked In"
        status_class = "up"
        note = "Strong day. Protect gains and stay selective."

    return {
        "status": status,
        "status_class": status_class,
        "loss_streak": loss_streak,
        "recent_alerts": recent_alerts,
        "today_pnl": today["pnl"],
        "note": note,
    }


def _rate(numerator, denominator):
    if not denominator:
        return None
    return round((float(numerator) / float(denominator)) * 100, 2)


def _health_snapshot(config, states, webhook_base_url=None):
    chips = []
    recent_alert_times = []
    for state in states.values():
        for alert in state.get("recent_alerts") or []:
            if alert.get("time"):
                recent_alert_times.append(alert.get("time"))

    last_update = max(recent_alert_times) if recent_alert_times else None
    staleness = None
    if last_update:
        parsed = _parse_iso(last_update)
        if parsed:
            staleness = int((datetime.now(timezone.utc) - parsed).total_seconds() // 60)

    chips.append(_chip("App Online", "good"))
    chips.append(_chip("Discord Ready", "good"))
    if config.get("alpaca", {}).get("api_key"):
        chips.append(_chip("Alpaca Live", "good"))
    else:
        chips.append(_chip("Estimated Contracts", "warn"))

    provider = str((config.get("tunnel") or {}).get("provider") or "").lower()
    if webhook_base_url:
        chips.append(_chip("Hosted Live" if provider == "render" else "Webhook Live", "good"))
    else:
        chips.append(_chip("Webhook Offline", "warn"))

    if staleness is None:
        chips.append(_chip("Waiting On First Alert", "warn"))
    elif staleness <= 30:
        chips.append(_chip(f"Fresh Feed {staleness}m", "good"))
    elif staleness <= 180:
        chips.append(_chip(f"Quiet Feed {staleness}m", "warn"))
    else:
        chips.append(_chip("Standby • no recent alerts", "warn"))
    return "".join(chips)


def _desk_status(webhook_base_url, latest_alert, total_sent, last_sent_alert, latest_error):
    latest_symbol = escape(str((latest_alert or {}).get("symbol") or "Waiting"))
    latest_lane = escape(str((latest_alert or {}).get("trade_style") or "No lane yet"))
    route_label = _route_label(webhook_base_url)
    discord_label = "Live feed armed" if total_sent else "Feed waiting on first hit"
    last_sent_label = _short_time((last_sent_alert or {}).get("time"))
    last_error_label = _short_time((latest_error or {}).get("time"))
    pills = [
        f"<span class='status-pill'>Route <strong>{escape(route_label)}</strong></span>",
        f"<span class='status-pill'>Last Symbol <strong>{latest_symbol}</strong></span>",
        f"<span class='status-pill'>Lane <strong>{latest_lane}</strong></span>",
        f"<span class='status-pill'>Discord <strong>{escape(discord_label)}</strong></span>",
        f"<span class='status-pill'>Last Hit <strong>{escape(last_sent_label)}</strong></span>",
        f"<span class='status-pill'>Last Reject <strong>{escape(last_error_label)}</strong></span>",
    ]
    return "".join(pills)


def _public_webhook_base_url(config, request_base_url=None):
    if request_base_url:
        return request_base_url.rstrip("/")
    tunnel = config.get("tunnel") or {}
    url_file = tunnel.get("public_url_file")
    if url_file and url_file.exists():
        value = url_file.read_text().strip()
        if value.startswith("https://"):
            return value

    log_file = tunnel.get("log_file")
    if log_file and log_file.exists():
        text = log_file.read_text(errors="ignore")
        matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        if matches:
            return matches[-1]
    return None


def _recap_lines(today, week, latest_alert, risk):
    latest_symbol = latest_alert.get("symbol") if latest_alert else "None yet"
    latest_side = latest_alert.get("side") if latest_alert else "N/A"
    latest_style = latest_alert.get("trade_style") if latest_alert else "N/A"
    return (
        f"Today: {today['alerts']} alerts landed, {today['closed']} paper trades closed, { _fmt_money(today['pnl']) } realized.\n"
        f"Week: {week['alerts']} alerts, {week['closed']} paper trades closed, { _fmt_money(week['pnl']) } on the board.\n"
        f"Latest confirmed lane: {latest_style} {latest_symbol} {latest_side}.\n"
        f"Desk note: {risk['note']}"
    )


def _closed_trade_row(item):
    pnl = _trade_pnl(item)
    pnl_class = _pnl_class(pnl)
    style = item.get("trade_style") or item.get("style")
    close_price = item.get("close_price")
    if close_price is None:
        close_price = item.get("exit_contract_price")
    return f"""
    <div class="row">
      <div>
        <div class="alert-symbol">{escape(str(item.get('symbol') or 'N/A'))}</div>
        <div class="alert-meta">{escape(_fmt_contract(item.get('option_symbol')))}</div>
      </div>
      <div>{escape(str(style or 'N/A'))}</div>
      <div><strong class="{pnl_class}">{escape(_fmt_money(pnl))}</strong></div>
      <div>{escape(_fmt(close_price))}</div>
      <div>{escape(_short_time(item.get('closed_at')))}</div>
    </div>
    """


def _leaderboard_row(item):
    return f"""
    <div class="row">
      <div><strong>{escape(item['symbol'])}</strong></div>
      <div>{item['alerts']}</div>
      <div>{item['closed']}</div>
      <div><strong class="{_pnl_class(item['pnl'])}">{escape(_fmt_money(item['pnl']))}</strong></div>
    </div>
    """


def _lane_analytics_row(item):
    label = item.get("style") or "N/A"
    closed = item.get("closed", 0)
    extra = f"{closed} closed • {escape(_fmt_pct(item.get('win_rate')))} WR"
    return f"""
    <div class="row">
      <div>
        <strong>{escape(label)}</strong>
        <div class="alert-meta">{extra}</div>
      </div>
      <div>{item.get('alerts', 0)}</div>
      <div>{closed}</div>
      <div><strong class="{_pnl_class(item.get('pnl'))}">{escape(_fmt_money(item.get('pnl')))}</strong></div>
    </div>
    """


def _chip(label, tone):
    return f"<span class='chip {tone}'>{escape(label)}</span>"


def _ops_row(module, status, detail, last_seen):
    return f"""
    <div class="row">
      <div><strong>{escape(module)}</strong></div>
      <div><span class="chip {_ops_tone(status)}">{escape(status)}</span></div>
      <div>{escape(str(detail or 'N/A'))}</div>
      <div>{escape(_short_time(last_seen))}</div>
    </div>
    """


def _settings_row(area, setting, value, purpose):
    return f"""
    <div class="row">
      <div><strong>{escape(str(area))}</strong></div>
      <div>{escape(str(setting))}</div>
      <div>{escape(str(value))}</div>
      <div>{escape(str(purpose))}</div>
    </div>
    """


def _ops_tone(status):
    label = str(status or "").upper()
    if label in {"LIVE", "CLEAR"}:
        return "good"
    if label in {"WATCHING", "OFF"}:
        return "warn"
    return "bad"


def _dte_window(style_cfg):
    if not style_cfg:
        return "N/A"
    return f"{style_cfg.get('dte_min', 'N/A')}-{style_cfg.get('dte_max', 'N/A')} days"


def _latest_discord_alert(alerts):
    sent_alerts = [alert for alert in alerts if alert.get("discord_sent")]
    return sent_alerts[-1] if sent_alerts else None


def _latest_webhook_error(states):
    latest = None
    latest_time = None
    for state in states.values():
        item = state.get("last_webhook_error") or {}
        if not item.get("message"):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol and symbol in DASHBOARD_HIDDEN_SYMBOLS:
            continue
        parsed = _parse_iso(item.get("time"))
        if latest is None or (parsed and (latest_time is None or parsed > latest_time)):
            latest = item
            latest_time = parsed
    return latest


def _latest_paper_error(states):
    latest = None
    latest_time = None
    for state in states.values():
        item = state.get("last_paper_error") or {}
        if not item.get("message"):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol and symbol in DASHBOARD_HIDDEN_SYMBOLS:
            continue
        parsed = _parse_iso(item.get("time"))
        if latest is None or (parsed and (latest_time is None or parsed > latest_time)):
            latest = item
            latest_time = parsed
    return latest


def _collect_paper_errors(states):
    latest_by_signal = {}

    for style, state in (states or {}).items():
        for item in state.get("recent_paper_errors") or []:
            if not item.get("message"):
                continue
            event = dict(item)
            event.setdefault("trade_style", style)
            signal_id = event.get("signal_id")
            if signal_id:
                previous = latest_by_signal.get(signal_id)
                if not previous or (event.get("time") or "") >= (previous.get("time") or ""):
                    latest_by_signal[signal_id] = event

    return latest_by_signal


def _focus_list(alerts, leaderboard):
    recent_symbols = []
    seen = set()
    for alert in reversed(alerts[-12:]):
        symbol = alert.get("symbol")
        if not symbol or symbol in seen:
            continue
        recent_symbols.append(symbol)
        seen.add(symbol)
        if len(recent_symbols) == 4:
            break
    if not recent_symbols:
        recent_symbols = [item["symbol"] for item in leaderboard[:4]]
    if not recent_symbols:
        return "Watch • waiting on tape"
    return "Watch • " + " / ".join(recent_symbols)


def _route_label(webhook_base_url):
    return "Render Hosted" if webhook_base_url and "onrender.com" in webhook_base_url else "Local Desk"


def _signal_flow_text(last_sent_alert, latest_error):
    if last_sent_alert and latest_error:
        return (
            f"Last Discord send: {last_sent_alert.get('symbol', 'N/A')} "
            f"{last_sent_alert.get('side', 'N/A')} at {_short_time(last_sent_alert.get('time'))}.\n"
            f"Last rejection: {latest_error.get('symbol', 'N/A')} "
            f"at {_short_time(latest_error.get('time'))}.\n"
            f"Reason: {latest_error.get('message', 'N/A')}"
        )
    if last_sent_alert:
        return (
            f"Last Discord send: {last_sent_alert.get('symbol', 'N/A')} "
            f"{last_sent_alert.get('side', 'N/A')} at {_short_time(last_sent_alert.get('time'))}.\n"
            "Flow looks clean right now."
        )
    if latest_error:
        return (
            f"Last rejection: {latest_error.get('symbol', 'N/A')} "
            f"at {_short_time(latest_error.get('time'))}.\n"
            f"Reason: {latest_error.get('message', 'N/A')}"
        )
    return "No Discord sends or rejections yet. The desk is waiting on the first clean hit."


def _loss_streak(closed_positions):
    streak = 0
    for trade in reversed(closed_positions):
        pnl = _trade_pnl(trade)
        if pnl is None:
            continue
        if float(pnl) < 0:
            streak += 1
        else:
            break
    return streak


def _closed_pnl(closed_positions):
    total = 0.0
    found = False
    for position in closed_positions:
        pnl = _trade_pnl(position)
        if pnl is None:
            continue
        total += float(pnl)
        found = True
    return round(total, 2) if found else 0.0


def _trade_pnl(item):
    if not item:
        return None
    pnl = item.get("realized_pnl")
    if pnl is None:
        pnl = item.get("option_pnl")
    if pnl is None:
        pnl = item.get("pnl")
    return pnl


def _pricing_badge(open_position):
    source = open_position.get("pricing_source")
    if source == "polygon":
        return f"Polygon {'Live' if open_position.get('current_contract_price') not in (None, '') else 'Contract Match'}"
    if source and str(source).startswith("alpaca"):
        return f"Alpaca {'Live' if open_position.get('current_contract_price') not in (None, '') else 'Contract Match'}"
    if open_position.get("option_symbol"):
        return "Contract Idea"
    return "N/A"


def _discord_ready(config):
    styles = config.get("styles") or {}
    return all((styles.get(style) or {}).get("discord_webhook") for style in ("LOTTO", "SWING"))


def _discord_detail(config):
    styles = config.get("styles") or {}
    missing = [style for style in ("LOTTO", "SWING") if not (styles.get(style) or {}).get("discord_webhook")]
    if not missing:
        return "LOTTO + SWING webhooks armed"
    return "Missing webhooks: " + ", ".join(missing)


def _alpaca_ready(config):
    alpaca = config.get("alpaca") or {}
    return bool(alpaca.get("api_key") and alpaca.get("secret_key"))


def _flow_state_path(config):
    data_dir = str(config.get("data_dir") or "data")
    return Path(data_dir) / "flow_state.json"


def _load_flow_state_snapshot(config):
    path = _flow_state_path(config)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _flow_diagnostics(config):
    flow = config.get("flow") or {}
    state = _load_flow_state_snapshot(config)

    directional_meta = state.get("last_scan_selection") or {}
    sold_meta = state.get("last_sold_scan_selection") or {}
    directional_posts = state.get("last_posted") or []
    sold_posts = state.get("last_sold_posted") or []
    last_error = str(state.get("last_scan_error") or "").strip()

    return {
        "headline": _flow_headline(flow, state),
        "last_started": state.get("last_scan_started_at"),
        "last_completed": state.get("last_scan_completed_at"),
        "directional_today": int(state.get("daily_alert_count", 0) or 0),
        "sold_today": int(state.get("sold_daily_alert_count", 0) or 0),
        "directional_scan": _flow_scan_counts(
            state.get("last_scan_candidate_count"),
            state.get("last_scan_selected_count"),
            state.get("last_scan_posted_count"),
        ),
        "sold_scan": _flow_scan_counts(
            state.get("last_sold_scan_candidate_count"),
            state.get("last_sold_scan_selected_count"),
            state.get("last_sold_scan_posted_count"),
        ),
        "directional_note": _flow_selection_note(directional_meta, "directional"),
        "sold_note": _flow_selection_note(sold_meta, "sold"),
        "last_error": last_error or "Clear",
        "error_class": "down" if last_error else "up",
        "directional_rows": _flow_post_rows(directional_posts, sold=False),
        "sold_rows": _flow_post_rows(sold_posts, sold=True),
    }


def _flow_headline(flow, state):
    if not flow.get("enabled"):
        return "Scanner disabled in config."
    if state.get("last_scan_error"):
        if "device_challenge_required" in str(state.get("last_scan_error") or ""):
            return "Tastytrade is asking for device verification. Refresh auth first, then the flow lanes can post again."
        return "Last scan hit an error. Check the error tile before the next bell."
    if (
        state.get("last_scan_completed_at")
        and not int(state.get("last_scan_candidate_count", 0) or 0)
        and not int(state.get("last_scan_selected_count", 0) or 0)
        and not int(state.get("last_scan_posted_count", 0) or 0)
        and not int(state.get("last_sold_scan_candidate_count", 0) or 0)
        and not int(state.get("last_sold_scan_selected_count", 0) or 0)
        and not int(state.get("last_sold_scan_posted_count", 0) or 0)
    ):
        return "Auth is live. If you are checking after the close, zeroed scan counts usually reflect an after-hours pass, not a broken scanner."
    if state.get("last_scan_completed_at"):
        return "Scanner is writing real scan state. Empty posts now usually mean filters, cooldowns, or no candidates."
    return "Waiting for the first completed flow scan."


def _flow_scan_counts(candidates, selected, posted):
    return f"{int(candidates or 0)} / {int(selected or 0)} / {int(posted or 0)}"


def _flow_selection_note(meta, lane_label):
    if not meta:
        return f"No {lane_label} selection data yet."

    remaining_today = int(meta.get("remaining_today", 0) or 0)
    skipped = meta.get("skipped") or {}
    top_reasons = [
        f"{reason.replace('_', ' ')} {count}"
        for reason, count in sorted(skipped.items(), key=lambda item: item[1], reverse=True)
        if count
    ][:2]

    parts = [f"Remaining today: {remaining_today}"]
    if meta.get("ranked_by"):
        parts.append(f"Ranked by {meta['ranked_by']}")
    if top_reasons:
        parts.append("Skipped: " + ", ".join(top_reasons))
    return " • ".join(parts)


def _flow_post_rows(items, sold=False):
    rows = []
    for item in items[:6]:
        premium_value = item.get("seller_premium") if sold else item.get("premium")
        note = (
            f"Seller share {round(float(item.get('seller_share', 0.0)) * 100)}%"
            if sold
            else f"{str(item.get('opt_type') or '').upper()} • Vol {int(item.get('volume', 0) or 0):,}"
        )
        rows.append(
            f"""
            <div class="row">
              <div>
                <div class="alert-symbol">{escape(str(item.get('symbol') or 'N/A'))}</div>
                <div class="alert-meta">{escape(str(item.get('expiry') or ''))}</div>
              </div>
              <div>{escape(_fmt_contract(item.get('contract_symbol')))}</div>
              <div>{escape(_fmt_money(premium_value))}</div>
              <div>{escape(_short_time(item.get('posted_at')))}</div>
              <div class="alert-meta">{escape(note)}</div>
            </div>
            """
        )
    return "".join(rows) or "<div class='empty'>No recent posts yet</div>"


def _flow_ready(config):
    flow = config.get("flow") or {}
    return bool(
        flow.get("enabled")
        and flow.get("tastytrade_username")
        and (flow.get("tastytrade_password") or flow.get("tastytrade_remember_token"))
        and flow.get("bull_webhook")
        and flow.get("bear_webhook")
    )


def _flow_detail(config):
    flow = config.get("flow") or {}
    if not flow.get("enabled"):
        return "Flow scanner disabled"
    missing = []
    if not flow.get("tastytrade_username") or not (flow.get("tastytrade_password") or flow.get("tastytrade_remember_token")):
        missing.append("Tastytrade auth")
    if not flow.get("bull_webhook") or not flow.get("bear_webhook"):
        missing.append("Bull/Bear webhooks")
    if not missing:
        return "Scanner configured with bull/bear routes"
    return "Missing: " + ", ".join(missing)


def _sold_flow_ready(config):
    flow = config.get("flow") or {}
    return bool(
        flow.get("enabled")
        and flow.get("tastytrade_username")
        and (flow.get("tastytrade_password") or flow.get("tastytrade_remember_token"))
        and flow.get("sold_calls_webhook")
        and flow.get("sold_puts_webhook")
    )


def _sold_flow_detail(config):
    flow = config.get("flow") or {}
    if not flow.get("enabled"):
        return "Sold premium scanner disabled"
    missing = []
    if not flow.get("tastytrade_username") or not (flow.get("tastytrade_password") or flow.get("tastytrade_remember_token")):
        missing.append("Tastytrade auth")
    if not flow.get("sold_calls_webhook") or not flow.get("sold_puts_webhook"):
        missing.append("Sold call/put webhooks")
    if not missing:
        return "Scanner configured with sold-call and sold-put routes"
    return "Missing: " + ", ".join(missing)


def _heatmap_ready(config):
    heatmap = config.get("heatmap") or {}
    return bool(heatmap.get("enabled") and heatmap.get("discord_webhook"))


def _heatmap_detail(config):
    heatmap = config.get("heatmap") or {}
    if not heatmap.get("enabled"):
        return "Heatmap disabled"
    if not heatmap.get("discord_webhook"):
        return "Discord webhook missing"
    return "Discord heatmap posting armed"


def _status_controls(style, open_position):
    if not open_position:
        return ""
    actions = ["ENTERED", "TRIMMED", "TP1 HIT", "STOPPED", "CLOSED"]
    buttons = []
    for action in actions:
        action_value = action.replace(" ", "_")
        buttons.append(
            f"""
            <form method="post" action="/position/action">
              <input type="hidden" name="trade_style" value="{escape(style)}">
              <input type="hidden" name="action" value="{escape(action_value)}">
              <button type="submit">{escape(action)}</button>
            </form>
            """
        )
    return f"<div class='controls'>{''.join(buttons)}</div>"


def _fmt_contract(value):
    if not value:
        return "N/A"
    symbol = str(value)
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
        return str(value)


def _fmt(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_money(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_ratio_pct(value):
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
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


def _fmt_timeframe(value):
    if value in (None, ""):
        return "No TF"
    text = str(value).strip()
    mapping = {
        "1": "1m",
        "3": "3m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "45": "45m",
        "60": "1h",
        "120": "2h",
        "240": "4h",
        "D": "1D",
        "W": "1W",
    }
    return mapping.get(text, text)


def _short_time(value):
    if not value:
        return "Never"
    text = str(value)
    if "T" in text:
        text = text.replace("T", " ")
    return text[:19]


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _win_rate(stats):
    wins = int(stats.get("wins", 0))
    losses = int(stats.get("losses", 0))
    total = wins + losses
    if total == 0:
        return "N/A"
    return f"{round((wins / total) * 100)}%"


def _pnl_class(value):
    if value is None:
        return ""
    if float(value) > 0:
        return "up"
    if float(value) < 0:
        return "down"
    return ""


def _status_class(status):
    status = str(status or "").upper()
    if status in {"TP1 HIT", "CLOSED"}:
        return "up"
    if status == "STOPPED":
        return "down"
    if status in {"ENTERED", "TRIMMED"}:
        return "warn"
    return ""


def _paper_section(paper):
    """Render the full paper trading P&L panel for the dashboard."""
    stats   = paper.get("stats") or {}
    opens   = paper.get("open_positions") or []
    closed  = paper.get("recent_closed") or []
    lotto_open = [item for item in opens if str(item.get("style") or "").upper() == "LOTTO"]
    swing_open = [item for item in opens if str(item.get("style") or "").upper() == "SWING"]
    lotto_closed = [item for item in closed if str(item.get("style") or "").upper() == "LOTTO"]
    swing_closed = [item for item in closed if str(item.get("style") or "").upper() == "SWING"]

    total_pnl   = stats.get("total_pnl", 0.0)
    lotto_pnl   = stats.get("lotto_pnl", 0.0)
    swing_pnl   = stats.get("swing_pnl", 0.0)
    total_trades= stats.get("total_trades", 0)
    wins        = stats.get("wins", 0)
    losses      = stats.get("losses", 0)
    win_rate    = stats.get("win_rate", 0)
    lotto_trades= stats.get("lotto_trades", 0)
    swing_trades= stats.get("swing_trades", 0)

    def pnl_color(v):
        return "#00e676" if v >= 0 else "#ff1744"

    def fmt_pnl(v):
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:.2f}"

    def contracts_for(item, *, closed=False):
        keys = (
            ("contracts_closed", "contracts_before_close", "initial_contracts", "contracts")
            if closed
            else ("contracts", "initial_contracts")
        )
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                try:
                    return max(1, int(value))
                except (TypeError, ValueError):
                    continue
        return 1

    def deployed_capital(entry_price, contracts):
        try:
            return round(float(entry_price) * 100 * int(contracts), 2)
        except (TypeError, ValueError):
            return None

    def one_contract_pnl(entry_price, mark_price):
        try:
            return round((float(mark_price) - float(entry_price)) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def one_contract_live_total(items):
        values = [
            one_contract_pnl(item.get("entry_contract_price"), item.get("current_contract_price"))
            for item in items
        ]
        values = [value for value in values if value is not None]
        return round(sum(values), 2) if values else 0.0

    def average_live_pct(items):
        values = [item.get("live_pnl_pct") for item in items if item.get("live_pnl_pct") not in (None, "")]
        if not values:
            return None
        return round(sum(float(value) for value in values) / len(values), 2)

    def open_rows_for(items):
        if not items:
            return "<div style='color:#555;font-size:13px;padding:12px 0'>No open positions</div>"
        rows = ""
        for p in items:
            sym         = escape(str(p.get("symbol", "")))
            side        = escape(str(p.get("side", "")))
            entry       = p.get("entry_contract_price") or 0
            unreal      = p.get("unrealized_pnl", 0.0) or 0.0
            opt_sym     = escape(str(p.get("option_symbol", "—")))
            entered     = str(p.get("entered_at", ""))[:16].replace("T", " ")
            unreal_pct  = p.get("live_pnl_pct")
            contracts   = contracts_for(p)
            deployed    = deployed_capital(entry, contracts)
            one_lot     = one_contract_pnl(entry, p.get("current_contract_price"))
            contract_meta = ""
            if deployed is not None:
                contract_meta = f"{_fmt_money(deployed)} deployed"
            unreal_text = fmt_pnl(unreal)
            if unreal_pct not in (None, ""):
                unreal_text = f"{unreal_text}<div style='font-size:10px;color:#777'>{_fmt_pct(unreal_pct)}</div>"
            if one_lot is not None:
                unreal_text = f"{unreal_text}<div style='font-size:10px;color:#666'>1ct {fmt_pnl(one_lot)}</div>"
            rows += f"""
              <div style="display:grid;grid-template-columns:80px 60px 1fr 60px 70px 100px 100px;
                          gap:8px;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);
                          font-size:12px;align-items:center">
                <span style="font-weight:600">{sym}</span>
                <span style="background:{'rgba(0,230,118,0.15)' if side=='CALL' else 'rgba(255,23,68,0.15)'};
                      color:{'#00e676' if side=='CALL' else '#ff1744'};padding:2px 6px;border-radius:4px;
                      font-size:10px;font-weight:600">{side}</span>
                <span style="color:#aaa;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{opt_sym}<span style='display:block;font-size:10px;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{contract_meta}</span></span>
                <span style="font-weight:600">{contracts}</span>
                <span>${entry:.2f}</span>
                <span style="color:{pnl_color(unreal)};font-weight:600">{unreal_text}</span>
                <span style="color:#666">{entered}</span>
              </div>"""
        return f"""
            <div style="background:rgba(255,255,255,0.03);border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,0.08)">
              <div style="display:grid;grid-template-columns:80px 60px 1fr 60px 70px 100px 100px;
                          gap:8px;padding:8px 10px;background:rgba(255,255,255,0.05);
                          font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em">
                <span>Symbol</span><span>Side</span><span>Contract</span><span>Qty</span><span>Entry</span><span>Unreal P&amp;L</span><span>Entered</span>
              </div>
              {rows}
            </div>"""

    def closed_rows_for(items):
        if not items:
            return "<div style='color:#555;font-size:13px;padding:12px 0'>No exit events yet</div>"
        rows = ""
        for p in items:
            sym     = escape(str(p.get("symbol", "")))
            side    = escape(str(p.get("side", "")))
            entry   = p.get("entry_contract_price") or 0
            exit_px = p.get("exit_contract_price")
            rpnl    = p.get("realized_pnl", 0.0) or 0.0
            contracts = contracts_for(p, closed=True)
            remaining_after = p.get("remaining_contracts_after")
            exit_type = "Final Close"
            if remaining_after not in (None, ""):
                try:
                    if int(remaining_after) > 0:
                        exit_type = "Trim"
                except (TypeError, ValueError):
                    pass
            deployed = deployed_capital(entry, contracts)
            one_lot = one_contract_pnl(entry, exit_px) if exit_px is not None else None
            pct     = None
            if entry:
                try:
                    pct = round(((float(exit_px) - float(entry)) / float(entry)) * 100, 2) if exit_px is not None else None
                except (TypeError, ValueError, ZeroDivisionError):
                    pct = None
            closed_at = str(p.get("closed_at", ""))[:16].replace("T", " ")
            pnl_text = fmt_pnl(rpnl)
            if pct not in (None, ""):
                pnl_text = f"{pnl_text}<div style='font-size:10px;color:#777'>{_fmt_pct(pct)}</div>"
            if one_lot is not None:
                pnl_text = f"{pnl_text}<div style='font-size:10px;color:#666'>1ct {fmt_pnl(one_lot)}</div>"
            exit_text = f"${exit_px:.2f}" if exit_px is not None else "—"
            exit_meta = ""
            if deployed is not None:
                exit_meta = f"{_fmt_money(deployed)} deployed"
            rows += f"""
              <div style="display:grid;grid-template-columns:80px 60px 70px 60px 70px 90px 100px 100px;
                          gap:8px;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);
                          font-size:12px;align-items:center">
                <span style="font-weight:600">{sym}</span>
                <span style="background:{'rgba(0,230,118,0.15)' if side=='CALL' else 'rgba(255,23,68,0.15)'};
                      color:{'#00e676' if side=='CALL' else '#ff1744'};padding:2px 6px;border-radius:4px;
                      font-size:10px;font-weight:600">{side}</span>
                <span style="font-size:10px;color:#bbb;font-weight:600">{exit_type}</span>
                <span style="font-weight:600">{contracts}</span>
                <span>${entry:.2f}</span>
                <span>{exit_text}<span style='display:block;font-size:10px;color:#666'>{exit_meta}</span></span>
                <span style="color:{pnl_color(rpnl)};font-weight:600">{pnl_text}</span>
                <span style="color:#555;font-size:11px">{closed_at}</span>
              </div>"""
        return f"""
            <div style="background:rgba(255,255,255,0.03);border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,0.08)">
              <div style="display:grid;grid-template-columns:80px 60px 70px 60px 70px 90px 100px 100px;
                          gap:8px;padding:8px 10px;background:rgba(255,255,255,0.05);
                          font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em">
                <span>Symbol</span><span>Side</span><span>Exit Type</span><span>Qty</span><span>Entry</span><span>Exit</span><span>P&amp;L</span><span>Closed</span>
              </div>
              {rows}
            </div>"""

    def style_panel(label, tone, pnl, trades_count, open_items, closed_items):
        win_count = sum(1 for item in closed_items if (item.get("realized_pnl") or 0) > 0)
        loss_count = sum(1 for item in closed_items if (item.get("realized_pnl") or 0) <= 0)
        wr = round((win_count / len(closed_items)) * 100) if closed_items else 0
        one_ct_live = one_contract_live_total(open_items)
        avg_live = average_live_pct(open_items)
        one_ct_text = fmt_pnl(one_ct_live)
        avg_live_text = _fmt_pct(avg_live) if avg_live is not None else "N/A"
        return f"""
          <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:16px">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px">
              <div style="font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:{tone}">{label} P&amp;L</div>
              <div style="font-size:20px;font-weight:700;color:{pnl_color(pnl)}">{fmt_pnl(pnl)}</div>
            </div>
            <div style="font-size:11px;color:#777;line-height:1.45;margin-bottom:12px">
              Dollar P&amp;L reflects actual sized contracts. Gray sublines show percent return and the 1-contract equivalent so you can compare signal quality across names.
            </div>
            <div class="paper-lane-metrics">
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">Completed Trades</div><div style="font-size:18px;font-weight:600">{trades_count}</div></div>
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">Win Rate</div><div style="font-size:18px;font-weight:600">{wr}%</div></div>
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">Open</div><div style="font-size:18px;font-weight:600">{len(open_items)}</div></div>
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">Exit W / L</div><div style="font-size:18px;font-weight:600">{win_count}/{loss_count}</div></div>
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">1CT Live</div><div style="font-size:18px;font-weight:600;color:{pnl_color(one_ct_live)}">{one_ct_text}</div></div>
              <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 12px"><div style="font-size:10px;color:#888;text-transform:uppercase">Avg Live %</div><div style="font-size:18px;font-weight:600;color:{'#00e676' if (avg_live or 0) >= 0 else '#ff1744'}">{avg_live_text}</div></div>
            </div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Open Positions</div>
            {open_rows_for(open_items)}
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin:14px 0 8px">Recent Exit Events</div>
            {closed_rows_for(closed_items)}
          </div>"""

    # ── Stat cards ───────────────────────────────────────────────────────
    stat_cards = f"""
        <div class="paper-stat-cards">
          <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px">
            <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Total P&L</div>
            <div style="font-size:20px;font-weight:600;color:{pnl_color(total_pnl)}">{fmt_pnl(total_pnl)}</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px">
            <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Win Rate</div>
            <div style="font-size:20px;font-weight:600;color:{'#00e676' if win_rate>=50 else '#ff9800'}">{win_rate}%</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px">
            <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Trades</div>
            <div style="font-size:20px;font-weight:600">{wins}W / {losses}L</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px">
            <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Lotto P&L</div>
            <div style="font-size:20px;font-weight:600;color:{pnl_color(lotto_pnl)}">{fmt_pnl(lotto_pnl)}</div>
            <div style="font-size:10px;color:#666;margin-top:2px">{lotto_trades} trades</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px">
            <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Swing P&L</div>
            <div style="font-size:20px;font-weight:600;color:{pnl_color(swing_pnl)}">{fmt_pnl(swing_pnl)}</div>
            <div style="font-size:10px;color:#666;margin-top:2px">{swing_trades} trades</div>
          </div>
        </div>"""

    style_sections = f"""
        <div class="paper-lane-grid">
          {style_panel('LOTTO', '#ffb727', lotto_pnl, lotto_trades, lotto_open, lotto_closed)}
          {style_panel('SWING', '#8ad7ff', swing_pnl, swing_trades, swing_open, swing_closed)}
        </div>"""

    empty_note = "" if total_trades > 0 else """
        <div style="text-align:center;padding:20px 0;color:#555;font-size:13px">
          Paper trading is live. Results will appear here after Monday's first signal fires.
        </div>"""

    return f"""
        <section style="margin-top:20px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
            <div style="width:8px;height:8px;border-radius:50%;background:#ffb727;
                        animation:pulse 2s infinite"></div>
            <div style="font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
                        color:#ffb727">Paper Trading Engine</div>
            <div style="font-size:11px;color:#555;margin-left:4px">Alpaca Paper · Auto TP/SL · LOTTO closes 3:55 PM ET · SWING can hold overnight</div>
          </div>
          <div style="background:rgba(255,183,39,0.04);border:1px solid rgba(255,183,39,0.18);
                      border-radius:10px;padding:18px 20px">
            {empty_note}
            {stat_cards}
            {style_sections}
          </div>
        </section>"""
