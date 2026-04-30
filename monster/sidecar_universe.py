SIDE_CAR_THEMES = {
    "Index Tape": ["SPY", "QQQ", "IWM", "DIA", "SMH", "XLF"],
    "Mega Tech": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"],
    "Semis": ["AMD", "AVGO", "QCOM", "MU", "SMCI", "ARM"],
    "Finance": ["JPM", "BAC", "GS", "MS", "V", "MA"],
    "Health": ["LLY", "UNH", "ABBV", "JNJ", "MRK", "ABT"],
    "Consumer": ["WMT", "COST", "HD", "MCD", "SBUX", "NKE"],
    "Energy + Indus": ["XOM", "CVX", "CAT", "GE", "RTX", "BA"],
    "High Beta": ["TSLA", "NFLX", "PLTR", "COIN", "HOOD", "UBER"],
}

SIDE_CAR_EXTRAS = [
    "ORCL",
    "CRM",
    "ADBE",
    "CSCO",
    "INTC",
    "NOW",
    "PANW",
    "SHOP",
    "DIS",
    "PYPL",
    "SOFI",
    "TMO",
    "PFE",
    "MCD",
    "LMT",
    "SLB",
    "FCX",
    "NEM",
]


def _unique(symbols):
    ordered = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    return ordered


SIDE_CAR_BASE_UNIVERSE = _unique(
    [symbol for symbols in SIDE_CAR_THEMES.values() for symbol in symbols] + SIDE_CAR_EXTRAS
)


def get_sidecar_symbols(config=None, limit=72):
    config = config or {}
    merged = _unique(SIDE_CAR_BASE_UNIVERSE + list(config.get("allowed_symbols") or []))
    return merged[:limit]


def get_sidecar_themes():
    return list(SIDE_CAR_THEMES.items())
