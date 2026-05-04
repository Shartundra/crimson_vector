from typing import NamedTuple


class GreeksResult(NamedTuple):
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
