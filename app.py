"""
Crimson Vector — Market Data Explorer
Run: streamlit run app.py
"""

import glob
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ingestion.config import DATA_RAW_DIR, EQUITY_TICKERS, FUTURES_TICKERS, IB_HOST, IB_PORT

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Crimson Vector",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .stTabs [data-baseweb="tab"] { font-size: 0.95rem; font-weight: 600; }
    .metric-card { background: #1e1e2e; border-radius: 8px; padding: 0.75rem 1rem; }
</style>
""", unsafe_allow_html=True)

# ── helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_futures() -> pd.DataFrame:
    frames = []
    for p in [DATA_RAW_DIR / "futures_ohlcv.parquet",
              DATA_RAW_DIR / "futures_corn_ZC.parquet"]:
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


@st.cache_data(ttl=300)
def load_spot() -> pd.DataFrame:
    p = DATA_RAW_DIR / "spot_prices.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


@st.cache_data(ttl=300)
def load_options(ticker: str) -> pd.DataFrame:
    p = DATA_RAW_DIR / f"options_{ticker}.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def available_options_tickers() -> list[str]:
    files = glob.glob(str(DATA_RAW_DIR / "options_*.parquet"))
    return sorted(Path(f).stem.replace("options_", "") for f in files)


def run_pipeline():
    from ingestion.pipeline import run_ingestion
    with st.spinner("Fetching live data from Yahoo Finance…"):
        run_ingestion()
    st.cache_data.clear()
    st.success("Data refreshed.")


def candlestick(df: pd.DataFrame, title: str) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.04,
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="OHLC",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"], name="Volume",
        marker_color="#5c6bc0", opacity=0.7,
    ), row=2, col=1)
    fig.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        height=520, template="plotly_dark",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.02),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


def iv_smile(df: pd.DataFrame, expiry: str) -> go.Figure:
    sub = df[df["expiry"] == expiry].copy()
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=calls["strike"], y=calls["implied_volatility"] * 100,
        mode="lines+markers", name="Calls IV",
        line=dict(color="#26a69a", width=2),
        marker=dict(size=5),
    ))
    fig.add_trace(go.Scatter(
        x=puts["strike"], y=puts["implied_volatility"] * 100,
        mode="lines+markers", name="Puts IV",
        line=dict(color="#ef5350", width=2),
        marker=dict(size=5),
    ))
    fig.update_layout(
        title=f"IV Smile — expiry {expiry}",
        xaxis_title="Strike", yaxis_title="Implied Volatility (%)",
        height=380, template="plotly_dark",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def oi_chart(df: pd.DataFrame, expiry: str) -> go.Figure:
    sub = df[df["expiry"] == expiry].copy()
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=calls["strike"],
        y=calls["open_interest"].astype("float"),
        name="Call OI", marker_color="#26a69a", opacity=0.8,
    ))
    fig.add_trace(go.Bar(
        x=puts["strike"],
        y=puts["open_interest"].astype("float"),
        name="Put OI", marker_color="#ef5350", opacity=0.8,
    ))
    fig.update_layout(
        title=f"Open Interest by Strike — expiry {expiry}",
        xaxis_title="Strike", yaxis_title="Open Interest",
        barmode="overlay", height=320,
        template="plotly_dark",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def greeks_chart(df: pd.DataFrame, expiry: str) -> go.Figure | None:
    """Delta and gamma by strike — only rendered when IB data is present."""
    sub = df[(df["expiry"] == expiry) & df.columns.isin(["delta","gamma","strike","option_type"]).all(axis=None) == False]
    if "delta" not in df.columns:
        return None
    sub = df[df["expiry"] == expiry].copy()
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Delta by Strike", "Gamma by Strike"])
    for df_side, name, color in [(calls, "Call Δ", "#26a69a"), (puts, "Put Δ", "#ef5350")]:
        fig.add_trace(go.Scatter(
            x=df_side["strike"], y=df_side["delta"],
            mode="lines+markers", name=name, line=dict(color=color, width=2),
        ), row=1, col=1)
    for df_side, name, color in [(calls, "Call Γ", "#26a69a"), (puts, "Put Γ", "#ef5350")]:
        fig.add_trace(go.Scatter(
            x=df_side["strike"], y=df_side["gamma"],
            mode="lines+markers", name=name, line=dict(color=color, width=2), showlegend=False,
        ), row=1, col=2)
    fig.update_layout(
        height=320, template="plotly_dark",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.1),
    )
    return fig


# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🔴 Crimson Vector")
    st.caption("Exotic Options Pricing System")
    st.divider()

    st.subheader("Yahoo Finance")
    if st.button("⟳  Refresh YF Data", use_container_width=True, type="primary"):
        run_pipeline()

    st.divider()
    st.subheader("Interactive Brokers")
    ib_port = st.number_input(
        "TWS / Gateway port",
        value=IB_PORT,
        step=1,
        help="7497=TWS paper  7496=TWS live  4002=Gateway paper  4001=Gateway live",
    )
    if st.button("🌽  Pull Corn Options (IB)", use_container_width=True):
        from ingestion.ib_options import fetch_corn_options
        with st.spinner("Connecting to IB and fetching corn options…"):
            try:
                df_ib = fetch_corn_options(port=int(ib_port))
                if df_ib.empty:
                    st.error("No data returned — check TWS is running and API is enabled.")
                else:
                    st.cache_data.clear()
                    st.success(f"Fetched {len(df_ib):,} rows from IB.")
            except Exception as e:
                st.error(f"IB connection failed: {e}")

    st.divider()
    data_dir_exists = DATA_RAW_DIR.exists()
    parquet_count = len(list(DATA_RAW_DIR.glob("*.parquet"))) if data_dir_exists else 0
    st.metric("Datasets loaded", parquet_count)
    if parquet_count == 0:
        st.warning("No data found. Use the buttons above to pull data.")

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_futures, tab_spot, tab_options, tab_raw = st.tabs([
    "📊 Futures", "💹 Spot Prices", "🎯 Options Chain", "🗃 Raw Data"
])

# ── FUTURES TAB ───────────────────────────────────────────────────────────────
with tab_futures:
    futures_df = load_futures()
    if futures_df.empty:
        st.info("No futures data. Click **Refresh Data** in the sidebar.")
    else:
        all_tickers = sorted(futures_df["ticker"].unique())
        col1, col2 = st.columns([3, 1])
        with col1:
            sel_ticker = st.selectbox("Contract", all_tickers,
                                      format_func=lambda t: f"{t}  ({futures_df[futures_df['ticker']==t]['contract_name'].iloc[0]})")
        with col2:
            currency_note = "USX/bu ÷ 100 = USD" if sel_ticker == "ZC=F" else ""
            if currency_note:
                st.caption(f"⚠ {currency_note}")

        sub = futures_df[futures_df["ticker"] == sel_ticker].sort_index()
        contract = sub["contract_name"].iloc[0]

        # KPI row
        last  = sub["Close"].iloc[-1]
        prev  = sub["Close"].iloc[-2]
        chg   = last - prev
        pct   = chg / prev * 100
        vol   = sub["Volume"].iloc[-1]
        hi30  = sub["High"].max()
        lo30  = sub["Low"].min()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Last Close", f"{last:,.4f}", f"{chg:+.4f} ({pct:+.2f}%)")
        k2.metric("Volume (last day)", f"{vol:,.0f}")
        k3.metric("30d High", f"{hi30:,.4f}")
        k4.metric("30d Low",  f"{lo30:,.4f}")

        st.plotly_chart(candlestick(sub, f"{sel_ticker} — {contract}"), use_container_width=True)

        with st.expander("OHLCV Table"):
            display = sub[["Open","High","Low","Close","Volume"]].copy()
            display.index = display.index.strftime("%Y-%m-%d")
            st.dataframe(display.sort_index(ascending=False), use_container_width=True)

# ── SPOT TAB ──────────────────────────────────────────────────────────────────
with tab_spot:
    spot_df = load_spot()
    if spot_df.empty:
        st.info("No spot data. Click **Refresh Data** in the sidebar.")
    else:
        all_spot = sorted(spot_df["ticker"].unique())
        sel_spots = st.multiselect(
            "Select tickers to compare",
            all_spot,
            default=[t for t in ["SPY", "QQQ", "GLD"] if t in all_spot],
        )

        if sel_spots:
            fig = go.Figure()
            for t in sel_spots:
                s = spot_df[spot_df["ticker"] == t].sort_index()
                # Normalise to 100 for comparison if >1 ticker
                base = s["Close"].iloc[0]
                y = (s["Close"] / base * 100) if len(sel_spots) > 1 else s["Close"]
                fig.add_trace(go.Scatter(
                    x=s.index, y=y, mode="lines", name=t,
                    line=dict(width=2),
                ))
            fig.update_layout(
                title="Close Price" + (" (rebased to 100)" if len(sel_spots) > 1 else ""),
                xaxis_title="Date",
                yaxis_title="Rebased Price" if len(sel_spots) > 1 else "Price (USD)",
                height=440, template="plotly_dark",
                margin=dict(l=10, r=10, t=40, b=10),
                legend=dict(orientation="h", y=1.05),
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Data Table"):
                pivot = (
                    spot_df[spot_df["ticker"].isin(sel_spots)][["ticker","Close"]]
                    .reset_index()
                    .pivot(index="Date", columns="ticker", values="Close")
                    .sort_index(ascending=False)
                )
                pivot.index = pivot.index.strftime("%Y-%m-%d")
                st.dataframe(pivot, use_container_width=True)

# ── OPTIONS TAB ───────────────────────────────────────────────────────────────
with tab_options:
    opt_tickers = available_options_tickers()
    if not opt_tickers:
        st.info("No options data. Click **Refresh Data** in the sidebar.")
    else:
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            opt_ticker = st.selectbox("Underlying", opt_tickers)
        opt_df = load_options(opt_ticker)

        expiries = sorted(opt_df["expiry"].unique()) if not opt_df.empty else []
        with col2:
            sel_expiry = st.selectbox("Expiry", expiries)
        with col3:
            opt_type_filter = st.radio("Show", ["Both", "Calls", "Puts"], horizontal=True)

        if not opt_df.empty and sel_expiry:
            chain = opt_df[opt_df["expiry"] == sel_expiry].copy()
            if opt_type_filter == "Calls":
                chain = chain[chain["option_type"] == "call"]
            elif opt_type_filter == "Puts":
                chain = chain[chain["option_type"] == "put"]

            # KPI row
            calls_count = (chain["option_type"] == "call").sum()
            puts_count  = (chain["option_type"] == "put").sum()
            atm_iv = chain[(chain["in_the_money"] == False)]["implied_volatility"]
            median_iv = atm_iv.median() * 100 if not atm_iv.empty else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Calls", calls_count)
            k2.metric("Puts",  puts_count)
            k3.metric("OTM median IV", f"{median_iv:.1f}%")
            k4.metric("Total contracts", len(chain))

            # IV Smile + OI
            c1, c2 = st.columns([1, 1])
            with c1:
                st.plotly_chart(iv_smile(opt_df, sel_expiry), use_container_width=True)
            with c2:
                st.plotly_chart(oi_chart(opt_df, sel_expiry), use_container_width=True)

            # Greeks charts — only shown when IB data (has delta/gamma cols) is loaded
            g_fig = greeks_chart(opt_df, sel_expiry)
            if g_fig is not None:
                st.plotly_chart(g_fig, use_container_width=True)

            # Strike ladder — calls on left, puts on right
            st.subheader("Strike Ladder")
            has_greeks = "delta" in chain.columns

            call_cols = ["strike","bid","ask","last_price","implied_volatility","open_interest","iv_suspect"]
            put_cols  = ["strike","bid","ask","last_price","implied_volatility","open_interest","iv_suspect"]
            if has_greeks:
                call_cols += ["delta","gamma","theta","vega"]
                put_cols  += ["delta","gamma","theta","vega"]
            # Keep only cols that actually exist
            call_cols = [c for c in call_cols if c in chain.columns]
            put_cols  = [c for c in put_cols  if c in chain.columns]

            calls = chain[chain["option_type"] == "call"][call_cols].sort_values("strike").rename(columns={
                "bid":"call_bid","ask":"call_ask","last_price":"call_last",
                "implied_volatility":"call_iv","open_interest":"call_oi",
                "iv_suspect":"call_iv_suspect",
                "delta":"call_Δ","gamma":"call_Γ","theta":"call_Θ","vega":"call_ν",
            }).set_index("strike")

            puts = chain[chain["option_type"] == "put"][put_cols].sort_values("strike").rename(columns={
                "bid":"put_bid","ask":"put_ask","last_price":"put_last",
                "implied_volatility":"put_iv","open_interest":"put_oi",
                "iv_suspect":"put_iv_suspect",
                "delta":"put_Δ","gamma":"put_Γ","theta":"put_Θ","vega":"put_ν",
            }).set_index("strike")

            ladder = calls.join(puts, how="outer").reset_index()
            for col in ["call_iv","put_iv"]:
                if col in ladder.columns:
                    ladder[col] = (ladder[col] * 100).round(2).astype(str) + "%"

            st.dataframe(
                ladder,
                use_container_width=True,
                height=420,
                column_config={
                    "strike":          st.column_config.NumberColumn("Strike", format="%.2f"),
                    "call_bid":        st.column_config.NumberColumn("Call Bid",  format="%.2f"),
                    "call_ask":        st.column_config.NumberColumn("Call Ask",  format="%.2f"),
                    "call_last":       st.column_config.NumberColumn("Call Last", format="%.2f"),
                    "call_oi":         st.column_config.NumberColumn("Call OI"),
                    "call_iv_suspect": st.column_config.CheckboxColumn("C IV?"),
                    "call_Δ":          st.column_config.NumberColumn("Call Δ",   format="%.3f"),
                    "call_Γ":          st.column_config.NumberColumn("Call Γ",   format="%.4f"),
                    "call_Θ":          st.column_config.NumberColumn("Call Θ",   format="%.3f"),
                    "call_ν":          st.column_config.NumberColumn("Call ν",   format="%.3f"),
                    "put_bid":         st.column_config.NumberColumn("Put Bid",   format="%.2f"),
                    "put_ask":         st.column_config.NumberColumn("Put Ask",   format="%.2f"),
                    "put_last":        st.column_config.NumberColumn("Put Last",  format="%.2f"),
                    "put_oi":          st.column_config.NumberColumn("Put OI"),
                    "put_iv_suspect":  st.column_config.CheckboxColumn("P IV?"),
                    "put_Δ":           st.column_config.NumberColumn("Put Δ",    format="%.3f"),
                    "put_Γ":           st.column_config.NumberColumn("Put Γ",    format="%.4f"),
                    "put_Θ":           st.column_config.NumberColumn("Put Θ",    format="%.3f"),
                    "put_ν":           st.column_config.NumberColumn("Put ν",    format="%.3f"),
                },
            )

# ── RAW DATA TAB ──────────────────────────────────────────────────────────────
with tab_raw:
    if parquet_count == 0:
        st.info("No data files found.")
    else:
        files = sorted(DATA_RAW_DIR.glob("*.parquet"))
        file_names = [f.name for f in files]
        sel_file = st.selectbox("Dataset", file_names)

        raw_df = pd.read_parquet(DATA_RAW_DIR / sel_file)
        st.caption(f"{len(raw_df):,} rows × {len(raw_df.columns)} columns")

        # Filter controls
        col1, col2 = st.columns([3, 1])
        with col1:
            search = st.text_input("Filter rows (substring match across all string columns)", "")
        with col2:
            max_rows = st.number_input("Max rows to show", 50, 5000, 200, step=50)

        if search:
            mask = raw_df.apply(lambda c: c.astype(str).str.contains(search, case=False, na=False)).any(axis=1)
            raw_df = raw_df[mask]

        st.dataframe(raw_df.head(max_rows), use_container_width=True, height=520)

        csv = raw_df.to_csv(index=True).encode()
        st.download_button(
            "⬇ Download as CSV",
            csv,
            file_name=sel_file.replace(".parquet", ".csv"),
            mime="text/csv",
        )
