"""
IBKR data fetcher — futures OHLCV + options chain for any supported underlying.

Requires TWS or IB Gateway running with API access enabled:
  Edit → Global Configuration → API → Settings
  ✓ Enable ActiveX and Socket Clients   ✗ Read-Only API (uncheck)

Ports: 7497 TWS paper | 7496 TWS live | 4002 Gateway paper | 4001 Gateway live

Standalone:
    python -m ingestion.ib_options --symbol ZC
"""

import time

import pandas as pd
from ib_insync import IB, BarData, Future, FuturesOption, util
from loguru import logger

from ingestion.config import (
    DATA_RAW_DIR,
    FUTURES_CONTRACTS,
    IB_CLIENT_ID,
    IB_HISTORY_DAYS,
    IB_HOST,
    IB_MAX_EXPIRIES,
    IB_MAX_STRIKES,
    IB_PORT,
)
from ingestion.utils import save_dataframe

util.logToConsole(False)


# ── connection ────────────────────────────────────────────────────────────────

def connect(host: str = IB_HOST, port: int = IB_PORT, client_id: int = IB_CLIENT_ID) -> IB:
    # readonly=True is enforced at the API level — TWS will reject any attempt
    # to place, modify, or cancel orders through this connection.
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10, readonly=True)
    logger.info(f"Connected to IB [READ-ONLY]  host={host}  port={port}  clientId={client_id}")
    return ib


def disconnect(ib: IB) -> None:
    ib.disconnect()
    logger.info("Disconnected from IB")


# ── contract resolution ───────────────────────────────────────────────────────

def get_front_month(ib: IB, symbol: str) -> Future:
    """Qualify and return the front-month futures contract for symbol."""
    meta = FUTURES_CONTRACTS[symbol]
    contract = Future(symbol=symbol, exchange=meta["exchange"], currency=meta["currency"])
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise ValueError(f"Could not qualify front-month contract for {symbol}")
    front = qualified[0]
    logger.info(f"Front-month {symbol}: {front.localSymbol}  conId={front.conId}")
    return front


def get_option_params(ib: IB, underlying: Future) -> pd.DataFrame:
    """
    Discover all valid strikes + expiries via reqSecDefOptParams.
    Returns DataFrame columns: expiry, strike.
    """
    meta = FUTURES_CONTRACTS[underlying.symbol]
    chains = ib.reqSecDefOptParams(
        underlyingSymbol=underlying.symbol,
        futFopExchange="",
        underlyingSecType="FUT",
        underlyingConId=underlying.conId,
    )
    target_exchange = meta["opt_exchange"]
    filtered = [c for c in chains if c.exchange == target_exchange] or list(chains)

    rows = [
        {"expiry": exp, "strike": float(s)}
        for c in filtered
        for exp in c.expirations
        for s in c.strikes
    ]
    df = pd.DataFrame(rows).drop_duplicates().sort_values(["expiry", "strike"])
    logger.info(f"Option params: {df['expiry'].nunique()} expiries, {df['strike'].nunique()} unique strikes")
    return df


def select_strikes_near_atm(
    strikes: list[float],
    atm: float,
    max_strikes: int | None,
) -> list[float]:
    s = sorted(strikes)
    if max_strikes is None:
        return s
    idx = min(range(len(s)), key=lambda i: abs(s[i] - atm))
    half = max_strikes // 2
    lo = max(0, idx - half)
    hi = min(len(s), idx + half + (max_strikes % 2))
    return s[lo:hi]


# ── futures OHLCV ─────────────────────────────────────────────────────────────

def fetch_futures_history(
    ib: IB,
    underlying: Future,
    history_days: int = IB_HISTORY_DAYS,
) -> pd.DataFrame:
    """Fetch daily OHLCV for a futures contract via reqHistoricalData."""
    logger.info(f"Fetching {history_days}d OHLCV for {underlying.localSymbol}…")
    bars: list[BarData] = ib.reqHistoricalData(
        underlying,
        endDateTime="",
        durationStr=f"{history_days} D",
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    if not bars:
        logger.warning("No historical bars returned")
        return pd.DataFrame()

    df = pd.DataFrame([{
        "Date":   b.date,
        "Open":   b.open,
        "High":   b.high,
        "Low":    b.low,
        "Close":  b.close,
        "Volume": b.volume,
    } for b in bars])
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df = df.set_index("Date").sort_index()
    df["ticker"] = underlying.localSymbol
    df["symbol"] = underlying.symbol
    logger.info(f"  {len(df)} daily bars")
    return df


# ── options chain ─────────────────────────────────────────────────────────────

def _ticker_to_row(ticker, expiry: str, option_type: str) -> dict:
    c = ticker.contract
    g = ticker.modelGreeks
    return {
        "contract_symbol":    c.localSymbol,
        "expiry":             expiry,
        "strike":             c.strike,
        "option_type":        option_type,
        "last_price":         ticker.last  if ticker.last  and ticker.last  > 0 else float("nan"),
        "bid":                ticker.bid   if ticker.bid   and ticker.bid   > 0 else float("nan"),
        "ask":                ticker.ask   if ticker.ask   and ticker.ask   > 0 else float("nan"),
        "volume":             int(ticker.volume) if ticker.volume and ticker.volume >= 0 else pd.NA,
        "open_interest":      int(ticker.callOpenInterest if option_type == "call"
                                  else ticker.putOpenInterest)
                              if (ticker.callOpenInterest or ticker.putOpenInterest) else pd.NA,
        "implied_volatility": ticker.impliedVolatility if ticker.impliedVolatility else float("nan"),
        "delta":              g.delta if g else float("nan"),
        "gamma":              g.gamma if g else float("nan"),
        "theta":              g.theta if g else float("nan"),
        "vega":               g.vega  if g else float("nan"),
        "currency":           c.currency,
        "exchange":           c.exchange,
    }


def fetch_options_chain(
    ib: IB,
    underlying: Future,
    atm_price: float,
    expiries: list[str],
    max_strikes: int | None = IB_MAX_STRIKES,
) -> pd.DataFrame:
    """
    Fetch options market data for the given expiries.
    expiries: list of YYYYMMDD strings to fetch (caller controls selection).
    """
    meta = FUTURES_CONTRACTS[underlying.symbol]
    rows: list[dict] = []

    for expiry in expiries:
        # Fetch option params for this expiry's strikes
        params = get_option_params(ib, underlying)
        expiry_strikes = params[params["expiry"] == expiry]["strike"].tolist()
        if not expiry_strikes:
            logger.warning(f"  {expiry}: no strikes found")
            continue

        strikes = select_strikes_near_atm(expiry_strikes, atm_price, max_strikes)
        logger.info(f"  {expiry}: {len(strikes)} strikes (ATM≈{atm_price:.4f})")

        contracts = [
            FuturesOption(
                symbol=underlying.symbol,
                lastTradeDateOrContractMonth=expiry,
                strike=strike,
                right=right,
                exchange=meta["opt_exchange"],
                currency=meta["currency"],
                multiplier=meta["multiplier"],
            )
            for strike in strikes
            for right in ("C", "P")
        ]

        qualified = ib.qualifyContracts(*contracts)
        if not qualified:
            logger.warning(f"  {expiry}: no contracts qualified")
            continue
        logger.info(f"  {expiry}: {len(qualified)} qualified")

        for i in range(0, len(qualified), 50):
            for ticker in ib.reqTickers(*qualified[i:i + 50]):
                right = ticker.contract.right
                rows.append(_ticker_to_row(ticker, expiry, "call" if right == "C" else "put"))
            time.sleep(0.5)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ("volume", "open_interest"):
        df[col] = pd.array(df[col], dtype="Int64")
    df["iv_suspect"] = df["implied_volatility"].isna() | (df["implied_volatility"] == 0.0)
    df["symbol"] = underlying.symbol
    return df.sort_values(["expiry", "option_type", "strike"]).reset_index(drop=True)


# ── discovery (lightweight — no market data) ──────────────────────────────────

def discover_expiries(
    symbol: str,
    host: str = IB_HOST,
    port: int = IB_PORT,
    client_id: int = IB_CLIENT_ID,
) -> list[str]:
    """
    Quick TWS round-trip to get available option expiries for a symbol.
    Does NOT fetch any market data — safe and fast.
    Returns sorted list of YYYYMMDD expiry strings.
    """
    ib = connect(host, port, client_id)
    try:
        underlying = get_front_month(ib, symbol)
        params = get_option_params(ib, underlying)
        return sorted(params["expiry"].unique().tolist())
    finally:
        disconnect(ib)


# ── main fetch ────────────────────────────────────────────────────────────────

def fetch_all_data(
    symbol: str,
    expiries: list[str],
    host: str = IB_HOST,
    port: int = IB_PORT,
    client_id: int = IB_CLIENT_ID,
    max_strikes: int | None = IB_MAX_STRIKES,
    history_days: int = IB_HISTORY_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    Single TWS connection → fetch futures OHLCV + options for chosen expiries.
    Saves futures_{symbol}_ib.parquet and options_{symbol}_ib.parquet.
    Returns {"futures": df, "options": df}.
    """
    if symbol not in FUTURES_CONTRACTS:
        raise ValueError(f"Unknown symbol '{symbol}'. Add it to FUTURES_CONTRACTS in config.py.")

    ib = connect(host, port, client_id)
    results: dict[str, pd.DataFrame] = {}
    try:
        underlying = get_front_month(ib, symbol)
        [und_ticker] = ib.reqTickers(underlying)
        atm = und_ticker.last or und_ticker.close or 0.0
        logger.info(f"{symbol} ATM price: {atm}")

        hist = fetch_futures_history(ib, underlying, history_days)
        if not hist.empty:
            save_dataframe(hist, f"futures_{symbol}_ib", DATA_RAW_DIR)
            results["futures"] = hist

        opts = fetch_options_chain(ib, underlying, atm, expiries, max_strikes)
        if not opts.empty:
            save_dataframe(opts, f"options_{symbol}_ib", DATA_RAW_DIR)
            results["options"] = opts

    finally:
        disconnect(ib)

    logger.info(f"Done. Fetched: {list(results.keys())}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ZC", choices=list(FUTURES_CONTRACTS))
    parser.add_argument("--expiries", nargs="+", help="YYYYMMDD expiry strings")
    parser.add_argument("--max-expiries", type=int, default=IB_MAX_EXPIRIES)
    args = parser.parse_args()

    if not args.expiries:
        all_exp = discover_expiries(args.symbol)
        args.expiries = all_exp[:args.max_expiries]
        print(f"Using expiries: {args.expiries}")

    data = fetch_all_data(args.symbol, args.expiries)
    if "options" in data:
        df = data["options"]
        print(df[["expiry","option_type","strike","bid","ask","implied_volatility","delta","open_interest"]].head(30).to_string())
