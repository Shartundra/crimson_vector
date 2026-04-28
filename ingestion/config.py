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
