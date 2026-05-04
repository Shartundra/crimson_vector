"""
Reiner-Rubinstein (1991) closed-form pricing for European barrier options on futures.

All 8 barrier types (up/down × in/out × call/put) are supported.
Underlying dynamics follow Black-76 (cost of carry b=0, futures).
Greeks are computed by finite differences — analytic barrier Greeks are
discontinuous near the barrier and impractical to maintain.

Rebate convention: paid at expiry (not at moment of breach).
"""
from __future__ import annotations

import math

from pricing._types import GreeksResult

_SQRT_2PI = math.sqrt(2 * math.pi)


def _ncdf(x: float) -> float:
    return math.erfc(-x / math.sqrt(2)) / 2


def _black76_scalar(F: float, K: float, T: float, r: float, sigma: float, call_put: str) -> float:
    """Vanilla Black-76 price as a plain float (used for already-breached knock-ins)."""
    phi = 1.0 if call_put == "call" else -1.0
    if F <= 0 or K <= 0:
        return 0.0
    if T <= 0 or sigma <= 0:
        return max(phi * (F - K), 0.0)
    D = math.exp(-r * T)
    sqT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqT)
    d2 = d1 - sigma * sqT
    return phi * D * (F * _ncdf(phi * d1) - K * _ncdf(phi * d2))


def _barrier_price_raw(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    H: float,
    call_put: str,
    barrier_dir: str,
    knock: str,
    rebate: float,
) -> float:
    """
    Scalar barrier option price (no Greeks). Called by price() and by its FD bumps.
    All inputs assumed validated by the caller.
    """
    cp  = call_put.lower()
    bd  = barrier_dir.lower()
    kn  = knock.lower()
    phi = 1.0 if cp == "call" else -1.0
    eta = 1.0 if bd == "down" else -1.0

    D = math.exp(-r * T)

    # --- degenerate: barrier already breached at initiation ---
    if bd == "down" and F <= H:
        return rebate * D if kn == "out" else _black76_scalar(F, K, T, r, sigma, cp)
    if bd == "up" and F >= H:
        return rebate * D if kn == "out" else _black76_scalar(F, K, T, r, sigma, cp)

    # --- degenerate: expired or zero vol ---
    if T <= 0 or sigma <= 0:
        if kn == "out":
            return max(phi * (F - K), 0.0)  # barrier not relevant at expiry
        else:
            return max(phi * (F - K), 0.0)  # if alive, intrinsic

    sqT     = math.sqrt(T)
    sig_sqT = sigma * sqT
    # mu = -0.5 always for futures (b=0): (b - sigma²/2)/sigma² = -1/2
    mu = -0.5

    # rebate lambda (for E_term)
    lam = math.sqrt(mu * mu + 2.0 * r / (sigma * sigma))

    # --- distances (log-form for numerical stability) ---
    ln_FK = math.log(F / K)
    ln_HF = math.log(H / F)   # negative for down-barriers (H<F)

    x1 = ln_FK  / sig_sqT + (1.0 + mu) * sig_sqT
    x2 = -ln_HF / sig_sqT + (1.0 + mu) * sig_sqT   # ln(F/H) = -ln(H/F)
    # y1 = ln(H²/(F·K)) = 2·ln(H/F) + ln(F/K) = 2*ln_HF + ln_FK (stable)
    y1 = (2.0 * ln_HF + ln_FK) / sig_sqT + (1.0 + mu) * sig_sqT
    y2 = ln_HF / sig_sqT + (1.0 + mu) * sig_sqT
    z  = ln_HF / sig_sqT + lam * sig_sqT

    # mu=-0.5 → hf^(2*(mu+1)) = (H/F)^1 = H/F
    #          hf^(2*mu)       = (H/F)^(-1) = F/H
    HoF = H / F
    FoH = F / H

    # --- building blocks ---
    A = phi * D * (F * _ncdf(phi * x1)            - K * _ncdf(phi * (x1 - sig_sqT)))
    B = phi * D * (F * _ncdf(phi * x2)            - K * _ncdf(phi * (x2 - sig_sqT)))
    C = phi * D * (F * HoF * _ncdf(eta * y1)      - K * FoH * _ncdf(eta * (y1 - sig_sqT)))
    Dt = phi * D * (F * HoF * _ncdf(eta * y2)     - K * FoH * _ncdf(eta * (y2 - sig_sqT)))
    E = rebate * D * (_ncdf(eta * (x2 - sig_sqT)) - FoH * _ncdf(eta * (y2 - sig_sqT)))

    # --- 8-case dispatch ---
    if bd == "down" and kn == "out" and cp == "call":
        return A - C + E    if K >= H else B - Dt + E
    if bd == "down" and kn == "in"  and cp == "call":
        return C - E        if K >= H else A - B + Dt - E
    if bd == "down" and kn == "out" and cp == "put":
        return A - B + Dt - C + E if K >= H else E
    if bd == "down" and kn == "in"  and cp == "put":
        return B - Dt + C - E     if K >= H else A - E
    if bd == "up"   and kn == "out" and cp == "call":
        return E                  if K >= H else A - B + Dt - C + E
    if bd == "up"   and kn == "in"  and cp == "call":
        return A - E              if K >= H else B - Dt + C - E
    if bd == "up"   and kn == "out" and cp == "put":
        return A - C + E    if K >= H else B - Dt + E
    if bd == "up"   and kn == "in"  and cp == "put":
        return C - E        if K >= H else A - B + Dt - E

    raise ValueError(f"Unrecognised combination: {barrier_dir!r} {knock!r} {call_put!r}")


def price(
    F: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    H: float,
    call_put: str,
    barrier_dir: str,
    knock: str,
    rebate: float = 0.0,
) -> GreeksResult:
    """
    Reiner-Rubinstein (1991) barrier option price and Greeks for a futures underlying.

    Parameters
    ----------
    F           : futures price
    K           : strike
    T           : time to expiry in years
    r           : risk-free rate (continuously compounded)
    sigma       : implied volatility
    H           : barrier level
    call_put    : "call" or "put"
    barrier_dir : "up" (H > F) or "down" (H < F)
    knock       : "out" (ceases if barrier hit) or "in" (activates if barrier hit)
    rebate      : cash paid at expiry if knock-out was triggered (default 0)

    Returns
    -------
    GreeksResult(price, delta, gamma, theta, vega, rho)
    Theta is annualised; divide by 365 for daily decay.
    Greeks are finite-difference estimates (central differences except theta).
    """
    cp = call_put.lower()
    bd = barrier_dir.lower()
    kn = knock.lower()

    if cp not in ("call", "put"):
        raise ValueError(f"call_put must be 'call' or 'put', got {call_put!r}")
    if bd not in ("up", "down"):
        raise ValueError(f"barrier_dir must be 'up' or 'down', got {barrier_dir!r}")
    if kn not in ("in", "out"):
        raise ValueError(f"knock must be 'in' or 'out', got {knock!r}")
    if F <= 0 or K <= 0 or H <= 0:
        return GreeksResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    if rebate < 0:
        raise ValueError(f"rebate must be non-negative, got {rebate}")

    def raw(F_=F, T_=T, r_=r, sigma_=sigma):
        return _barrier_price_raw(F_, K, T_, r_, sigma_, H, cp, bd, kn, rebate)

    p0 = raw()

    # delta & gamma — central FD on F
    dF   = F * 1e-4
    p_fu = raw(F_=F + dF)
    p_fd = raw(F_=F - dF)
    delta = (p_fu - p_fd) / (2.0 * dF)
    gamma = (p_fu - 2.0 * p0 + p_fd) / (dF * dF)

    # vega — central FD on sigma
    ds   = 1e-4
    vega = (raw(sigma_=sigma + ds) - raw(sigma_=sigma - ds)) / (2.0 * ds)

    # theta — forward FD on T (annualised, consistent with black76.py)
    dT    = 1.0 / 365
    theta = (raw(T_=max(T - dT, 1e-10)) - p0) / dT

    # rho — central FD on r
    dr  = 1e-4
    rho = (raw(r_=r + dr) - raw(r_=r - dr)) / (2.0 * dr)

    return GreeksResult(price=p0, delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)
