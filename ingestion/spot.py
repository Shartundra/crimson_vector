import pandas as pd
from loguru import logger

from ingestion.config import DEFAULT_HISTORY_PERIOD, EQUITY_TICKERS, SPOT_PROXIES
from ingestion.utils import safe_download, validate_dataframe


def fetch_spot_price(
    ticker: str,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV history for a single spot/equity ticker."""
    logger.info(f"Fetching spot: {ticker}")
    df = safe_download(ticker, period, interval)
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["ticker"] = ticker
    return df


def fetch_all_spots(
    tickers: list[str] | None = None,
    period: str = DEFAULT_HISTORY_PERIOD,
) -> dict[str, pd.DataFrame]:
    """Fetch spot prices for equity tickers and futures spot proxies."""
    if tickers is None:
        tickers = EQUITY_TICKERS + list(SPOT_PROXIES.values())
        tickers = list(dict.fromkeys(tickers))  # deduplicate, preserve order

    results: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = fetch_spot_price(ticker, period)
        if validate_dataframe(df, ticker, ["Close"]):
            results[ticker] = df
        else:
            logger.warning(f"Skipping {ticker} — no valid spot data")
    return results
