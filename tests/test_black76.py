import math
import pytest
import pandas as pd

from pricing.black76 import price
from pricing._types import GreeksResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pcp_forward(F, K, T, r):
    """Put-call parity: C - P = exp(-rT) * (F - K)."""
    return math.exp(-r * T) * (F - K)


# ---------------------------------------------------------------------------
# 1. Put-call parity (parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("F,K,T,r,sigma", [
    (100.0, 100.0, 1.0,  0.05, 0.20),
    (100.0, 110.0, 0.5,  0.04, 0.25),
    (450.0, 460.0, 0.25, 0.05, 0.18),
    (200.0,  80.0, 2.0,  0.03, 0.35),
    (50.0,   55.0, 0.1,  0.00, 0.50),
])
def test_put_call_parity(F, K, T, r, sigma):
    c = price(F=F, K=K, T=T, r=r, sigma=sigma, option_type="call")
    p = price(F=F, K=K, T=T, r=r, sigma=sigma, option_type="put")
    assert c.price - p.price == pytest.approx(pcp_forward(F, K, T, r), abs=1e-10)


# ---------------------------------------------------------------------------
# 2. ATM symmetry: when F == K, call price == put price
# ---------------------------------------------------------------------------

def test_atm_call_equals_put():
    c = price(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call")
    p = price(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="put")
    assert c.price == pytest.approx(p.price, rel=1e-10)


# ---------------------------------------------------------------------------
# 3. Reference values (verified against closed-form computation)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs,attr,expected,tol", [
    # ATM call/put: price, delta, gamma, vega
    (dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call"),  "price",  7.577082, 1e-4),
    (dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call"),  "delta",  0.513500, 1e-4),
    (dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put"),   "price",  7.577082, 1e-4),
    (dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put"),   "delta", -0.437729, 1e-4),
    # OTM call
    (dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25, option_type="call"),  "price",  3.373074, 1e-4),
    (dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25, option_type="call"),  "delta",  0.319622, 1e-4),
    # ITM put
    (dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25, option_type="put"),   "price", 13.175061, 1e-4),
    # Futures-size call (ES-like)
    (dict(F=450, K=460, T=0.25, r=0.05, sigma=0.18, option_type="call"), "price", 11.668628, 1e-4),
    (dict(F=450, K=460, T=0.25, r=0.05, sigma=0.18, option_type="put"),  "price", 21.544406, 1e-4),
])
def test_reference_values(kwargs, attr, expected, tol):
    result = price(**kwargs)
    assert getattr(result, attr) == pytest.approx(expected, rel=tol)


# ---------------------------------------------------------------------------
# 4. Greeks signs and magnitudes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opt_type,delta_min,delta_max", [
    ("call",  0.0,  1.0),
    ("put",  -1.0,  0.0),
])
def test_delta_bounds(opt_type, delta_min, delta_max):
    r = price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type=opt_type)
    D = math.exp(-0.05 * 1.0)
    # delta in (0, D) for call or (-D, 0) for put
    assert delta_min * D < r.delta < delta_max * D or r.delta == pytest.approx(delta_min * D) or r.delta == pytest.approx(delta_max * D)


def test_gamma_positive():
    for opt in ("call", "put"):
        r = price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type=opt)
        assert r.gamma > 0


def test_vega_positive():
    for opt in ("call", "put"):
        r = price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type=opt)
        assert r.vega > 0


def test_theta_negative():
    for opt in ("call", "put"):
        r = price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type=opt)
        assert r.theta < 0


def test_gamma_vega_identical_for_call_put():
    c = price(F=100, K=105, T=0.5, r=0.04, sigma=0.25, option_type="call")
    p = price(F=100, K=105, T=0.5, r=0.04, sigma=0.25, option_type="put")
    assert c.gamma == pytest.approx(p.gamma, rel=1e-10)
    assert c.vega == pytest.approx(p.vega, rel=1e-10)


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

def test_expired_call_itm():
    r = price(F=110, K=100, T=0.0, r=0.05, sigma=0.20, option_type="call")
    assert r.price == pytest.approx(10.0)
    assert r.delta == pytest.approx(1.0)
    assert r.gamma == r.vega == r.theta == 0.0


def test_expired_call_otm():
    r = price(F=90, K=100, T=0.0, r=0.05, sigma=0.20, option_type="call")
    assert r.price == pytest.approx(0.0)
    assert r.delta == pytest.approx(0.0)


def test_expired_put_itm():
    r = price(F=90, K=100, T=0.0, r=0.05, sigma=0.20, option_type="put")
    assert r.price == pytest.approx(10.0)
    assert r.delta == pytest.approx(-1.0)


def test_zero_vol_call_itm():
    r = price(F=110, K=100, T=1.0, r=0.05, sigma=0.0, option_type="call")
    assert r.price == pytest.approx(10.0)
    assert r.vega == 0.0


def test_zero_vol_put_otm():
    r = price(F=110, K=100, T=1.0, r=0.05, sigma=0.0, option_type="put")
    assert r.price == pytest.approx(0.0)


def test_atm_delta_near_half():
    r = price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    D = math.exp(-0.05 * 1.0)
    assert r.delta == pytest.approx(0.5 * D, rel=0.15)  # within 15% of D/2 for ATM


def test_invalid_option_type():
    with pytest.raises(ValueError, match="option_type"):
        price(F=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="straddle")


def test_invalid_F():
    r = price(F=0, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    assert r == GreeksResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 6. Batch pricing via price_dataframe
# ---------------------------------------------------------------------------

def test_batch_pricing():
    from pricing.batch import price_dataframe

    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call"),
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="put"),
        dict(F=450.0, K=460.0, T=0.25, r=0.05, sigma=0.18, option_type="call"),
        dict(F=450.0, K=460.0, T=0.25, r=0.05, sigma=0.18, option_type="put"),
    ])

    result = price_dataframe(df)

    assert set(["price", "delta", "gamma", "theta", "vega", "rho"]).issubset(result.columns)
    assert len(result) == 4
    assert result[["price", "delta", "gamma", "vega"]].notna().all().all()


def test_batch_does_not_mutate_input():
    from pricing.batch import price_dataframe

    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call"),
    ])
    original_cols = list(df.columns)
    price_dataframe(df)
    assert list(df.columns) == original_cols


def test_batch_unknown_model():
    from pricing.batch import price_dataframe

    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, option_type="call"),
    ])
    with pytest.raises(ValueError, match="black76"):
        price_dataframe(df, model="sabr")
