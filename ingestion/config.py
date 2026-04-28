from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# ── Interactive Brokers connection ────────────────────────────────────────────
# TWS live: 7496 | TWS paper: 7497 | IB Gateway live: 4001 | IB Gateway paper: 4002
IB_HOST = "127.0.0.1"
IB_PORT = 7497          # change to 7496 for live account
IB_CLIENT_ID = 10       # any unused client id

# Options fetch settings
IB_MAX_EXPIRIES = 4     # nearest N expiries to pull
IB_MAX_STRIKES = 30     # strikes centred around ATM per expiry (None = all)

# Futures history
IB_HISTORY_DAYS = 30    # calendar days of daily OHLCV to fetch

# ── Supported futures underlyings ─────────────────────────────────────────────
# symbol → {name, exchange, opt_exchange, currency, multiplier}
# opt_exchange: exchange used when building FuturesOption contracts
FUTURES_CONTRACTS: dict[str, dict] = {
    "ZC": {"name": "Corn",            "exchange": "CBOT",  "opt_exchange": "CBOT",  "currency": "USD", "multiplier": "50"},
    "ZS": {"name": "Soybeans",        "exchange": "CBOT",  "opt_exchange": "CBOT",  "currency": "USD", "multiplier": "50"},
    "ZW": {"name": "Wheat",           "exchange": "CBOT",  "opt_exchange": "CBOT",  "currency": "USD", "multiplier": "50"},
    "ES": {"name": "E-mini S&P 500",  "exchange": "CME",   "opt_exchange": "CME",   "currency": "USD", "multiplier": "50"},
    "NQ": {"name": "E-mini Nasdaq",   "exchange": "CME",   "opt_exchange": "CME",   "currency": "USD", "multiplier": "20"},
    "CL": {"name": "Crude Oil (WTI)", "exchange": "NYMEX", "opt_exchange": "NYMEX", "currency": "USD", "multiplier": "1000"},
    "GC": {"name": "Gold",            "exchange": "COMEX", "opt_exchange": "COMEX", "currency": "USD", "multiplier": "100"},
    "SI": {"name": "Silver",          "exchange": "COMEX", "opt_exchange": "COMEX", "currency": "USD", "multiplier": "5000"},
    "ZB": {"name": "30yr T-Bond",     "exchange": "CBOT",  "opt_exchange": "CBOT",  "currency": "USD", "multiplier": "1000"},
    "6E": {"name": "Euro FX",         "exchange": "CME",   "opt_exchange": "CME",   "currency": "USD", "multiplier": "125000"},
}
