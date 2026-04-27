import time
from pathlib import Path

import pandas as pd
import yfinance as yf
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingestion.config import REQUEST_DELAY_SECONDS

_RETRY = retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    retry=retry_if_exception_type((ConnectionError, OSError, ValueError)),
    reraise=True,
)


@_RETRY
def safe_download(
    ticker: str,
    period: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV history for a single ticker with retry and NaN cleanup."""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        logger.warning(f"{ticker}: empty history returned")
        return pd.DataFrame()

    df = df.dropna(how="all")
    if "Close" not in df.columns or df["Close"].isna().all():
        logger.warning(f"{ticker}: no usable Close data")
        return pd.DataFrame()

    df = df[df["Close"].notna()]
    time.sleep(REQUEST_DELAY_SECONDS)
    return df


def validate_dataframe(
    df: pd.DataFrame,
    name: str,
    required_cols: list[str],
) -> bool:
    if df.empty:
        logger.warning(f"{name}: DataFrame is empty")
        return False
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.warning(f"{name}: missing columns {missing}")
        return False
    return True


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
