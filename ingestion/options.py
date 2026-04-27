import time

import pandas as pd
import yfinance as yf
from loguru import logger

from ingestion.config import (
    EQUITY_TICKERS,
    MAX_EXPIRIES_PER_TICKER,
    REQUEST_DELAY_SECONDS,
)

_COL_RENAME = {
    "contractSymbol": "contract_symbol",
    "lastTradeDate": "last_trade_date",
    "strike": "strike",
    "lastPrice": "last_price",
    "bid": "bid",
    "ask": "ask",
    "change": "change",
    "percentChange": "pct_change",
    "volume": "volume",
    "openInterest": "open_interest",
    "impliedVolatility": "implied_volatility",
    "inTheMoney": "in_the_money",
    "contractSize": "contract_size",
    "currency": "currency",
}


def fetch_expiry_dates(ticker: str) -> tuple[str, ...]:
    """Return available option expiry date strings for ticker."""
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            logger.warning(f"{ticker}: no option expiries available")
        return expiries
    except Exception as exc:
        logger.warning(f"{ticker}: failed to fetch expiries — {exc}")
        return ()


def _normalise_chain(df: pd.DataFrame, ticker: str, expiry: str, opt_type: str) -> pd.DataFrame:
    df = df.rename(columns=_COL_RENAME)
    df["ticker"] = ticker
    df["expiry"] = expiry
    df["option_type"] = opt_type

    # Volume and open interest are often NaN (no trades); use nullable Int64
    for col in ("volume", "open_interest"):
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    # Flag zero IV — these are real rows but their IV is unreliable
    if "implied_volatility" in df.columns:
        df["iv_suspect"] = df["implied_volatility"] == 0.0

    # Normalise last_trade_date to UTC if present
    if "last_trade_date" in df.columns:
        df["last_trade_date"] = pd.to_datetime(df["last_trade_date"], utc=True, errors="coerce")

    return df


def fetch_option_chain_for_expiry(
    ticker: str,
    expiry: str,
    option_type: str = "both",
) -> pd.DataFrame:
    """Fetch one expiry's option chain for a ticker.

    option_type: 'calls', 'puts', or 'both'
    Returns empty DataFrame on failure.
    """
    try:
        t = yf.Ticker(ticker)
        chain = t.option_chain(expiry)
    except Exception as exc:
        logger.warning(f"{ticker} {expiry}: option_chain() failed — {exc}")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    if option_type in ("calls", "both") and not chain.calls.empty:
        frames.append(_normalise_chain(chain.calls.copy(), ticker, expiry, "call"))
    if option_type in ("puts", "both") and not chain.puts.empty:
        frames.append(_normalise_chain(chain.puts.copy(), ticker, expiry, "put"))

    if not frames:
        logger.warning(f"{ticker} {expiry}: empty chain")
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def fetch_all_options(
    ticker: str,
    max_expiries: int = MAX_EXPIRIES_PER_TICKER,
) -> pd.DataFrame:
    """Fetch up to max_expiries nearest expiries for ticker, calls + puts combined."""
    expiries = fetch_expiry_dates(ticker)
    if not expiries:
        return pd.DataFrame()

    selected = expiries[:max_expiries]
    frames: list[pd.DataFrame] = []

    for expiry in selected:
        logger.info(f"Fetching options: {ticker} expiry={expiry}")
        df = fetch_option_chain_for_expiry(ticker, expiry)
        if not df.empty:
            frames.append(df)
        time.sleep(REQUEST_DELAY_SECONDS)

    if not frames:
        logger.error(f"{ticker}: no option chain data retrieved")
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def fetch_options_for_all_tickers(
    tickers: list[str] = EQUITY_TICKERS,
    max_expiries: int = MAX_EXPIRIES_PER_TICKER,
) -> dict[str, pd.DataFrame]:
    """Fetch options chains for all tickers. Returns dict mapping ticker → DataFrame."""
    results: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = fetch_all_options(ticker, max_expiries)
        if not df.empty:
            results[ticker] = df
        else:
            logger.warning(f"Skipping {ticker} — no options data")
    return results
