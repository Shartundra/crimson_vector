"""
Integration smoke tests — make real yfinance network calls.
Run with:
    python -m pytest tests/ -m integration -v
Excluded from CI by default (no --run-integration flag).
"""

import pytest

pytestmark = pytest.mark.integration


def test_spot_fetch_returns_nonempty():
    from ingestion.spot import fetch_spot_price

    df = fetch_spot_price("SPY")
    assert not df.empty, "SPY spot fetch returned empty DataFrame"
    assert (df["Close"] > 0).all(), "SPY Close prices should be positive"


def test_futures_fetch_returns_expected_tickers():
    from ingestion.futures import fetch_all_futures

    df = fetch_all_futures({"ES": "ES=F", "GC": "GC=F"})
    assert not df.empty, "Futures fetch returned empty DataFrame"
    tickers = df["ticker"].unique().tolist()
    assert "ES=F" in tickers, "ES=F missing from futures data"
    assert "GC=F" in tickers, "GC=F missing from futures data"


def test_options_expiries_nonempty():
    from ingestion.options import fetch_expiry_dates

    expiries = fetch_expiry_dates("SPY")
    assert len(expiries) > 0, "SPY should have at least one option expiry"


def test_options_chain_has_required_columns():
    from ingestion.options import fetch_option_chain_for_expiry, fetch_expiry_dates

    expiries = fetch_expiry_dates("SPY")
    assert expiries, "No expiries available for SPY"
    df = fetch_option_chain_for_expiry("SPY", expiries[0])
    assert not df.empty, "Options chain for SPY first expiry is empty"
    for col in ("strike", "implied_volatility", "option_type"):
        assert col in df.columns, f"Missing required column: {col}"


def test_options_iv_not_all_zero():
    from ingestion.options import fetch_option_chain_for_expiry, fetch_expiry_dates

    expiries = fetch_expiry_dates("SPY")
    assert expiries, "No expiries available for SPY"
    df = fetch_option_chain_for_expiry("SPY", expiries[0])
    assert not df.empty
    non_zero_iv = (df["implied_volatility"] > 0).sum()
    assert non_zero_iv > 0, "All implied volatility values are zero — suspicious"


def test_options_iv_suspect_column_present():
    from ingestion.options import fetch_option_chain_for_expiry, fetch_expiry_dates

    expiries = fetch_expiry_dates("SPY")
    assert expiries
    df = fetch_option_chain_for_expiry("SPY", expiries[0])
    assert "iv_suspect" in df.columns, "iv_suspect flag column missing"
