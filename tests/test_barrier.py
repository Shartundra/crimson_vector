"""
Tests for Reiner-Rubinstein (1991) barrier option pricing.

The gold-standard test is in-out parity: knock_in + knock_out == vanilla Black-76.
This holds analytically and validates all 8 formula branches simultaneously.
Reference prices are computed from this implementation and verified to be
internally consistent; in-out parity guarantees correctness of relative values.
"""
import math
import pytest
import pandas as pd

from pricing import price, price_dataframe
from pricing.models.black76 import price as b76
from pricing.models.reiner_rubinstein import _barrier_price_raw as raw


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BASE = dict(F=100.0, K=100.0, T=0.5, r=0.05, sigma=0.25)


def barrier(call_put, barrier_dir, knock, H=None, rebate=0.0, **overrides):
    params = {**BASE, **overrides}
    if H is None:
        H = 95.0 if barrier_dir == "down" else 105.0
    return price(
        structure="barrier", model="reiner_rubinstein",
        H=H, call_put=call_put, barrier_dir=barrier_dir, knock=knock, rebate=rebate,
        **params,
    )


def vanilla(call_put, **overrides):
    return b76(**{**BASE, **overrides}, call_put=call_put)


# ---------------------------------------------------------------------------
# 1. In-out parity  (knock_in + knock_out == vanilla Black-76)
#    Tests ALL 8 formula branches across multiple strike/barrier configurations.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call_put,barrier_dir,H,K", [
    # ATM, down barrier (K >= H)
    ("call", "down", 95,  100),
    ("put",  "down", 95,  100),
    # ATM, up barrier (K <= H)
    ("call", "up",   105, 100),
    ("put",  "up",   105, 100),
    # K < H (down barrier — exercises the B/D_term branches)
    ("call", "down", 95,  90),
    ("put",  "down", 95,  90),
    # K > H (up barrier — exercises the A/C branches for up options)
    ("call", "up",   105, 110),
    ("put",  "up",   105, 110),
    # OTM variants
    ("call", "down", 95,  105),
    ("put",  "up",   105, 95),
])
def test_in_out_parity(call_put, barrier_dir, H, K):
    v = vanilla(call_put, K=K).price
    ko = raw(**{**BASE, "K": K}, H=H, call_put=call_put,
             barrier_dir=barrier_dir, knock="out", rebate=0)
    ki = raw(**{**BASE, "K": K}, H=H, call_put=call_put,
             barrier_dir=barrier_dir, knock="in",  rebate=0)
    assert ko + ki == pytest.approx(v, abs=1e-8)


# ---------------------------------------------------------------------------
# 2. Reference values (F=100, K=100, T=0.5, r=0.05, sigma=0.25)
#    Verified by in-out parity above; hardcoded to catch regressions.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call_put,barrier_dir,knock,H,expected_price", [
    # down barrier H=95
    ("call", "down", "out", 95,  3.873237),
    ("call", "down", "in",  95,  2.996063),
    ("put",  "down", "out", 95,  0.549561),
    ("put",  "down", "in",  95,  6.319739),
    # up barrier H=105
    ("call", "up",   "out", 105, 0.499505),
    ("call", "up",   "in",  105, 6.369796),
    ("put",  "up",   "out", 105, 3.721340),
    ("put",  "up",   "in",  105, 3.147961),
])
def test_reference_prices(call_put, barrier_dir, knock, H, expected_price):
    result = barrier(call_put, barrier_dir, knock, H=H)
    assert result.price == pytest.approx(expected_price, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. Degenerate: barrier already breached at initiation
# ---------------------------------------------------------------------------

def test_already_breached_knock_out_returns_discounted_rebate():
    # F=90 < H=95 → down barrier already breached
    rebate = 5.0
    p = raw(F=90, K=100, T=0.5, r=0.05, sigma=0.25,
            H=95, call_put="call", barrier_dir="down", knock="out", rebate=rebate)
    expected = rebate * math.exp(-0.05 * 0.5)
    assert p == pytest.approx(expected, rel=1e-8)


def test_already_breached_knock_in_returns_vanilla():
    # F=90 < H=95 → down barrier already breached → knock-in immediately live
    p = raw(F=90, K=100, T=0.5, r=0.05, sigma=0.25,
            H=95, call_put="call", barrier_dir="down", knock="in", rebate=0)
    v = vanilla("call", F=90).price
    assert p == pytest.approx(v, rel=1e-8)


def test_already_breached_up_knock_out():
    # F=110 > H=105 → up barrier already breached
    p = raw(F=110, K=100, T=0.5, r=0.05, sigma=0.25,
            H=105, call_put="put", barrier_dir="up", knock="out", rebate=3.0)
    expected = 3.0 * math.exp(-0.05 * 0.5)
    assert p == pytest.approx(expected, rel=1e-8)


# ---------------------------------------------------------------------------
# 4. Zero-rebate degenerate: options that can never pay their vanilla payoff
# ---------------------------------------------------------------------------

def test_up_out_call_K_ge_H_zero_rebate_is_zero():
    """Up-out call with K>=H: ITM payoff requires crossing barrier → always knocked out."""
    p = raw(F=100, K=110, T=0.5, r=0.05, sigma=0.25,
            H=105, call_put="call", barrier_dir="up", knock="out", rebate=0)
    assert p == pytest.approx(0.0, abs=1e-10)


def test_down_out_put_K_lt_H_zero_rebate_is_zero():
    """Down-out put with K<H: ITM payoff requires F_T<K<H → barrier always hit first."""
    p = raw(F=100, K=90, T=0.5, r=0.05, sigma=0.25,
            H=95, call_put="put", barrier_dir="down", knock="out", rebate=0)
    assert p == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# 5. Rebate increases knock-out value
# ---------------------------------------------------------------------------

def test_rebate_increases_knockout_price():
    ko_no_rebate = barrier("call", "down", "out", H=95, rebate=0.0).price
    ko_rebate    = barrier("call", "down", "out", H=95, rebate=5.0).price
    assert ko_rebate > ko_no_rebate


# ---------------------------------------------------------------------------
# 6. Greeks signs
# ---------------------------------------------------------------------------

def test_down_out_call_delta_positive():
    r = barrier("call", "down", "out", H=95)
    assert r.delta > 0


def test_down_out_put_delta_negative():
    r = barrier("put", "down", "out", H=95)
    assert r.delta < 0


def test_theta_negative():
    # Long barrier option should lose value as time passes (away from barrier)
    r = barrier("call", "down", "out", H=80)  # far barrier — well-behaved theta
    assert r.theta < 0


# ---------------------------------------------------------------------------
# 7. Input validation
# ---------------------------------------------------------------------------

def test_invalid_call_put_raises():
    with pytest.raises(ValueError, match="call_put"):
        price("barrier", "reiner_rubinstein", **BASE, H=95,
              call_put="straddle", barrier_dir="down", knock="out")


def test_invalid_barrier_dir_raises():
    with pytest.raises(ValueError, match="barrier_dir"):
        price("barrier", "reiner_rubinstein", **BASE, H=95,
              call_put="call", barrier_dir="sideways", knock="out")


def test_invalid_knock_raises():
    with pytest.raises(ValueError, match="knock"):
        price("barrier", "reiner_rubinstein", **BASE, H=95,
              call_put="call", barrier_dir="down", knock="maybe")


def test_negative_rebate_raises():
    with pytest.raises(ValueError, match="rebate"):
        price("barrier", "reiner_rubinstein", **BASE, H=95,
              call_put="call", barrier_dir="down", knock="out", rebate=-1.0)


def test_zero_F_returns_zero_greeks():
    r = price("barrier", "reiner_rubinstein", F=0, K=100, T=0.5, r=0.05, sigma=0.25,
              H=95, call_put="call", barrier_dir="down", knock="out")
    assert r == pytest.approx((0.0,) * 6, abs=1e-10)


# ---------------------------------------------------------------------------
# 8. Batch pricing via price_dataframe
# ---------------------------------------------------------------------------

def test_batch_barrier():
    df = pd.DataFrame([
        dict(F=100, K=100, T=0.5, r=0.05, sigma=0.25, H=95,
             call_put="call", barrier_dir="down", knock="out"),
        dict(F=100, K=100, T=0.5, r=0.05, sigma=0.25, H=95,
             call_put="put",  barrier_dir="down", knock="in"),
        dict(F=100, K=100, T=0.5, r=0.05, sigma=0.25, H=105,
             call_put="call", barrier_dir="up", knock="in"),
    ])
    result = price_dataframe(df, structure="barrier", model="reiner_rubinstein")
    assert {"price", "delta", "gamma", "theta", "vega", "rho"}.issubset(result.columns)
    assert len(result) == 3
    assert result["price"].notna().all()
    assert (result["price"] >= 0).all()
