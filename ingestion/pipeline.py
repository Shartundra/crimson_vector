"""
Crimson Vector — data ingestion pipeline.

Run from the project root:
    python -m ingestion.pipeline
"""

from pathlib import Path

import pandas as pd
from loguru import logger

from ingestion.config import (
    DATA_RAW_DIR,
    DEFAULT_HISTORY_PERIOD,
    EQUITY_TICKERS,
    FUTURES_TICKERS,
    MAX_EXPIRIES_PER_TICKER,
    SPOT_PROXIES,
)
from ingestion.futures import fetch_all_futures
from ingestion.options import fetch_options_for_all_tickers
from ingestion.spot import fetch_all_spots
from ingestion.utils import ensure_output_dir


def save_dataframe(
    df: pd.DataFrame,
    name: str,
    output_dir: Path,
    fmt: str = "parquet",
) -> Path:
    ensure_output_dir(output_dir)
    if fmt == "parquet":
        path = output_dir / f"{name}.parquet"
        df.to_parquet(path, index=True)
    else:
        path = output_dir / f"{name}.csv"
        df.to_csv(path, index=True)
    logger.info(f"Saved {name} → {path} ({len(df)} rows)")
    return path


def run_ingestion(
    futures_tickers: dict[str, str] = FUTURES_TICKERS,
    equity_tickers: list[str] = EQUITY_TICKERS,
    spot_proxies: dict[str, str] = SPOT_PROXIES,
    history_period: str = DEFAULT_HISTORY_PERIOD,
    max_expiries: int = MAX_EXPIRIES_PER_TICKER,
    output_format: str = "parquet",
    output_dir: Path = DATA_RAW_DIR,
) -> dict[str, pd.DataFrame]:
    results: dict[str, pd.DataFrame] = {}

    # 1. Futures OHLCV
    logger.info("=== Fetching futures OHLCV ===")
    futures_df = fetch_all_futures(futures_tickers, history_period)
    if not futures_df.empty:
        save_dataframe(futures_df, "futures_ohlcv", output_dir, output_format)
        results["futures_ohlcv"] = futures_df

    # 2. Spot prices (equity tickers + futures proxies, deduplicated)
    logger.info("=== Fetching spot prices ===")
    spot_tickers = equity_tickers + list(spot_proxies.values())
    spot_tickers = list(dict.fromkeys(spot_tickers))
    spot_data = fetch_all_spots(spot_tickers, history_period)
    if spot_data:
        combined_spot = pd.concat(spot_data.values())
        save_dataframe(combined_spot, "spot_prices", output_dir, output_format)
        results["spot_prices"] = combined_spot

    # 3. Options chains
    logger.info("=== Fetching options chains ===")
    options_data = fetch_options_for_all_tickers(equity_tickers, max_expiries)
    for ticker, df in options_data.items():
        safe_name = f"options_{ticker}"
        save_dataframe(df, safe_name, output_dir, output_format)
        results[safe_name] = df

    logger.info(f"Ingestion complete. {len(results)} datasets saved to {output_dir}")
    return results


if __name__ == "__main__":
    run_ingestion()
