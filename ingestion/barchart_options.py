"""
Barchart OnDemand options fetcher for CBOT corn (ZC) futures options.

Requires a Barchart OnDemand API key:
  https://www.barchart.com/ondemand/api

Set via environment variable:
    export BARCHART_API_KEY=your_key_here

Or pass api_key directly to fetch_corn_options().

Standalone usage:
    python -m ingestion.barchart_options
"""

import os
import time

import pandas as pd
import requests
from loguru import logger

from ingestion.config import (
    BARCHART_API_KEY,
    BARCHART_BASE_URL,
    BARCHART_MAX_CONTRACTS,
    BARCHART_REQUEST_DELAY,
    DATA_RAW_DIR,
)
from ingestion.pipeline import save_dataframe
from ingestion.utils import ensure_output_dir


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(endpoint: str, params: dict) -> dict:
    """GET a Barchart OnDemand endpoint. Raises on HTTP error or API error status."""
    url = f"{BARCHART_BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", {})
    code = status.get("code", 200)
    if code not in (200, 204):
        raise ValueError(f"Barchart API error {code}: {status.get('message')}")
    return data


# ── contract discovery ────────────────────────────────────────────────────────

def get_active_corn_contracts(api_key: str, max_contracts: int = BARCHART_MAX_CONTRACTS) -> list[str]:
    """
    Call getFuturesExpirations to discover active ZC contracts.
    Returns a list of contract symbols like ['ZCK26', 'ZCN26', ...],
    sorted by expiration date, nearest first.
    """
    logger.info("Discovering active ZC corn futures contracts…")
    try:
        data = _get("getFuturesExpirations.json", {"roots": "ZC", "apikey": api_key})
    except Exception as exc:
        logger.error(f"getFuturesExpirations failed: {exc}")
        return _fallback_corn_contracts(max_contracts)

    results = data.get("results") or []
    if not results:
        logger.warning("No expiration results — falling back to generated symbols")
        return _fallback_corn_contracts(max_contracts)

    contracts = sorted(results, key=lambda r: r.get("expirationDate", ""))
    symbols = [r["symbol"] for r in contracts if r.get("symbol")]
    logger.info(f"Found {len(symbols)} active ZC contracts: {symbols[:max_contracts]}")
    return symbols[:max_contracts]


def _fallback_corn_contracts(n: int) -> list[str]:
    """
    Generate the next N corn futures contract symbols from today's date.
    Corn trades in March(H), May(K), July(N), September(U), December(Z).
    """
    from datetime import date

    month_codes = {3: "H", 5: "K", 7: "N", 9: "U", 12: "Z"}
    today = date.today()
    symbols: list[str] = []
    year = today.year

    for _ in range(n * 6):   # scan enough months ahead
        for month, code in sorted(month_codes.items()):
            candidate = date(year, month, 1)
            if candidate >= today:
                symbols.append(f"ZC{code}{str(year)[-2:]}")
        year += 1
        if len(symbols) >= n:
            break

    result = symbols[:n]
    logger.info(f"Fallback contracts: {result}")
    return result


# ── options fetch ─────────────────────────────────────────────────────────────

def fetch_options_for_contract(api_key: str, contract: str) -> pd.DataFrame:
    """
    Fetch the full options chain for a single ZC contract (e.g. 'ZCK26').
    Returns a normalised DataFrame with calls and puts combined.
    """
    logger.info(f"Fetching options for {contract}…")
    params = {
        "apikey":   api_key,
        "root":     "ZC",
        "contract": contract,
        "fields":   "openInterest,bid,ask,premium,settlement",
    }
    try:
        data = _get("getFuturesOptions.json", params)
    except Exception as exc:
        logger.warning(f"{contract}: request failed — {exc}")
        return pd.DataFrame()

    results = data.get("results") or []
    if not results:
        logger.warning(f"{contract}: no options data returned")
        return pd.DataFrame()

    rows = []
    for r in results:
        iv_raw = r.get("impliedVolatility")
        iv = float(iv_raw) if iv_raw not in (None, "", "N/A") else float("nan")

        def _float(key: str) -> float:
            v = r.get(key)
            return float(v) if v not in (None, "", "N/A") else float("nan")

        def _int(key: str):
            v = r.get(key)
            try:
                return int(float(v)) if v not in (None, "", "N/A") else pd.NA
            except (ValueError, TypeError):
                return pd.NA

        rows.append({
            "contract_symbol":    r.get("symbol", ""),
            "ticker":             "ZC",
            "expiry":             r.get("expirationDate", ""),
            "option_type":        r.get("type", "").lower(),   # "Call" → "call"
            "strike":             _float("strike"),
            "last_price":         _float("last"),
            "bid":                _float("bid"),
            "ask":                _float("ask"),
            "volume":             _int("volume"),
            "open_interest":      _int("openInterest"),
            "implied_volatility": iv,
            "delta":              _float("delta"),
            "gamma":              _float("gamma"),
            "theta":              _float("theta"),
            "vega":               _float("vega"),
            "last_trade_date":    pd.NaT,
            "currency":           "USD",
            "exchange":           r.get("exchange", "CBOT"),
            "contract":           contract,
            "iv_suspect":         (iv != iv) or iv == 0.0,   # NaN or zero
        })

    df = pd.DataFrame(rows)
    for col in ("volume", "open_interest"):
        df[col] = pd.array(df[col], dtype="Int64")
    df = df.sort_values(["option_type", "strike"]).reset_index(drop=True)
    logger.info(f"  {contract}: {len(df)} options ({(df['option_type']=='call').sum()} calls, {(df['option_type']=='put').sum()} puts)")
    return df


# ── main entry point ──────────────────────────────────────────────────────────

def fetch_corn_options(
    api_key: str = "",
    max_contracts: int = BARCHART_MAX_CONTRACTS,
    save: bool = True,
) -> pd.DataFrame:
    """
    Fetch CBOT corn (ZC) options chains from Barchart OnDemand.

    Args:
        api_key: Barchart API key. Falls back to BARCHART_API_KEY env var.
        max_contracts: Number of active contracts (expiries) to fetch.
        save: If True, saves result to data/raw/options_ZC_corn_barchart.parquet.

    Returns:
        Combined DataFrame with all expiries, calls and puts.
    """
    key = api_key or BARCHART_API_KEY
    if not key:
        raise ValueError(
            "No Barchart API key provided. Set BARCHART_API_KEY env var "
            "or pass api_key= to fetch_corn_options()."
        )

    contracts = get_active_corn_contracts(key, max_contracts)
    if not contracts:
        logger.error("No active ZC contracts found")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for contract in contracts:
        df = fetch_options_for_contract(key, contract)
        if not df.empty:
            frames.append(df)
        time.sleep(BARCHART_REQUEST_DELAY)

    if not frames:
        logger.error("No options data collected from Barchart")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["expiry", "option_type", "strike"]).reset_index(drop=True)
    logger.info(f"Barchart corn options: {len(combined)} rows, {combined['expiry'].nunique()} expiries")

    if save:
        ensure_output_dir(DATA_RAW_DIR)
        save_dataframe(combined, "options_ZC_corn_barchart", DATA_RAW_DIR)

    return combined


if __name__ == "__main__":
    key = os.environ.get("BARCHART_API_KEY", "")
    if not key:
        print("Set BARCHART_API_KEY env var before running.")
    else:
        df = fetch_corn_options(api_key=key)
        if not df.empty:
            print(df[["expiry", "option_type", "strike", "bid", "ask",
                       "implied_volatility", "delta", "open_interest"]].head(30).to_string())
