from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import re

from monster.options_data import attach_live_pnl
from monster.store import load_all_states
try:
    from monster.paper_trader import get_paper_summary
    _PAPER_TRADER_AVAILABLE = True
except Exception:
    _PAPER_TRADER_AVAILABLE = False
    def get_paper_summary(config):
        return {"open_positions": [], "recent_closed": [], "stats": {}}


def render_dashboard(config, public_base_url=None):
    states = load_all_states(config)
    states = attach_live_pnl(config, states)

    alerts = _collect_alerts(states)
    closed_positions = _collect_closed_positions(states)
    latest_alert = alerts[-1] if alerts else None
    last_sent_alert = _latest_discord_alert(alerts)
    latest_error = _latest_webhook_error(states)
    today = _summary_window(alerts, closed_positions, timedelta(days=1))
    week = _summary_window(alerts, closed_positions, timedelta(days=7))
    leaderboard = _leaderboard(alerts, closed_positions)
    risk = _risk_snapshot(states, alerts, closed_positions)
    webhook_base_url = _public_webhook_base_url(config, public_base_url)
    health = _health_snapshot(config, states, webhook_base_url)
    focus_list = _focus_list(alerts, leaderboard)

    total_alerts = sum(int((state.get("stats") or {}).get("alerts_received", 0)) for state in states.values())
    total_sent = sum(int((state.get("stats") or {}).get("discord_sent", 0)) for state in states.values())
    total_closed_pnl = sum(_closed_pnl(state.get("closed_positions") or []) for state in states.values())
    last_seen = max(
        (state.get("last_updated") for state in states.values() if state.get("last_updated")),
        default="Never",
    )

    style_cards = "".join(_style_card(style, state) for style, state in states.items())
    closed_rows = "".join(_closed_trade_row(item) for item in reversed(closed_positions[-8:])) or (
        "<div class='empty'>No closed trades yet</div>"
    )
    leaderboard_rows = "".join(_leaderboard_row(item) for item in leaderboard) or (
        "<div class='empty'>Leaderboard wakes up after more alerts land</div>"
    )
    recap_lines = _recap_lines(today, week, latest_alert, risk)

    hero = _hero(latest_alert)

    # Paper trading summary
    paper = get_paper_summary(config) if _PAPER_TRADER_AVAILABLE else {"open_positions": [], "recent_closed": [], "stats": {}}
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
        }}
        * {{
          box-sizing: border-box;
        }}
        body {{
          margin: 0;
          font-family: Inter, Arial, sans-serif;
          background:
            radial-gradient(circle at top left, rgba(206, 17, 38, 0.24), transparent 28%),
            radial-gradient(circle at top right, rgba(255, 255, 255, 0.08), transparent 18%),
            linear-gradient(180deg, #0b0b0d 0%, #151518 100%);
          color: #f4f4f5;
        }}
        main {{
          max-width: 1280px;
          margin: 0 auto;
          padding: 18px 18px 44px;
        }}
        .topbar, .panel, .hero-card, .card, .summary div {{
          box-shadow: 0 12px 30px rgba(0, 0, 0, 0.34);
        }}
        .topbar {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 14px;
          padding: 10px 14px;
          background: rgba(20, 20, 24, 0.9);
          border: 1px solid rgba(206, 17, 38, 0.28);
          border-radius: 8px;
          backdrop-filter: blur(10px);
        }}
        .brand {{
          display: flex;
          align-items: center;
          gap: 10px;
        }}
        .brand-mark {{
          width: 28px;
          height: 28px;
          border-radius: 8px;
          background: linear-gradient(135deg, #ce1126 0%, #8f0f1f 100%);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 15px;
          font-weight: 800;
          color: white;
        }}
        .sub {{
          margin-top: 8px;
          color: #c8aab0;
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
          background: rgba(28, 28, 33, 0.98);
          border: 1px solid rgba(206, 17, 38, 0.16);
          color: #f3c7ce;
          font-size: 12px;
        }}
        .chip.good {{ color: #8cffb0; border-color: rgba(118,255,163,.22); }}
        .chip.warn {{ color: #ffd37e; border-color: rgba(255,211,126,.22); }}
        .chip.bad {{ color: #ff9aa7; border-color: rgba(255,154,167,.22); }}
        .status-pill {{
          color: #f6d9de;
        }}
        .status-pill strong {{
          color: #ffffff;
          font-weight: 700;
        }}
        .hero {{
          display: grid;
          grid-template-columns: 1.5fr 1fr;
          gap: 16px;
          margin-bottom: 16px;
        }}
        .hero-card, .panel, .card, .summary div {{
          background: rgba(20, 20, 25, 0.96);
          border: 1px solid rgba(206, 17, 38, 0.16);
          border-radius: 8px;
          padding: 16px;
          backdrop-filter: blur(12px);
        }}
        .hero-card {{
          min-height: 220px;
          background:
            linear-gradient(135deg, rgba(206,17,38,.14), rgba(20,20,25,.98) 38%),
            rgba(20,20,25,.96);
        }}
        .hero-title {{
          font-size: 13px;
          text-transform: uppercase;
          letter-spacing: .05em;
          color: #d6b0b7;
          margin-bottom: 8px;
        }}
        .hero-symbol {{
          font-size: 40px;
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
          color: #cba8af;
          font-size: 12px;
          margin-bottom: 6px;
          text-transform: uppercase;
        }}
        .summary strong {{
          font-size: 22px;
        }}
        .stat, .grid-stat {{
          background: rgba(12, 12, 16, 0.96);
          border: 1px solid rgba(206, 17, 38, 0.12);
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
        .card.lotto {{ border-top: 3px solid #ce1126; }}
        .card.swing {{ border-top: 3px solid #ffffff; }}
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
          background: rgba(255, 255, 255, 0.08);
          color: #f4f4f5;
        }}
        .tag.buy {{ background: rgba(206, 17, 38, 0.16); color: #ff8d9a; }}
        .tag.sell {{ background: rgba(255, 255, 255, 0.14); color: #f5f5f5; }}
        .metrics, .strip, .position-grid {{
          display: grid;
          gap: 8px;
          margin-bottom: 12px;
        }}
        .metrics {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
        .strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
        .position-grid {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
        .metrics div, .strip div, .position-grid div, .hero-grid div {{
          background: rgba(12, 12, 16, 0.96);
          border: 1px solid rgba(206, 17, 38, 0.12);
          border-radius: 8px;
          padding: 10px;
        }}
        .metrics span, .strip span, .position-grid span, .hero-grid span {{
          display: block;
          color: #b79097;
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
          font-size: 13px;
          font-weight: 700;
          margin-bottom: 8px;
          color: #fff2f4;
          text-transform: uppercase;
          letter-spacing: .04em;
        }}
        .table {{
          border: 1px solid rgba(206, 17, 38, 0.14);
          border-radius: 8px;
          overflow: hidden;
          background: rgba(10, 10, 13, 0.92);
        }}
        .table-head, .row {{
          display: grid;
          gap: 8px;
          align-items: center;
          padding: 10px 12px;
        }}
        .table-head {{
          color: #ba969d;
          font-size: 11px;
          text-transform: uppercase;
          border-bottom: 1px solid rgba(206, 17, 38, 0.14);
        }}
        .row {{
          border-bottom: 1px solid rgba(206, 17, 38, 0.08);
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
        .alert-meta, .muted {{
          color: #c1a6ab;
          font-size: 12px;
        }}
        .alert-symbol {{
          font-size: 14px;
          font-weight: 700;
        }}
        .recap-box {{
          white-space: pre-wrap;
          line-height: 1.5;
          font-size: 14px;
          color: #f7e8eb;
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
          color: #b89097;
          padding: 14px 12px;
        }}
        @media (max-width: 940px) {{
          .hero, .layout {{
            grid-template-columns: 1fr;
          }}
          .summary {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
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
          .hero-symbol {{
            font-size: 30px;
          }}
          .alert-table .table-head, .alert-table .row,
          .closed-table .table-head, .closed-table .row,
          .leader-table .table-head, .leader-table .row {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
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
            <div class="ticker-pill">{escape(focus_list)}</div>
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
              <div><span>Net Closed P&amp;L</span><strong class="{_pnl_class(total_closed_pnl)}">{escape(_fmt_money(total_closed_pnl))}</strong></div>
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
            <div class="section-title" style="margin-top:14px;">Webhook</div>
            <div class="recap-box">{escape((webhook_base_url + "/webhook/tradingview") if webhook_base_url else "Webhook unavailable")}</div>
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

        <section class="grid">
          {style_cards}
        </section>

        <section class="layout">
          <section class="panel">
            <div class="section-title">Recent Closed Trades</div>
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


def _style_card(style, state):
    alerts = state.get("recent_alerts", [])
    last = state.get("last_alert") or {}
    open_position = state.get("open_position") or {}
    stats = state.get("stats") or {}
    closed_positions = state.get("closed_positions") or []
    last_webhook_error = state.get("last_webhook_error") or {}
    win_rate = _win_rate(stats)
    closed_pnl = _closed_pnl(closed_positions)
    live_pnl = open_position.get("live_pnl")

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
    position_entry = escape(_fmt(open_position.get("entry_price")))
    position_stop = escape(_fmt(open_position.get("stop")))
    position_tp1 = escape(_fmt(open_position.get("tp1")))
    option_symbol = escape(_fmt_contract(open_position.get("option_symbol")))
    option_entry = escape(_fmt_money(open_position.get("entry_contract_price")))
    option_mark = escape(_fmt_money(open_position.get("current_contract_price")))
    live_pnl_class = _pnl_class(live_pnl)
    closed_pnl_class = _pnl_class(closed_pnl)
    pricing_badge = escape(_pricing_badge(open_position))
    position_status = escape(str(open_position.get("status") or "N/A"))
    status_class = _status_class(open_position.get("status"))
    style_class = style.lower()
    controls = _status_controls(style, open_position)
    webhook_error_block = ""
    if last_webhook_error.get("message"):
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
        <div><span>Alerts</span><strong>{escape(str(stats.get("alerts_received", 0)))}</strong></div>
        <div><span>Sent</span><strong>{escape(str(stats.get("discord_sent", 0)))}</strong></div>
        <div><span>Wins</span><strong>{escape(str(stats.get("wins", 0)))}</strong></div>
        <div><span>Losses</span><strong>{escape(str(stats.get("losses", 0)))}</strong></div>
      </div>

      <div class="strip">
        <div><span>Last Update</span><strong>{escape(_short_time(state.get("last_updated")))}</strong></div>
        <div><span>Discord</span><strong>{escape(last_sent)}</strong></div>
        <div><span>Win Rate</span><strong>{escape(win_rate)}</strong></div>
      </div>

      <div class="strip">
        <div><span>Closed P&amp;L</span><strong class="{closed_pnl_class}">{escape(_fmt_money(closed_pnl))}</strong></div>
        <div><span>Live P&amp;L</span><strong class="{live_pnl_class}">{escape(_fmt_money(live_pnl))}</strong></div>
        <div><span>Status</span><strong class="{status_class}">{position_status}</strong></div>
      </div>
      {webhook_error_block}

      <div class="position">
        <div class="section-title">Open Position / Contract Idea</div>
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
          <div><span>Live P&amp;L %</span><strong class="{live_pnl_class}">{escape(_fmt_pct(open_position.get("live_pnl_pct")))}</strong></div>
        </div>
        {controls}
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


def _collect_alerts(states):
    alerts = []
    for state in states.values():
        alerts.extend(state.get("recent_alerts") or [])
    alerts.sort(key=lambda item: item.get("time") or "")
    return alerts


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
            value = item.get("option_pnl")
            if value is None:
                value = item.get("pnl")
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
        value = trade.get("option_pnl")
        if value is None:
            value = trade.get("pnl")
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
        f"Today: {today['alerts']} alerts landed, {today['closed']} trades closed, { _fmt_money(today['pnl']) } realized.\n"
        f"Week: {week['alerts']} alerts, {week['closed']} closed trades, { _fmt_money(week['pnl']) } on the board.\n"
        f"Latest confirmed lane: {latest_style} {latest_symbol} {latest_side}.\n"
        f"Desk note: {risk['note']}"
    )


def _closed_trade_row(item):
    pnl = item.get("option_pnl")
    if pnl is None:
        pnl = item.get("pnl")
    pnl_class = _pnl_class(pnl)
    return f"""
    <div class="row">
      <div>
        <div class="alert-symbol">{escape(str(item.get('symbol') or 'N/A'))}</div>
        <div class="alert-meta">{escape(_fmt_contract(item.get('option_symbol')))}</div>
      </div>
      <div>{escape(str(item.get('trade_style') or 'N/A'))}</div>
      <div><strong class="{pnl_class}">{escape(_fmt_money(pnl))}</strong></div>
      <div>{escape(_fmt(item.get('close_price')))}</div>
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


def _chip(label, tone):
    return f"<span class='chip {tone}'>{escape(label)}</span>"


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
        parsed = _parse_iso(item.get("time"))
        if latest is None or (parsed and (latest_time is None or parsed > latest_time)):
            latest = item
            latest_time = parsed
    return latest


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
        pnl = trade.get("option_pnl")
        if pnl is None:
            pnl = trade.get("pnl")
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
        pnl = position.get("option_pnl")
        if pnl is None:
            continue
        total += float(pnl)
        found = True
    return round(total, 2) if found else 0.0


def _pricing_badge(open_position):
    source = open_position.get("pricing_source")
    if source == "polygon":
        return f"Polygon {'Live' if open_position.get('current_contract_price') not in (None, '') else 'Contract Match'}"
    if source and str(source).startswith("alpaca"):
        return f"Alpaca {'Live' if open_position.get('current_contract_price') not in (None, '') else 'Contract Match'}"
    if open_position.get("option_symbol"):
        return "Contract Idea"
    return "N/A"


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

    # ── Stat cards ───────────────────────────────────────────────────────
    stat_cards = f"""
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px">
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

    # ── Open positions ────────────────────────────────────────────────────
    if opens:
        open_rows = ""
        for p in opens:
            sym         = escape(str(p.get("symbol", "")))
            side        = escape(str(p.get("side", "")))
            style       = escape(str(p.get("style", "")))
            contracts   = p.get("contracts", 1)
            entry       = p.get("entry_contract_price") or 0
            current     = p.get("current_contract_price") or entry
            unreal      = p.get("unrealized_pnl", 0.0) or 0.0
            opt_sym     = escape(str(p.get("option_symbol", "—")))
            tp          = p.get("tp")
            sl          = p.get("sl")
            entered     = str(p.get("entered_at", ""))[:16].replace("T", " ")
            underlying  = p.get("current_underlying_price")
            und_str     = f"${underlying:.2f}" if underlying else "—"

            open_rows += f"""
              <div style="display:grid;grid-template-columns:80px 60px 60px 1fr 70px 70px 80px 80px 80px;
                          gap:8px;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);
                          font-size:12px;align-items:center">
                <span style="font-weight:600">{sym}</span>
                <span style="background:{'rgba(0,230,118,0.15)' if side=='CALL' else 'rgba(255,23,68,0.15)'};
                      color:{'#00e676' if side=='CALL' else '#ff1744'};padding:2px 6px;border-radius:4px;
                      font-size:10px;font-weight:600">{side}</span>
                <span style="background:rgba(255,183,39,0.12);color:#ffb727;padding:2px 6px;
                      border-radius:4px;font-size:10px">{style}</span>
                <span style="color:#aaa;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{opt_sym}</span>
                <span>${entry:.2f}</span>
                <span>{und_str}</span>
                <span>TP: {f"${float(tp):.2f}" if tp else "—"} / SL: {f"${float(sl):.2f}" if sl else "—"}</span>
                <span style="color:{pnl_color(unreal)};font-weight:600">{fmt_pnl(unreal)}</span>
                <span style="color:#666">{entered}</span>
              </div>"""

        open_section = f"""
          <div style="margin-bottom:16px">
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">
              Open Positions ({len(opens)})
            </div>
            <div style="background:rgba(255,255,255,0.03);border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,0.08)">
              <div style="display:grid;grid-template-columns:80px 60px 60px 1fr 70px 70px 80px 80px 80px;
                          gap:8px;padding:8px 10px;background:rgba(255,255,255,0.05);
                          font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em">
                <span>Symbol</span><span>Side</span><span>Style</span><span>Contract</span>
                <span>Entry $</span><span>Underlying</span><span>TP / SL</span>
                <span>Unreal P&L</span><span>Entered</span>
              </div>
              {open_rows}
            </div>
          </div>"""
    else:
        open_section = """
          <div style="margin-bottom:16px">
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Open Positions</div>
            <div style="color:#555;font-size:13px;padding:16px 0">No open paper positions</div>
          </div>"""

    # ── Recent closed ─────────────────────────────────────────────────────
    if closed:
        closed_rows = ""
        for p in closed:
            sym     = escape(str(p.get("symbol", "")))
            side    = escape(str(p.get("side", "")))
            style   = escape(str(p.get("style", "")))
            entry   = p.get("entry_contract_price") or 0
            exit_px = p.get("exit_contract_price")
            rpnl    = p.get("realized_pnl", 0.0) or 0.0
            reason  = escape(str(p.get("exit_reason", "—")))
            closed_at = str(p.get("closed_at", ""))[:16].replace("T", " ")

            closed_rows += f"""
              <div style="display:grid;grid-template-columns:80px 60px 60px 70px 70px 1fr 90px 100px;
                          gap:8px;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06);
                          font-size:12px;align-items:center">
                <span style="font-weight:600">{sym}</span>
                <span style="background:{'rgba(0,230,118,0.15)' if side=='CALL' else 'rgba(255,23,68,0.15)'};
                      color:{'#00e676' if side=='CALL' else '#ff1744'};padding:2px 6px;
                      border-radius:4px;font-size:10px;font-weight:600">{side}</span>
                <span style="background:rgba(255,183,39,0.12);color:#ffb727;padding:2px 6px;
                      border-radius:4px;font-size:10px">{style}</span>
                <span>${entry:.2f}</span>
                <span>{f"${exit_px:.2f}" if exit_px is not None else "—"}</span>
                <span style="color:#aaa;font-size:11px">{reason}</span>
                <span style="color:{pnl_color(rpnl)};font-weight:600">{fmt_pnl(rpnl)}</span>
                <span style="color:#555;font-size:11px">{closed_at}</span>
              </div>"""

        closed_section = f"""
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">
              Recent Closed ({len(closed)})
            </div>
            <div style="background:rgba(255,255,255,0.03);border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,0.08)">
              <div style="display:grid;grid-template-columns:80px 60px 60px 70px 70px 1fr 90px 100px;
                          gap:8px;padding:8px 10px;background:rgba(255,255,255,0.05);
                          font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em">
                <span>Symbol</span><span>Side</span><span>Style</span>
                <span>Entry</span><span>Exit</span><span>Reason</span>
                <span>P&L</span><span>Closed</span>
              </div>
              {closed_rows}
            </div>
          </div>"""
    else:
        closed_section = """
          <div>
            <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Recent Closed</div>
            <div style="color:#555;font-size:13px;padding:16px 0">Paper trades will appear here after they close</div>
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
            <div style="font-size:11px;color:#555;margin-left:4px">Alpaca Paper · Auto TP/SL · Force close 3:55 PM ET</div>
          </div>
          <div style="background:rgba(255,183,39,0.04);border:1px solid rgba(255,183,39,0.18);
                      border-radius:10px;padding:18px 20px">
            {empty_note}
            {stat_cards}
            {open_section}
            {closed_section}
          </div>
        </section>"""
