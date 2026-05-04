import pandas as pd

from pricing._registry import price as _price
from pricing._types import GreeksResult


def price_dataframe(
    df: pd.DataFrame,
    structure: str = "european",
    model: str = "black76",
    **model_kwargs,
) -> pd.DataFrame:
    """
    Price a batch of options described by df.

    Columns required depend on the structure; at minimum: F, K, T, r, sigma.
    European options also need: call_put ("call" or "put").
    Extra columns are silently ignored.

    Returns a copy of df with added columns: price, delta, gamma, theta, vega, rho.
    Extra keyword arguments are forwarded to the model (e.g. barrier level H).
    """
    def _price_row(row: pd.Series) -> pd.Series:
        result: GreeksResult = _price(
            structure=structure,
            model=model,
            **row.to_dict(),
            **model_kwargs,
        )
        return pd.Series(result._asdict())

    greeks = df.apply(_price_row, axis=1)
    return pd.concat([df, greeks], axis=1)
