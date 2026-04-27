import pandas as pd
from loguru import logger

from ingestion.config import DEFAULT_HISTORY_PERIOD, FUTURES_TICKERS
from ingestion.utils import safe_download, validate_dataframe


def fetch_futures_history(
    ticker: str,
    contract_name: str,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV history for a single futures ticker (e.g. 'ES=F').

    Yahoo Finance returns front-month continuous contracts. Price jumps at roll
    dates are expected and not adjusted for.
    """
    logger.info(f"Fetching futures: {ticker} ({contract_name})")
    df = safe_download(ticker, period, interval)
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["ticker"] = ticker
    df["contract_name"] = contract_name
    return df


def fetch_all_futures(
    tickers: dict[str, str] = FUTURES_TICKERS,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch all futures in FUTURES_TICKERS and return a single long-format DataFrame."""
    frames: list[pd.DataFrame] = []
    for contract_name, yahoo_ticker in tickers.items():
        df = fetch_futures_history(yahoo_ticker, contract_name, period, interval)
        if validate_dataframe(df, yahoo_ticker, ["Close"]):
            frames.append(df)
        else:
            logger.warning(f"Skipping {yahoo_ticker} — no valid futures data")

    if not frames:
        logger.error("No futures data retrieved")
        return pd.DataFrame()

    combined = pd.concat(frames)
    combined.index.name = "Date"
    combined = combined.sort_values(["ticker", "Date"])
    return combined
