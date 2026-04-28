"""
IBKR data fetcher for CBOT corn (ZC) — futures OHLCV + options chain.

Requires TWS or IB Gateway running with API access enabled:
  Edit → Global Configuration → API → Settings
  ✓ Enable ActiveX and Socket Clients
  ✗ Read-Only API (uncheck)

Ports: 7497 TWS paper | 7496 TWS live | 4002 Gateway paper | 4001 Gateway live

Standalone:
    python -m ingestion.ib_options
"""

import time

import pandas as pd
from ib_insync import IB, BarData, Future, FuturesOption, util
from loguru import logger

from ingestion.config import (
    DATA_RAW_DIR,
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
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10)
    logger.info(f"Connected to IB  host={host}  port={port}  clientId={client_id}")
    return ib


def disconnect(ib: IB) -> None:
    ib.disconnect()
    logger.info("Disconnected from IB")


# ── corn futures contract ─────────────────────────────────────────────────────

def get_front_month_corn(ib: IB) -> Future:
    """Qualify and return the front-month ZC futures contract."""
    contract = Future(symbol="ZC", exchange="CBOT", currency="USD")
    [qualified] = ib.qualifyContracts(contract)
    logger.info(f"Front-month corn: {qualified.localSymbol}  conId={qualified.conId}")
    return qualified


# ── futures OHLCV history ─────────────────────────────────────────────────────

def fetch_corn_futures_history(
    ib: IB,
    underlying: Future,
    history_days: int = IB_HISTORY_DAYS,
) -> pd.DataFrame:
    """Fetch daily OHLCV history for the corn futures contract via reqHistoricalData."""
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
    df["contract_name"] = "ZC"
    logger.info(f"  {len(df)} daily bars retrieved")
    return df


# ── options chain ─────────────────────────────────────────────────────────────

def get_corn_option_params(ib: IB, underlying: Future) -> pd.DataFrame:
    """
    Discover valid strikes + expiries via reqSecDefOptParams.
    Returns DataFrame with columns: expiry, strike.
    """
    chains = ib.reqSecDefOptParams(
        underlyingSymbol=underlying.symbol,
        futFopExchange="",
        underlyingSecType="FUT",
        underlyingConId=underlying.conId,
    )
    cbot = [c for c in chains if c.exchange == "CBOT"] or list(chains)

    rows = [
        {"expiry": exp, "strike": float(s)}
        for c in cbot
        for exp in c.expirations
        for s in c.strikes
    ]
    df = pd.DataFrame(rows).drop_duplicates().sort_values(["expiry", "strike"])
    logger.info(f"Option params: {df['expiry'].nunique()} expiries, {df['strike'].nunique()} unique strikes")
    return df


def select_strikes_near_atm(
    strikes: list[float],
    atm: float,
    max_strikes: int | None = IB_MAX_STRIKES,
) -> list[float]:
    """Return up to max_strikes strikes centred on atm, sorted ascending."""
    s = sorted(strikes)
    if max_strikes is None:
        return s
    idx = min(range(len(s)), key=lambda i: abs(s[i] - atm))
    half = max_strikes // 2
    lo = max(0, idx - half)
    hi = min(len(s), idx + half + (max_strikes % 2))
    return s[lo:hi]


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


def fetch_corn_options_chain(
    ib: IB,
    underlying: Future,
    atm_price: float,
    max_expiries: int = IB_MAX_EXPIRIES,
    max_strikes: int | None = IB_MAX_STRIKES,
) -> pd.DataFrame:
    """Fetch options chain for corn futures. Requires an open IB connection."""
    params = get_corn_option_params(ib, underlying)
    if params.empty:
        logger.error("No option params — check TWS market data subscriptions")
        return pd.DataFrame()

    expiries = sorted(params["expiry"].unique())[:max_expiries]
    logger.info(f"Fetching options for {len(expiries)} expiries: {expiries}")

    rows: list[dict] = []
    for expiry in expiries:
        strikes = select_strikes_near_atm(
            params[params["expiry"] == expiry]["strike"].tolist(),
            atm_price, max_strikes,
        )
        logger.info(f"  {expiry}: {len(strikes)} strikes (ATM≈{atm_price:.2f})")

        contracts = [
            FuturesOption(
                symbol="ZC",
                lastTradeDateOrContractMonth=expiry,
                strike=strike,
                right=right,
                exchange="CBOT",
                currency="USD",
                multiplier="50",
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
            batch = qualified[i:i + 50]
            for ticker in ib.reqTickers(*batch):
                right = ticker.contract.right
                rows.append(_ticker_to_row(ticker, expiry, "call" if right == "C" else "put"))
            time.sleep(0.5)

    if not rows:
        logger.error("No option rows collected")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ("volume", "open_interest"):
        df[col] = pd.array(df[col], dtype="Int64")
    df["iv_suspect"] = df["implied_volatility"].isna() | (df["implied_volatility"] == 0.0)
    df["ticker"] = "ZC"
    return df.sort_values(["expiry", "option_type", "strike"]).reset_index(drop=True)


# ── main entry point ──────────────────────────────────────────────────────────

def fetch_all_corn_data(
    host: str = IB_HOST,
    port: int = IB_PORT,
    client_id: int = IB_CLIENT_ID,
    max_expiries: int = IB_MAX_EXPIRIES,
    max_strikes: int | None = IB_MAX_STRIKES,
    history_days: int = IB_HISTORY_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    Single TWS connection → fetch ZC futures OHLCV + options chain.
    Saves both to data/raw/ and returns {"futures": df, "options": df}.
    """
    ib = connect(host, port, client_id)
    results: dict[str, pd.DataFrame] = {}
    try:
        underlying = get_front_month_corn(ib)

        # Current price (used as ATM reference for strike selection)
        [und_ticker] = ib.reqTickers(underlying)
        atm = und_ticker.last or und_ticker.close or 460.0
        logger.info(f"ZC ATM price: {atm}")

        # 1. Futures OHLCV
        hist = fetch_corn_futures_history(ib, underlying, history_days)
        if not hist.empty:
            save_dataframe(hist, "futures_ZC_ib", DATA_RAW_DIR)
            results["futures"] = hist

        # 2. Options chain
        opts = fetch_corn_options_chain(ib, underlying, atm, max_expiries, max_strikes)
        if not opts.empty:
            save_dataframe(opts, "options_ZC_corn_ib", DATA_RAW_DIR)
            results["options"] = opts

    finally:
        disconnect(ib)

    logger.info(f"Done. Fetched: {list(results.keys())}")
    return results


if __name__ == "__main__":
    data = fetch_all_corn_data()
    if "options" in data:
        df = data["options"]
        print(df[["expiry","option_type","strike","bid","ask","implied_volatility","delta","open_interest"]].head(30).to_string())
