from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Yahoo Finance continuous front-month futures tickers
FUTURES_TICKERS: dict[str, str] = {
    "ES": "ES=F",   # E-mini S&P 500
    "NQ": "NQ=F",   # E-mini Nasdaq-100
    "CL": "CL=F",   # WTI Crude Oil
    "GC": "GC=F",   # Gold
    "SI": "SI=F",   # Silver
    "ZB": "ZB=F",   # 30-year US Treasury Bond
    "6E": "6E=F",   # Euro FX
}

# Equity underlyings for options chain pulls
EQUITY_TICKERS: list[str] = ["SPY", "QQQ", "AAPL", "TSLA", "AMZN", "GLD"]

# Closest liquid spot proxy for each futures contract.
# Yahoo Finance does not expose raw cash prices for most futures underlyings;
# these ETF/index proxies are the best available substitute.
SPOT_PROXIES: dict[str, str] = {
    "ES=F": "^GSPC",   # S&P 500 index
    "NQ=F": "^NDX",    # Nasdaq-100 index
    "CL=F": "USO",     # Crude oil ETF (no WTI cash on Yahoo)
    "GC=F": "GLD",     # Gold ETF
    "SI=F": "SLV",     # Silver ETF
    "ZB=F": "TLT",     # Long-duration treasury ETF
    "6E=F": "FXE",     # Euro FX ETF
}

DEFAULT_HISTORY_PERIOD = "30d"
MAX_EXPIRIES_PER_TICKER = 4

# Courtesy delay between yfinance HTTP calls to avoid 429s
REQUEST_DELAY_SECONDS = 1.5
