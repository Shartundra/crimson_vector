from pathlib import Path

import pandas as pd
from loguru import logger


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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
