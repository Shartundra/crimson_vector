import math

from pricing._types import GreeksResult

_SQRT_2PI = math.sqrt(2 * math.pi)


def _ncdf(x: float) -> float:
    """Standard normal CDF via math.erfc — no scipy required."""
    return math.erfc(-x / math.sqrt(2)) / 2


def _npdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def price(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> GreeksResult:
    """
    Black-76 price and Greeks for a European option on a futures contract.

    Parameters
    ----------
    F : futures price
    K : strike price
    T : time to expiry in years
    r : risk-free rate (continuously compounded)
    sigma : implied volatility
    option_type : "call" or "put"

    Returns
    -------
    GreeksResult(price, delta, gamma, theta, vega, rho)
    Theta is annualised; divide by 365 for daily decay.
    """
    opt = option_type.lower()
    if opt not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    if F <= 0 or K <= 0:
        return GreeksResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    # Degenerate cases — return intrinsic value with binary delta
    if T <= 0 or sigma <= 0:
        if opt == "call":
            intrinsic = max(F - K, 0.0)
            delta = 1.0 if F > K else 0.0
        else:
            intrinsic = max(K - F, 0.0)
            delta = -1.0 if K > F else 0.0
        return GreeksResult(price=intrinsic, delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    D = math.exp(-r * T)

    n_d1 = _ncdf(d1)
    n_d2 = _ncdf(d2)
    n_neg_d1 = 1.0 - n_d1
    n_neg_d2 = 1.0 - n_d2
    pdf_d1 = _npdf(d1)

    if opt == "call":
        p = D * (F * n_d1 - K * n_d2)
        delta = D * n_d1
        theta = -F * D * pdf_d1 * sigma / (2 * sqrt_T) + r * D * (F * n_d1 - K * n_d2)
    else:
        p = D * (K * n_neg_d2 - F * n_neg_d1)
        delta = D * (n_d1 - 1.0)
        theta = -F * D * pdf_d1 * sigma / (2 * sqrt_T) + r * D * (K * n_neg_d2 - F * n_neg_d1)

    gamma = D * pdf_d1 / (F * sigma * sqrt_T)
    vega = F * D * pdf_d1 * sqrt_T
    rho = -T * p

    return GreeksResult(price=p, delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)
