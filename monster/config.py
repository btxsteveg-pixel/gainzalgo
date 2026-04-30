from pathlib import Path
import os

DEFAULT_ALLOWED_SYMBOLS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK.B", "JPM",
    "LLY", "V", "MA", "NFLX", "XOM", "COST", "WMT", "UNH", "ORCL", "HD",
    "PG", "JNJ", "BAC", "ABBV", "KO", "AMD", "CRM", "MRK", "PEP", "ADBE",
    "CSCO", "ABT", "TMO", "ACN", "MCD", "DHR", "QCOM", "DIS", "TXN", "INTU",
    "AMGN", "PFE", "CMCSA", "NEE", "PM", "LIN", "HON", "UNP", "LOW", "INTC",
    "IBM", "CAT", "GE", "NOW", "BKNG", "GS", "PLTR", "UBER", "PANW", "MU",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "XLK", "XLF", "XLE", "SMH",
    "SOXX", "ARKK", "XLI", "XLV", "XLP",
]


def load_config():
    _load_dotenv()

    base_dir = Path(__file__).resolve().parent.parent
    legacy_data_dir = base_dir / "data"
    data_dir = _resolve_data_dir(base_dir, legacy_data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    return {
        "base_dir": base_dir,
        "legacy_data_dir": legacy_data_dir,
        "data_dir": data_dir,
        "secret": os.getenv("TRADINGVIEW_WEBHOOK_SECRET", ""),
        "host": os.getenv("TV_WEBHOOK_HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT") or os.getenv("TV_WEBHOOK_PORT", "8787")),
        "public_base_url": os.getenv("PUBLIC_BASE_URL", "").strip(),
        "polygon": {
            "api_key": os.getenv("POLYGON_API_KEY", ""),
            "base_url": os.getenv("POLYGON_BASE_URL", "https://api.polygon.io"),
        },
        "alpaca": {
            "api_key": os.getenv("ALPACA_API_KEY", ""),
            "secret_key": os.getenv("ALPACA_SECRET_KEY", ""),
            "data_base_url": os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
            "trading_base_url": os.getenv("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets"),
            "options_feed": os.getenv("ALPACA_OPTIONS_FEED", "indicative"),
        },
        "discord": {
            "timeout_seconds": float(os.getenv("DISCORD_TIMEOUT_SECONDS", "6")),
            "max_retries": int(os.getenv("DISCORD_MAX_RETRIES", "2")),
            "retry_backoff_seconds": float(os.getenv("DISCORD_RETRY_BACKOFF_SECONDS", "0.75")),
        },
        "tunnel": {
            "provider": os.getenv("TUNNEL_PROVIDER", "cloudflared"),
            "public_url_file": base_dir / os.getenv("TUNNEL_PUBLIC_URL_FILE", "desktop_app/tunnel_url.txt"),
            "log_file": base_dir / os.getenv("TUNNEL_LOG_FILE", "desktop_app/logs/cloudflared.log"),
        },
        "max_recent_alerts": int(os.getenv("MAX_RECENT_ALERTS", "100")),
        "max_signal_ids": int(os.getenv("MAX_SIGNAL_IDS", "5000")),
        "max_contract_premium": _optional_float(os.getenv("MAX_CONTRACT_PREMIUM", "")),
        "allowed_symbols": _allowed_symbols(os.getenv("ALLOWED_SYMBOLS", "")),
        "paper_account_size": float(os.getenv("PAPER_ACCOUNT_SIZE", "10000")),
        # Paper execution engine — set PAPER_TRADING_ENABLED=false to disable.
        # Uses the same Alpaca keys but hits paper-api.alpaca.markets.
        # Make sure ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets in .env.
        "paper_trading_enabled": os.getenv("PAPER_TRADING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        # ── Options Flow Scanner (Tastytrade) ──────────────────────────────────
        # Scans top-20 symbols for unusual options activity ($1M+ premium).
        # Calls → FLOW_DISCORD_WEBHOOK_BULL, Puts → FLOW_DISCORD_WEBHOOK_BEAR
        # Trigger: GET /flow-scan?secret=<FLOW_SCAN_SECRET>
        "flow": {
            "tastytrade_username":  os.getenv("TASTYTRADE_USERNAME", ""),
            "tastytrade_password":  os.getenv("TASTYTRADE_PASSWORD", ""),
            "tastytrade_remember_token": os.getenv("TASTYTRADE_REMEMBER_TOKEN", ""),
            "tastytrade_otp": os.getenv("TASTYTRADE_OTP", ""),
            "bull_webhook":         os.getenv("FLOW_DISCORD_WEBHOOK_BULL", ""),
            "bear_webhook":         os.getenv("FLOW_DISCORD_WEBHOOK_BEAR", ""),
            "sold_calls_webhook":   os.getenv("FLOW_DISCORD_WEBHOOK_SOLD_CALLS", ""),
            "sold_puts_webhook":    os.getenv("FLOW_DISCORD_WEBHOOK_SOLD_PUTS", ""),
            "min_premium":          float(os.getenv("FLOW_MIN_PREMIUM", "1000000")),
            "min_volume":           int(os.getenv("FLOW_MIN_VOLUME", "3000")),
            "min_dte":              int(os.getenv("FLOW_MIN_DTE", "3")),
            "max_dte":              int(os.getenv("FLOW_MAX_DTE", "60")),
            "max_alerts":           int(os.getenv("FLOW_MAX_ALERTS", "8")),
            "max_alerts_per_symbol": int(os.getenv("FLOW_MAX_ALERTS_PER_SYMBOL", "1")),
            "daily_max_alerts":     int(os.getenv("FLOW_DAILY_MAX_ALERTS", "8")),
            "repeat_window_minutes": int(os.getenv("FLOW_REPEAT_WINDOW_MINUTES", "390")),
            "sold_min_premium":     float(os.getenv("FLOW_SOLD_MIN_PREMIUM", "250000")),
            "sold_min_seller_share": float(os.getenv("FLOW_SOLD_MIN_SELLER_SHARE", "0.60")),
            "sold_candidate_limit": int(os.getenv("FLOW_SOLD_CANDIDATE_LIMIT", "40")),
            "sold_window_seconds":  int(os.getenv("FLOW_SOLD_WINDOW_SECONDS", "8")),
            "sold_max_alerts":      int(os.getenv("FLOW_SOLD_MAX_ALERTS", "2")),
            "sold_max_alerts_per_symbol": int(
                os.getenv("FLOW_SOLD_MAX_ALERTS_PER_SYMBOL", os.getenv("FLOW_MAX_ALERTS_PER_SYMBOL", "1"))
            ),
            "sold_daily_max_alerts": int(os.getenv("FLOW_SOLD_DAILY_MAX_ALERTS", "12")),
            "sold_repeat_window_minutes": int(
                os.getenv("FLOW_SOLD_REPEAT_WINDOW_MINUTES", os.getenv("FLOW_REPEAT_WINDOW_MINUTES", "390"))
            ),
            "sold_symbol_repeat_window_minutes": int(
                os.getenv(
                    "FLOW_SOLD_SYMBOL_REPEAT_WINDOW_MINUTES",
                    os.getenv("FLOW_SYMBOL_REPEAT_WINDOW_MINUTES", "90"),
                )
            ),
            "scan_secret":          os.getenv("FLOW_SCAN_SECRET", ""),
            "enabled":              os.getenv("FLOW_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        },
        "news": {
            "enabled": os.getenv("NEWS_RADAR_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
            "refresh_seconds": int(os.getenv("NEWS_REFRESH_SECONDS", "90")),
            "benzinga_api_key": os.getenv("BENZINGA_NEWS_API_KEY", "").strip(),
            "discord_webhook": os.getenv("NEWS_DISCORD_WEBHOOK", "").strip() or os.getenv("DISCORD_WEBHOOK_URL_NEWS", "").strip(),
            "scan_secret": os.getenv("NEWS_SCAN_SECRET", "").strip(),
        },
        "styles": {
            "LOTTO": {
                "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL_LOTTO", ""),
                "state_file": data_dir / os.getenv("STATE_FILE_LOTTO", "lotto_state.json"),
                "trade_log": data_dir / os.getenv("TRADE_LOG_LOTTO", "lotto_alerts.csv"),
                # FIX: was min(..., 70.0) which capped at 70 making the env var useless above 70.
                # Now a straight float. Pine v4.1 lotto_min_tfs=3 outputs 70% — matches this default.
                "min_confidence": float(os.getenv("LOTTO_MIN_CONFIDENCE", "70")),
                "dte_min": int(os.getenv("DEFAULT_LOTTO_DTE_MIN", "0")),
                "dte_max": int(os.getenv("DEFAULT_LOTTO_DTE_MAX", "7")),
                "risk_pct": float(os.getenv("LOTTO_RISK_PCT", "0.5")),
                "contract_tp1_pct": float(os.getenv("LOTTO_CONTRACT_TP1_PCT", "30")),
                "contract_tp2_pct": float(os.getenv("LOTTO_CONTRACT_TP2_PCT", "50")),
                "contract_stop_pct": float(os.getenv("LOTTO_CONTRACT_STOP_PCT", "30")),
                "cooldown_seconds": int(os.getenv("LOTTO_COOLDOWN_SECONDS", "900")),
                # Delta range for lotto. 0.25-0.40 = OTM with real movement potential.
                "delta_min": float(os.getenv("LOTTO_DELTA_MIN", "0.25")),
                "delta_target": float(os.getenv("LOTTO_DELTA_TARGET", "0.35")),
                "delta_max": float(os.getenv("LOTTO_DELTA_MAX", "0.45")),
                # Percentage-based gap bounds replace the old fixed $2-$5 band.
                # 0.5%-1.5% OTM works correctly across low and high price names.
                "gap_pct_min": float(os.getenv("LOTTO_GAP_PCT_MIN", "0.005")),
                "gap_pct_max": float(os.getenv("LOTTO_GAP_PCT_MAX", "0.015")),
                # Liquidity gates — looser than swing but real protection.
                "min_open_interest": int(os.getenv("LOTTO_MIN_OPEN_INTEREST", "50")),
                "min_option_volume": int(os.getenv("LOTTO_MIN_OPTION_VOLUME", "5")),
                "max_bid_ask_spread_pct": float(os.getenv("LOTTO_MAX_BID_ASK_SPREAD_PCT", "0.30")),
            },
            "SWING": {
                "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL_SWING", ""),
                "state_file": data_dir / os.getenv("STATE_FILE_SWING", "swing_state.json"),
                "trade_log": data_dir / os.getenv("TRADE_LOG_SWING", "swing_alerts.csv"),
                "min_confidence": float(os.getenv("SWING_MIN_CONFIDENCE", "65")),
                "dte_min": int(os.getenv("DEFAULT_SWING_DTE_MIN", "3")),
                "dte_max": int(os.getenv("DEFAULT_SWING_DTE_MAX", "7")),
                "risk_pct": float(os.getenv("SWING_RISK_PCT", "0.75")),
                "cooldown_seconds": int(os.getenv("SWING_COOLDOWN_SECONDS", "3600")),
                "delta_min": float(os.getenv("SWING_DELTA_MIN", "0.40")),
                "delta_target_max": float(os.getenv("SWING_DELTA_TARGET_MAX", "0.55")),
                "delta_absolute_max": float(os.getenv("SWING_DELTA_ABSOLUTE_MAX", "0.65")),
                "strong_setup_confidence": float(os.getenv("SWING_STRONG_SETUP_CONFIDENCE", "80")),
                "min_open_interest": int(os.getenv("SWING_MIN_OPEN_INTEREST", "100")),
                "min_option_volume": int(os.getenv("SWING_MIN_OPTION_VOLUME", "10")),
                "max_bid_ask_spread_pct": float(os.getenv("SWING_MAX_BID_ASK_SPREAD_PCT", "0.15")),
                "hold_days_max": int(os.getenv("SWING_HOLD_DAYS_MAX", "5")),
                "trailing_stop_enabled": os.getenv("SWING_TRAILING_STOP_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
                "trailing_stop_pct": float(os.getenv("SWING_TRAILING_STOP_PCT", "0.25")),
            },
        },
    }


def _load_dotenv():
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        break


def _parse_list(value):
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _optional_float(value):
    try:
        stripped = str(value).strip()
        if not stripped:
            return None
        return float(stripped)
    except (TypeError, ValueError):
        return None


def _allowed_symbols(value):
    symbols = _parse_list(value)
    for symbol in DEFAULT_ALLOWED_SYMBOLS:
        if symbol not in symbols:
            symbols.append(symbol)
    # Keep a few liquid crypto tickers available for after-hours webhook testing.
    for symbol in ("BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"):
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _resolve_data_dir(base_dir, legacy_data_dir):
    configured = str(os.getenv("DATA_DIR", "")).strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else base_dir / path

    render_data_root = Path("/var/data")
    if render_data_root.exists():
        return render_data_root / "gainzalgo_monster"

    return legacy_data_dir
