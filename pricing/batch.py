import pandas as pd

from pricing import black76
from pricing._types import GreeksResult

_MODELS = {
    "black76": black76.price,
    # "sabr": sabr.price,  ← adding a model is one line here
}


def price_dataframe(
    df: pd.DataFrame,
    model: str = "black76",
    **model_kwargs,
) -> pd.DataFrame:
    """
    Price a batch of options described by df.

    Required columns: F, K, T, r, sigma, option_type
    Returns a copy of df with added columns: price, delta, gamma, theta, vega, rho
    Extra keyword arguments are forwarded to the model (e.g. SABR params).
    """
    if model not in _MODELS:
        raise ValueError(
            f"Unknown model {model!r}. Available models: {list(_MODELS)}"
        )

    fn = _MODELS[model]

    def _price_row(row):
        result: GreeksResult = fn(
            F=row["F"],
            K=row["K"],
            T=row["T"],
            r=row["r"],
            sigma=row["sigma"],
            option_type=row["option_type"],
            **model_kwargs,
        )
        return pd.Series(result._asdict())

    greeks = df.apply(_price_row, axis=1)
    return pd.concat([df, greeks], axis=1)
