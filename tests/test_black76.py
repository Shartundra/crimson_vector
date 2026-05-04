import math
import pytest
import pandas as pd

from pricing import price, price_dataframe, GreeksResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def eu(call_put, **kwargs):
    """Shorthand: price a European option via the registry."""
    return price(structure="european", model="black76", call_put=call_put, **kwargs)


def pcp_forward(F, K, T, r):
    return math.exp(-r * T) * (F - K)


BASE = dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20)


# ---------------------------------------------------------------------------
# 1. Put-call parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("F,K,T,r,sigma", [
    (100.0, 100.0, 1.0,  0.05, 0.20),
    (100.0, 110.0, 0.5,  0.04, 0.25),
    (450.0, 460.0, 0.25, 0.05, 0.18),
    (200.0,  80.0, 2.0,  0.03, 0.35),
    (50.0,   55.0, 0.1,  0.00, 0.50),
])
def test_put_call_parity(F, K, T, r, sigma):
    c = eu("call", F=F, K=K, T=T, r=r, sigma=sigma)
    p = eu("put",  F=F, K=K, T=T, r=r, sigma=sigma)
    assert c.price - p.price == pytest.approx(pcp_forward(F, K, T, r), abs=1e-10)


# ---------------------------------------------------------------------------
# 2. ATM symmetry
# ---------------------------------------------------------------------------

def test_atm_call_equals_put():
    c = eu("call", **BASE)
    p = eu("put",  **BASE)
    assert c.price == pytest.approx(p.price, rel=1e-10)


# ---------------------------------------------------------------------------
# 3. Reference values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call_put,params,attr,expected", [
    ("call", dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20), "price",  7.577082),
    ("call", dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20), "delta",  0.513500),
    ("put",  dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20), "price",  7.577082),
    ("put",  dict(F=100, K=100, T=1.0, r=0.05, sigma=0.20), "delta", -0.437729),
    ("call", dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25), "price",  3.373074),
    ("call", dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25), "delta",  0.319622),
    ("put",  dict(F=100, K=110, T=0.5, r=0.04, sigma=0.25), "price", 13.175061),
    ("call", dict(F=450, K=460, T=0.25, r=0.05, sigma=0.18), "price", 11.668628),
    ("put",  dict(F=450, K=460, T=0.25, r=0.05, sigma=0.18), "price", 21.544406),
])
def test_reference_values(call_put, params, attr, expected):
    result = eu(call_put, **params)
    assert getattr(result, attr) == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 4. Greeks signs
# ---------------------------------------------------------------------------

def test_call_delta_in_range():
    r = eu("call", **BASE)
    D = math.exp(-BASE["r"] * BASE["T"])
    assert 0 < r.delta < D


def test_put_delta_in_range():
    r = eu("put", **BASE)
    D = math.exp(-BASE["r"] * BASE["T"])
    assert -D < r.delta < 0


def test_gamma_positive():
    for cp in ("call", "put"):
        assert eu(cp, **BASE).gamma > 0


def test_vega_positive():
    for cp in ("call", "put"):
        assert eu(cp, **BASE).vega > 0


def test_theta_negative():
    for cp in ("call", "put"):
        assert eu(cp, **BASE).theta < 0


def test_gamma_vega_same_for_call_and_put():
    c = eu("call", F=100, K=105, T=0.5, r=0.04, sigma=0.25)
    p = eu("put",  F=100, K=105, T=0.5, r=0.04, sigma=0.25)
    assert c.gamma == pytest.approx(p.gamma, rel=1e-10)
    assert c.vega  == pytest.approx(p.vega,  rel=1e-10)


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

def test_expired_call_itm():
    r = eu("call", F=110, K=100, T=0.0, r=0.05, sigma=0.20)
    assert r.price == pytest.approx(10.0)
    assert r.delta == pytest.approx(1.0)
    assert r.gamma == r.vega == r.theta == 0.0


def test_expired_call_otm():
    r = eu("call", F=90, K=100, T=0.0, r=0.05, sigma=0.20)
    assert r.price == pytest.approx(0.0)
    assert r.delta == pytest.approx(0.0)


def test_expired_put_itm():
    r = eu("put", F=90, K=100, T=0.0, r=0.05, sigma=0.20)
    assert r.price == pytest.approx(10.0)
    assert r.delta == pytest.approx(-1.0)


def test_zero_vol_call_itm():
    r = eu("call", F=110, K=100, T=1.0, r=0.05, sigma=0.0)
    assert r.price == pytest.approx(10.0)
    assert r.vega  == 0.0


def test_zero_vol_put_otm():
    r = eu("put", F=110, K=100, T=1.0, r=0.05, sigma=0.0)
    assert r.price == pytest.approx(0.0)


def test_invalid_call_put():
    with pytest.raises(ValueError, match="call_put"):
        eu("straddle", **BASE)


def test_invalid_F():
    r = eu("call", F=0, K=100, T=1.0, r=0.05, sigma=0.20)
    assert r == GreeksResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 6. Registry — error handling
# ---------------------------------------------------------------------------

def test_unknown_model_for_known_structure():
    with pytest.raises(ValueError, match="black76"):
        price(structure="european", model="heston", **BASE, call_put="call")


def test_unknown_structure():
    with pytest.raises(ValueError, match="european"):
        price(structure="autocall", model="black76", **BASE)


# ---------------------------------------------------------------------------
# 7. Straddle composite
# ---------------------------------------------------------------------------

def test_straddle_equals_call_plus_put():
    s  = price(structure="straddle", model="black76", **BASE)
    c  = eu("call", **BASE)
    p  = eu("put",  **BASE)
    assert s.price == pytest.approx(c.price + p.price, rel=1e-10)
    assert s.delta == pytest.approx(c.delta + p.delta, rel=1e-10)
    assert s.gamma == pytest.approx(c.gamma + p.gamma, rel=1e-10)
    assert s.vega  == pytest.approx(c.vega  + p.vega,  rel=1e-10)


def test_straddle_delta_near_zero_atm():
    """ATM straddle delta ≈ 0 (call and put deltas nearly cancel)."""
    s = price(structure="straddle", model="black76", **BASE)
    assert abs(s.delta) < 0.1


def test_straddle_price_positive():
    s = price(structure="straddle", model="black76", **BASE)
    assert s.price > 0


# ---------------------------------------------------------------------------
# 8. Batch pricing
# ---------------------------------------------------------------------------

def test_batch_european():
    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, call_put="call"),
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, call_put="put"),
        dict(F=450.0, K=460.0, T=0.25, r=0.05, sigma=0.18, call_put="call"),
        dict(F=450.0, K=460.0, T=0.25, r=0.05, sigma=0.18, call_put="put"),
    ])
    result = price_dataframe(df, structure="european", model="black76")
    assert set(["price", "delta", "gamma", "theta", "vega", "rho"]).issubset(result.columns)
    assert len(result) == 4
    assert result[["price", "delta", "gamma", "vega"]].notna().all().all()


def test_batch_straddle():
    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0,  r=0.05, sigma=0.20),
        dict(F=450.0, K=460.0, T=0.25, r=0.05, sigma=0.18),
    ])
    result = price_dataframe(df, structure="straddle", model="black76")
    assert len(result) == 2
    assert (result["price"] > 0).all()


def test_batch_does_not_mutate_input():
    df = pd.DataFrame([
        dict(F=100.0, K=100.0, T=1.0, r=0.05, sigma=0.20, call_put="call"),
    ])
    original_cols = list(df.columns)
    price_dataframe(df, structure="european", model="black76")
    assert list(df.columns) == original_cols
