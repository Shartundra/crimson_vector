"""
IBKR options chain fetcher using ib_insync.

Requires TWS or IB Gateway to be running with API access enabled:
  TWS:        Enable API via Edit → Global Config → API → Settings
              Check "Enable ActiveX and Socket Clients", uncheck "Read-Only API"
  Port:       7497 (TWS paper) / 7496 (TWS live) / 4002 (Gateway paper) / 4001 (Gateway live)

Standalone usage:
    python -m ingestion.ib_options
"""

import time
from datetime import datetime

import pandas as pd
from ib_insync import IB, FuturesOption, Future, util
from loguru import logger

from ingestion.config import (
    DATA_RAW_DIR,
    IB_CLIENT_ID,
    IB_HOST,
    IB_MAX_EXPIRIES,
    IB_MAX_STRIKES,
    IB_PORT,
)
from ingestion.pipeline import save_dataframe
from ingestion.utils import ensure_output_dir

util.logToConsole(False)   # suppress ib_insync's own logger; we use loguru


# ── connection helpers ────────────────────────────────────────────────────────

def connect(host: str = IB_HOST, port: int = IB_PORT, client_id: int = IB_CLIENT_ID) -> IB:
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10)
    logger.info(f"Connected to IB  host={host}  port={port}  clientId={client_id}")
    return ib


def disconnect(ib: IB) -> None:
    ib.disconnect()
    logger.info("Disconnected from IB")


# ── contract helpers ──────────────────────────────────────────────────────────

def get_front_month_corn(ib: IB) -> Future:
    """Qualify and return the front-month ZC (corn) futures contract."""
    contract = Future(symbol="ZC", exchange="CBOT", currency="USD")
    [qualified] = ib.qualifyContracts(contract)
    logger.info(f"Front-month corn: {qualified.localSymbol}  conId={qualified.conId}")
    return qualified


def get_corn_option_params(ib: IB, underlying: Future) -> pd.DataFrame:
    """
    Call reqSecDefOptParams to discover all valid strikes + expiries for
    options on the given corn futures contract.
    Returns a flat DataFrame with columns: expiry, strike.
    """
    chains = ib.reqSecDefOptParams(
        underlyingSymbol=underlying.symbol,
        futFopExchange="",          # empty → IB returns all exchanges
        underlyingSecType="FUT",
        underlyingConId=underlying.conId,
    )
    # Filter to CBOT only (avoids duplicates from other exchanges)
    cbot_chains = [c for c in chains if c.exchange == "CBOT"]
    if not cbot_chains:
        cbot_chains = chains   # fall back to all if CBOT not listed separately

    rows = []
    for chain in cbot_chains:
        for expiry in chain.expirations:
            for strike in chain.strikes:
                rows.append({"expiry": expiry, "strike": float(strike)})

    df = pd.DataFrame(rows).drop_duplicates().sort_values(["expiry", "strike"])
    logger.info(f"Option params: {df['expiry'].nunique()} expiries, {df['strike'].nunique()} unique strikes")
    return df


def select_strikes_near_atm(
    strikes: list[float],
    atm_price: float,
    max_strikes: int | None = IB_MAX_STRIKES,
) -> list[float]:
    """Return up to max_strikes strikes centred on atm_price, sorted ascending."""
    sorted_strikes = sorted(strikes)
    if max_strikes is None:
        return sorted_strikes

    # Find index of closest strike to ATM
    atm_idx = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - atm_price))
    half = max_strikes // 2
    lo = max(0, atm_idx - half)
    hi = min(len(sorted_strikes), atm_idx + half + (max_strikes % 2))
    return sorted_strikes[lo:hi]


# ── market data ───────────────────────────────────────────────────────────────

def fetch_snapshot(ib: IB, contracts: list) -> list:
    """Request delayed snapshots for a batch of contracts. Returns Ticker list."""
    # reqTickers fetches a snapshot synchronously (waits for data)
    tickers = ib.reqTickers(*contracts)
    return tickers


def ticker_to_row(ticker, expiry: str, option_type: str) -> dict:
    c = ticker.contract
    return {
        "contract_symbol":    c.localSymbol,
        "expiry":             expiry,
        "strike":             c.strike,
        "option_type":        option_type,
        "last_price":         ticker.last if ticker.last and ticker.last > 0 else float("nan"),
        "bid":                ticker.bid  if ticker.bid  and ticker.bid  > 0 else float("nan"),
        "ask":                ticker.ask  if ticker.ask  and ticker.ask  > 0 else float("nan"),
        "volume":             int(ticker.volume) if ticker.volume and ticker.volume >= 0 else pd.NA,
        "open_interest":      int(ticker.callOpenInterest if option_type == "call"
                                  else ticker.putOpenInterest)
                              if (ticker.callOpenInterest or ticker.putOpenInterest) else pd.NA,
        "implied_volatility": ticker.impliedVolatility if ticker.impliedVolatility else float("nan"),
        "delta":              ticker.modelGreeks.delta if ticker.modelGreeks else float("nan"),
        "gamma":              ticker.modelGreeks.gamma if ticker.modelGreeks else float("nan"),
        "theta":              ticker.modelGreeks.theta if ticker.modelGreeks else float("nan"),
        "vega":               ticker.modelGreeks.vega  if ticker.modelGreeks else float("nan"),
        "last_trade_date":    pd.NaT,
        "currency":           c.currency,
        "exchange":           c.exchange,
    }


# ── main fetch function ───────────────────────────────────────────────────────

def fetch_corn_options(
    host: str = IB_HOST,
    port: int = IB_PORT,
    client_id: int = IB_CLIENT_ID,
    max_expiries: int = IB_MAX_EXPIRIES,
    max_strikes: int | None = IB_MAX_STRIKES,
    save: bool = True,
) -> pd.DataFrame:
    """
    Connect to IB, pull corn futures options chain, return as DataFrame.

    Columns match the yfinance options schema plus IB extras (greeks).
    """
    ib = connect(host, port, client_id)
    try:
        # 1. Get the underlying futures contract + current price
        underlying = get_front_month_corn(ib)
        [und_ticker] = ib.reqTickers(underlying)
        atm_price = und_ticker.last or und_ticker.close or 460.0
        logger.info(f"Corn ATM price: {atm_price}")

        # 2. Discover all valid strikes / expiries
        params_df = get_corn_option_params(ib, underlying)
        if params_df.empty:
            logger.error("No option params returned — check TWS market data subscriptions")
            return pd.DataFrame()

        expiries = sorted(params_df["expiry"].unique())[:max_expiries]
        logger.info(f"Fetching {max_expiries} expiries: {expiries}")

        all_rows: list[dict] = []

        for expiry in expiries:
            strikes_all = params_df[params_df["expiry"] == expiry]["strike"].tolist()
            strikes = select_strikes_near_atm(strikes_all, atm_price, max_strikes)
            logger.info(f"  {expiry}: {len(strikes)} strikes (ATM≈{atm_price:.2f})")

            # Build call + put contracts
            contracts = []
            for strike in strikes:
                for right in ("C", "P"):
                    contracts.append(FuturesOption(
                        symbol="ZC",
                        lastTradeDateOrContractMonth=expiry,
                        strike=strike,
                        right=right,
                        exchange="CBOT",
                        currency="USD",
                        multiplier="50",   # corn: 5000 bu, quoted in cents → $50/cent
                    ))

            # Qualify contracts (IB assigns conId; invalid ones are filtered out)
            qualified = ib.qualifyContracts(*contracts)
            if not qualified:
                logger.warning(f"  {expiry}: no contracts qualified")
                continue
            logger.info(f"  {expiry}: {len(qualified)} contracts qualified")

            # Fetch market data in batches of 50 (IB rate limit)
            batch_size = 50
            for i in range(0, len(qualified), batch_size):
                batch = qualified[i : i + batch_size]
                tickers = fetch_snapshot(ib, batch)
                for ticker in tickers:
                    right = ticker.contract.right
                    opt_type = "call" if right == "C" else "put"
                    all_rows.append(ticker_to_row(ticker, expiry, opt_type))
                time.sleep(0.5)   # stay under IB's pacing limits

    finally:
        disconnect(ib)

    if not all_rows:
        logger.error("No option rows collected")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # Dtype cleanup
    for col in ("volume", "open_interest"):
        df[col] = pd.array(df[col], dtype="Int64")
    df["iv_suspect"] = df["implied_volatility"].isna() | (df["implied_volatility"] == 0.0)
    df["ticker"] = "ZC"
    df = df.sort_values(["expiry", "option_type", "strike"]).reset_index(drop=True)

    logger.info(f"Corn options: {len(df)} rows, {df['expiry'].nunique()} expiries")

    if save:
        ensure_output_dir(DATA_RAW_DIR)
        save_dataframe(df, "options_ZC_corn_ib", DATA_RAW_DIR)

    return df


if __name__ == "__main__":
    df = fetch_corn_options()
    if not df.empty:
        print(df[["expiry", "option_type", "strike", "bid", "ask",
                   "implied_volatility", "delta", "open_interest"]].head(30).to_string())
