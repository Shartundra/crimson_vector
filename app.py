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

from ingestion.config import DATA_RAW_DIR, IB_PORT

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
</style>
""", unsafe_allow_html=True)

# ── data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_futures() -> pd.DataFrame:
    p = DATA_RAW_DIR / "futures_ZC_ib.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


@st.cache_data(ttl=300)
def load_options(name: str) -> pd.DataFrame:
    p = DATA_RAW_DIR / f"options_{name}.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def available_options_files() -> list[str]:
    files = glob.glob(str(DATA_RAW_DIR / "options_*.parquet"))
    return sorted(Path(f).stem.replace("options_", "") for f in files)


# ── charts ────────────────────────────────────────────────────────────────────

def candlestick(df: pd.DataFrame, title: str) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.75, 0.25], vertical_spacing=0.04,
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="OHLC",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
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
    fig.update_yaxes(title_text="Price (USX/bu)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


def iv_smile(df: pd.DataFrame, expiry: str) -> go.Figure:
    sub = df[df["expiry"] == expiry]
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=calls["strike"], y=calls["implied_volatility"] * 100,
        mode="lines+markers", name="Calls IV",
        line=dict(color="#26a69a", width=2), marker=dict(size=5),
    ))
    fig.add_trace(go.Scatter(
        x=puts["strike"], y=puts["implied_volatility"] * 100,
        mode="lines+markers", name="Puts IV",
        line=dict(color="#ef5350", width=2), marker=dict(size=5),
    ))
    fig.update_layout(
        title=f"IV Smile — {expiry}", xaxis_title="Strike",
        yaxis_title="Implied Volatility (%)", height=360,
        template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def oi_chart(df: pd.DataFrame, expiry: str) -> go.Figure:
    sub = df[df["expiry"] == expiry]
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=calls["strike"], y=calls["open_interest"].astype("float"),
        name="Call OI", marker_color="#26a69a", opacity=0.8,
    ))
    fig.add_trace(go.Bar(
        x=puts["strike"], y=puts["open_interest"].astype("float"),
        name="Put OI", marker_color="#ef5350", opacity=0.8,
    ))
    fig.update_layout(
        title=f"Open Interest — {expiry}", xaxis_title="Strike",
        yaxis_title="Open Interest", barmode="overlay", height=320,
        template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def greeks_chart(df: pd.DataFrame, expiry: str) -> go.Figure | None:
    if "delta" not in df.columns:
        return None
    sub = df[df["expiry"] == expiry]
    calls = sub[sub["option_type"] == "call"].sort_values("strike")
    puts  = sub[sub["option_type"] == "put"].sort_values("strike")
    fig = make_subplots(rows=1, cols=2, subplot_titles=["Delta by Strike", "Gamma by Strike"])
    for side, name, color in [(calls, "Call Δ", "#26a69a"), (puts, "Put Δ", "#ef5350")]:
        fig.add_trace(go.Scatter(
            x=side["strike"], y=side["delta"],
            mode="lines+markers", name=name, line=dict(color=color, width=2),
        ), row=1, col=1)
    for side, name, color in [(calls, "Call Γ", "#26a69a"), (puts, "Put Γ", "#ef5350")]:
        fig.add_trace(go.Scatter(
            x=side["strike"], y=side["gamma"],
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

    st.subheader("Interactive Brokers TWS")
    ib_port = st.number_input(
        "Port",
        value=IB_PORT,
        step=1,
        help="7497 TWS paper | 7496 TWS live | 4002 Gateway paper | 4001 Gateway live",
    )
    ib_expiries = st.number_input("Expiries to fetch", min_value=1, max_value=12, value=4, step=1)
    ib_strikes  = st.number_input("Strikes around ATM", min_value=5, max_value=100, value=30, step=5)

    if st.button("⟳  Fetch Corn Data", use_container_width=True, type="primary"):
        from ingestion.ib_options import fetch_all_corn_data
        with st.spinner("Connecting to TWS and fetching ZC data…"):
            try:
                results = fetch_all_corn_data(
                    port=int(ib_port),
                    max_expiries=int(ib_expiries),
                    max_strikes=int(ib_strikes),
                )
                if not results:
                    st.error("No data returned — is TWS running with API enabled?")
                else:
                    st.cache_data.clear()
                    parts = []
                    if "futures" in results:
                        parts.append(f"{len(results['futures'])} futures bars")
                    if "options" in results:
                        parts.append(f"{len(results['options'])} option rows")
                    st.success("Fetched: " + ", ".join(parts))
            except Exception as e:
                st.error(f"TWS error: {e}")

    st.divider()
    parquet_count = len(list(DATA_RAW_DIR.glob("*.parquet"))) if DATA_RAW_DIR.exists() else 0
    st.metric("Datasets on disk", parquet_count)
    if parquet_count == 0:
        st.warning("No data yet. Click **Fetch Corn Data** above.")

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_futures, tab_options, tab_raw = st.tabs(["📊 Futures", "🎯 Options Chain", "🗃 Raw Data"])

# ── FUTURES TAB ───────────────────────────────────────────────────────────────
with tab_futures:
    fut = load_futures()
    if fut.empty:
        st.info("No futures data yet. Click **Fetch Corn Data** in the sidebar.")
    else:
        contract_label = fut["ticker"].iloc[0] if "ticker" in fut.columns else "ZC"

        last = fut["Close"].iloc[-1]
        prev = fut["Close"].iloc[-2]
        chg  = last - prev
        pct  = chg / prev * 100

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Last Close",   f"{last:,.2f} USX/bu", f"{chg:+.2f} ({pct:+.2f}%)")
        k2.metric("≈ USD/bu",     f"${last/100:,.3f}")
        k3.metric(f"{len(fut)}d High", f"{fut['High'].max():,.2f}")
        k4.metric(f"{len(fut)}d Low",  f"{fut['Low'].min():,.2f}")

        st.caption("Prices in US cents per bushel (USX/bu). Divide by 100 for USD.")
        st.plotly_chart(candlestick(fut, f"ZC Corn Futures — {contract_label}"), use_container_width=True)

        with st.expander("OHLCV Table"):
            disp = fut[["Open","High","Low","Close","Volume"]].copy()
            disp.index = disp.index.strftime("%Y-%m-%d")
            st.dataframe(disp.sort_index(ascending=False), use_container_width=True)

# ── OPTIONS TAB ───────────────────────────────────────────────────────────────
with tab_options:
    opt_names = available_options_files()
    if not opt_names:
        st.info("No options data yet. Click **Fetch Corn Data** in the sidebar.")
    else:
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            opt_name = st.selectbox("Dataset", opt_names)
        opt_df = load_options(opt_name)

        expiries = sorted(opt_df["expiry"].unique()) if not opt_df.empty else []
        with col2:
            sel_expiry = st.selectbox("Expiry", expiries)
        with col3:
            show = st.radio("Show", ["Both", "Calls", "Puts"], horizontal=True)

        if not opt_df.empty and sel_expiry:
            chain = opt_df[opt_df["expiry"] == sel_expiry].copy()
            if show == "Calls":
                chain = chain[chain["option_type"] == "call"]
            elif show == "Puts":
                chain = chain[chain["option_type"] == "put"]

            n_calls = (chain["option_type"] == "call").sum()
            n_puts  = (chain["option_type"] == "put").sum()
            otm_iv  = opt_df[
                (opt_df["expiry"] == sel_expiry) & (~opt_df.get("iv_suspect", pd.Series(False)))
            ]["implied_volatility"]
            median_iv = otm_iv.median() * 100 if not otm_iv.empty else float("nan")

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Calls",         n_calls)
            k2.metric("Puts",          n_puts)
            k3.metric("Median IV",     f"{median_iv:.1f}%" if not pd.isna(median_iv) else "—")
            k4.metric("Total strikes", len(chain))

            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(iv_smile(opt_df, sel_expiry), use_container_width=True)
            with c2:
                st.plotly_chart(oi_chart(opt_df, sel_expiry), use_container_width=True)

            g = greeks_chart(opt_df, sel_expiry)
            if g:
                st.plotly_chart(g, use_container_width=True)

            # Strike ladder
            st.subheader("Strike Ladder")
            has_greeks = "delta" in chain.columns
            base_cols = ["strike","bid","ask","last_price","implied_volatility","open_interest","iv_suspect"]
            greek_cols = ["delta","gamma","theta","vega"] if has_greeks else []

            def side_df(opt_type: str, prefix: str) -> pd.DataFrame:
                cols = [c for c in base_cols + greek_cols if c in chain.columns]
                rename = {
                    "bid": f"{prefix}_bid", "ask": f"{prefix}_ask",
                    "last_price": f"{prefix}_last", "implied_volatility": f"{prefix}_iv",
                    "open_interest": f"{prefix}_oi", "iv_suspect": f"{prefix}_iv?",
                    "delta": f"{prefix}_Δ", "gamma": f"{prefix}_Γ",
                    "theta": f"{prefix}_Θ", "vega":  f"{prefix}_ν",
                }
                return (
                    chain[chain["option_type"] == opt_type][cols]
                    .sort_values("strike")
                    .rename(columns=rename)
                    .set_index("strike")
                )

            ladder = side_df("call", "call").join(side_df("put", "put"), how="outer").reset_index()
            for col in [c for c in ["call_iv","put_iv"] if c in ladder.columns]:
                ladder[col] = (ladder[col] * 100).round(2).astype(str) + "%"

            col_cfg = {
                "strike":   st.column_config.NumberColumn("Strike", format="%.2f"),
                "call_bid": st.column_config.NumberColumn("Call Bid",  format="%.2f"),
                "call_ask": st.column_config.NumberColumn("Call Ask",  format="%.2f"),
                "call_last":st.column_config.NumberColumn("Call Last", format="%.2f"),
                "call_oi":  st.column_config.NumberColumn("Call OI"),
                "call_iv?": st.column_config.CheckboxColumn("C IV?"),
                "call_Δ":   st.column_config.NumberColumn("Call Δ",  format="%.3f"),
                "call_Γ":   st.column_config.NumberColumn("Call Γ",  format="%.4f"),
                "call_Θ":   st.column_config.NumberColumn("Call Θ",  format="%.3f"),
                "call_ν":   st.column_config.NumberColumn("Call ν",  format="%.3f"),
                "put_bid":  st.column_config.NumberColumn("Put Bid",   format="%.2f"),
                "put_ask":  st.column_config.NumberColumn("Put Ask",   format="%.2f"),
                "put_last": st.column_config.NumberColumn("Put Last",  format="%.2f"),
                "put_oi":   st.column_config.NumberColumn("Put OI"),
                "put_iv?":  st.column_config.CheckboxColumn("P IV?"),
                "put_Δ":    st.column_config.NumberColumn("Put Δ",   format="%.3f"),
                "put_Γ":    st.column_config.NumberColumn("Put Γ",   format="%.4f"),
                "put_Θ":    st.column_config.NumberColumn("Put Θ",   format="%.3f"),
                "put_ν":    st.column_config.NumberColumn("Put ν",   format="%.3f"),
            }
            st.dataframe(ladder, use_container_width=True, height=440, column_config=col_cfg)

# ── RAW DATA TAB ──────────────────────────────────────────────────────────────
with tab_raw:
    if parquet_count == 0:
        st.info("No data files found.")
    else:
        files = sorted(DATA_RAW_DIR.glob("*.parquet"))
        sel_file = st.selectbox("Dataset", [f.name for f in files])
        raw_df = pd.read_parquet(DATA_RAW_DIR / sel_file)
        st.caption(f"{len(raw_df):,} rows × {len(raw_df.columns)} columns")

        col1, col2 = st.columns([3, 1])
        with col1:
            search = st.text_input("Filter (substring across all string columns)", "")
        with col2:
            max_rows = st.number_input("Max rows", 50, 5000, 200, step=50)

        if search:
            mask = raw_df.apply(lambda c: c.astype(str).str.contains(search, case=False, na=False)).any(axis=1)
            raw_df = raw_df[mask]

        st.dataframe(raw_df.head(max_rows), use_container_width=True, height=520)
        st.download_button(
            "⬇ Download CSV",
            raw_df.to_csv(index=True).encode(),
            file_name=sel_file.replace(".parquet", ".csv"),
            mime="text/csv",
        )
