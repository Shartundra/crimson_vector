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

# ── Interactive Brokers connection ────────────────────────────────────────────
# TWS live: 7496 | TWS paper: 7497 | IB Gateway live: 4001 | IB Gateway paper: 4002
IB_HOST = "127.0.0.1"
IB_PORT = 7497          # change to 7496 for live account
IB_CLIENT_ID = 10       # any unused client id

# How many expiries to fetch from IB (nearest N)
IB_MAX_EXPIRIES = 4

# Max strikes to fetch per expiry (centred around ATM). None = all strikes.
IB_MAX_STRIKES = 30
