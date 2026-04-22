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
    data_dir = base_dir / os.getenv("DATA_DIR", "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    return {
        "base_dir": base_dir,
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
        "allowed_symbols": _allowed_symbols(os.getenv("ALLOWED_SYMBOLS", "")),
        "paper_account_size": float(os.getenv("PAPER_ACCOUNT_SIZE", "10000")),
        "styles": {
            "LOTTO": {
                "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL_LOTTO", ""),
                "state_file": data_dir / os.getenv("STATE_FILE_LOTTO", "lotto_state.json"),
                "trade_log": data_dir / os.getenv("TRADE_LOG_LOTTO", "lotto_alerts.csv"),
                "min_confidence": min(float(os.getenv("LOTTO_MIN_CONFIDENCE", "70")), 70.0),
                "dte_min": int(os.getenv("DEFAULT_LOTTO_DTE_MIN", "0")),
                "dte_max": int(os.getenv("DEFAULT_LOTTO_DTE_MAX", "7")),
                "risk_pct": float(os.getenv("LOTTO_RISK_PCT", "0.5")),
                "cooldown_seconds": int(os.getenv("LOTTO_COOLDOWN_SECONDS", "900")),
            },
            "SWING": {
                "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL_SWING", ""),
                "state_file": data_dir / os.getenv("STATE_FILE_SWING", "swing_state.json"),
                "trade_log": data_dir / os.getenv("TRADE_LOG_SWING", "swing_alerts.csv"),
                "min_confidence": float(os.getenv("SWING_MIN_CONFIDENCE", "65")),
                "dte_min": int(os.getenv("DEFAULT_SWING_DTE_MIN", "14")),
                "dte_max": int(os.getenv("DEFAULT_SWING_DTE_MAX", "45")),
                "risk_pct": float(os.getenv("SWING_RISK_PCT", "1.0")),
                "cooldown_seconds": int(os.getenv("SWING_COOLDOWN_SECONDS", "3600")),
            },
        },
    }


def _load_dotenv():
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _parse_list(value):
    return [item.strip().upper() for item in value.split(",") if item.strip()]


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
