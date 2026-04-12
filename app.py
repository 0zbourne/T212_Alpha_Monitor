import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

# Custom utils
from utils.t212 import get_auth_headers, fetch_to_file, extract_cash_balance
from utils.currency import infer_yf_symbol, get_ticker_currency, convert_to_gbp
from jobs.fundamentals import ensure_fundamentals, load_fundamentals
from jobs.snapshot import append_today_snapshot_if_missing
from pdperf.series import read_nav, daily_returns_twr, cumulative_return
from pdperf.cashflows import build_cash_flows
from bench.sp500 import get_sp500_daily

# ---- CONFIG & SETTINGS ----
st.set_page_config(page_title="T212 Alpha Monitor", layout="wide")

# ---- SLEEK STYLING (MINIMALIST) ----
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
.stApp { background-color: #0E1117; }
h1, h2, h3 { font-weight: 600 !important; letter-spacing: -0.02em !important; }
.metric-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    transition: transform 0.2s ease, border-color 0.2s ease;
}
.metric-card:hover { transform: translateY(-2px); border-color: #00DB8B; }
.metric-label {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #8892B0;
    margin-bottom: 8px;
}
.metric-value { font-size: 1.8rem; font-weight: 600; color: #FFFFFF; }
[data-testid="stSidebar"] {
    background-color: rgba(11, 13, 17, 0.7);
    backdrop-filter: blur(12px);
    border-right: 1px solid rgba(255, 255, 255, 0.05);
}
hr { margin: 2rem 0 !important; border: 0; border-top: 1px solid rgba(255, 255, 255, 0.05) !important; }
.stProgress > div > div > div > div { background-color: #00DB8B; }
</style>
""", unsafe_allow_html=True)

def sleek_metric(label, value):
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
    """, unsafe_allow_html=True)

# Paths
DATA_DIR = Path("data")
PORTFOLIO_JSON = DATA_DIR / "portfolio.json"
TRANSACTIONS_JSON = DATA_DIR / "transactions.json"
NAV_CSV = DATA_DIR / "nav_daily.csv"
FUNDAMENTALS_JSON = DATA_DIR / "fundamentals.json"
FUND_AUDIT = DATA_DIR / "fundamentals_audit.csv"

# Env/Secrets
BASE_URL = os.getenv("T212_API_BASE", "https://live.trading212.com")

def _freshness(path: Path) -> str:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "Never"

# ---- SYNC LOGIC ----
def sync_all_data():
    """Fetch all necessary data from T212 API."""
    with st.status("Syncing with Trading 212...", expanded=True) as status:
        st.write("Updating portfolio holdings...")
        fetch_to_file(f"{BASE_URL}/api/v0/equity/portfolio", PORTFOLIO_JSON)
        
        st.write("Updating transactions history...")
        fetch_to_file(f"{BASE_URL}/api/v0/history/transactions?from=1970-01-01&to=2100-01-01", TRANSACTIONS_JSON)
        
        st.write("Updating account info...")
        fetch_to_file(f"{BASE_URL}/api/v0/equity/account/info", DATA_DIR / "account.json")
        
        st.cache_data.clear()
        status.update(label="Sync complete!", state="complete", expanded=False)

# ---- HERO SECTION ----
col1, col2 = st.columns([5, 1])
with col1:
    st.title("T212 Alpha Monitor")
    st.markdown("*An ultra-lean instrument for tracking weight-adjusted quality benchmarks and TWR-indexed performance.*")
with col2:
    if st.button("🔄 Refresh", use_container_width=True):
        sync_all_data()
        st.rerun()

# Initial sync check
if not PORTFOLIO_JSON.exists():
    st.info("No data found. Click 'Refresh Data' to sync with Trading 212.")
    st.stop()

# ---- DATA LOADING ----
@st.cache_data
def get_clean_portfolio():
    if not PORTFOLIO_JSON.exists(): return pd.DataFrame()
    data = json.loads(PORTFOLIO_JSON.read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    df.rename(columns={"ticker": "symbol", "quantity": "shares", "currentPrice": "price_raw"}, inplace=True)
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    df["price_raw"] = pd.to_numeric(df["price_raw"], errors="coerce")
    return df

portfolio = get_clean_portfolio()

# FX Rate (Frankfurter fallback)
@st.cache_data(ttl=3600)
def get_fx_rate():
    try:
        import requests
        r = requests.get("https://api.frankfurter.app/latest", params={"from": "USD", "to": "GBP"}, timeout=10)
        return float(r.json()["rates"]["GBP"])
    except:
        return 0.78 # Conservative fallback

usd_to_gbp = get_fx_rate()

# ---- CALCULATIONS ----
with st.spinner("Calculating portfolio values..."):
    # Map currencies
    currencies = {}
    for sym in portfolio["symbol"].unique():
        ysym = infer_yf_symbol(sym)
        currencies[sym] = get_ticker_currency(ysym)
    
    # Calculate GBP values
    portfolio["price_gbp"] = portfolio.apply(lambda r: convert_to_gbp(r["price_raw"], currencies.get(r["symbol"], "GBP"), usd_to_gbp), axis=1)
    portfolio["market_value_gbp"] = portfolio["shares"] * portfolio["price_gbp"]
    portfolio["total_value_gbp"] = portfolio["market_value_gbp"] # Alignment for snapshot job
    
    total_market_value = portfolio["market_value_gbp"].sum()
    
    # Cash
    acc_data = json.loads((DATA_DIR / "account.json").read_text(encoding="utf-8")) if (DATA_DIR / "account.json").exists() else {}
    cash_val, _ = extract_cash_balance(acc_data)
    cash_gbp = float(cash_val or 0.0)
    
    total_portfolio_value = total_market_value + cash_gbp

# ---- CALCULATIONS & QUALITY DATA ----
weights = {row.symbol: row.market_value_gbp / total_market_value for row in portfolio.itertuples()} if total_market_value > 0 else {}
ensure_fundamentals(weights)
fund_data = load_fundamentals()
q = (fund_data or {}).get("portfolio_weighted", {})

# ---- DASHBOARD HERO: QUALITY BENCHMARKS ----
def fmt(v, suffix="%"): return f"{v*100:.1f}{suffix}" if v and not (np.isnan(v) or np.isinf(v)) else "N/A"

q_cols = st.columns(5)
with q_cols[0]: sleek_metric("ROCE", fmt(q.get("roce")))
with q_cols[1]: sleek_metric("Gross Margin", fmt(q.get("gm")))
with q_cols[2]: sleek_metric("Op. Margin", fmt(q.get("om")))
with q_cols[3]: sleek_metric("Cash Conv.", fmt(q.get("cc")))
with q_cols[4]: 
    ic_val = q.get("ic")
    sleek_metric("Int. Cover", f"{ic_val:.1f}x" if ic_val else "N/A")

st.divider()

if FUND_AUDIT.exists():
    st.subheader("Asset Quality Audit")
    audit_df = pd.read_csv(FUND_AUDIT)
    
    # Merge with portfolio to get names if possible, else use symbol-pretty
    display_audit = audit_df[["symbol", "weight", "roce", "gm", "om", "cc", "ic"]].copy()
    
    # Scale decimals to percentages (0.85 -> 85.0) for display
    cols_to_scale = ["weight", "roce", "gm", "om", "cc"]
    for c in cols_to_scale:
        display_audit[c] = display_audit[c] * 100.0
    
    st.dataframe(
        display_audit.sort_values("weight", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "symbol": "Ticker",
            "weight": st.column_config.ProgressColumn("Allocation", format="%.1f%%", min_value=0, max_value=100),
            "roce": st.column_config.NumberColumn("ROCE", format="%.1f%%"),
            "gm": st.column_config.NumberColumn("Gross Margin", format="%.1f%%"),
            "om": st.column_config.NumberColumn("Op. Margin", format="%.1f%%"),
            "cc": st.column_config.NumberColumn("Cash Conv.", format="%.1f%%"),
            "ic": st.column_config.NumberColumn("Int. Cover", format="%.1fx")
        }
    )
    st.divider()

# ---- PERFORMANCE VS S&P 500 ----
st.subheader("Performance Comparison (vs S&P 500)")
try:
    # Update snapshot for benchmarking
    append_today_snapshot_if_missing(portfolio)
    
    nav_data = read_nav()
    flow_data = build_cash_flows(TRANSACTIONS_JSON)
    port_daily = daily_returns_twr(nav_data, flow_data)
    
    start_date = pd.to_datetime(nav_data.index).min().strftime("%Y-%m-%d")
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sp500 = get_sp500_daily(start_date, end_date)
    
    # Merge and compare
    port_daily["date"] = pd.to_datetime(port_daily["date"]).dt.date
    sp500["date"] = pd.to_datetime(sp500["date"]).dt.date
    comparison = port_daily.merge(sp500[["date", "daily_ret"]].rename(columns={"daily_ret": "r_bench"}), on="date", how="inner")
    
    if not comparison.empty:
        comparison["Portfolio (TWR)"] = (100.0 * (1.0 + comparison["r_port"]).cumprod())
        comparison["S&P 500 (GBP)"] = (100.0 * (1.0 + comparison["r_bench"]).cumprod())
        
        plot_df = comparison.melt(id_vars=["date"], value_vars=["Portfolio (TWR)", "S&P 500 (GBP)"], var_name="Series", value_name="Index")
        
        line_chart = alt.Chart(plot_df).mark_line(strokeWidth=2.5, interpolate='monotone').encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(grid=False, labelColor="#8892B0")),
            y=alt.Y("Index:Q", title=None, scale=alt.Scale(zero=False), axis=alt.Axis(grid=True, gridColor="rgba(255,255,255,0.05)", labelColor="#8892B0")),
            color=alt.Color("Series:N", 
                scale=alt.Scale(domain=["Portfolio (TWR)", "S&P 500 (GBP)"], range=["#00DB8B", "#8892B0"]),
                legend=alt.Legend(orient="top", title=None, labelColor="#FFFFFF", labelFontSize=12, symbolType="circle")
            ),
            tooltip=["date:T", "Series:N", alt.Tooltip("Index:Q", format=".2f")]
        ).properties(height=400).configure_view(strokeOpacity=0)
        
        st.altair_chart(line_chart, use_container_width=True)
    else:
        st.info("Insufficient historical data for performance comparison.")
except Exception as e:
    st.error(f"Performance chart error: {e}")

# ---- FOOTER EXTRAS ----
with st.expander("Quality Audit (Per Ticker)"):
    if FUND_AUDIT.exists():
        st.dataframe(pd.read_csv(FUND_AUDIT), hide_index=True, use_container_width=True)
    else:
        st.write("Audit data pending.")

st.sidebar.title("Settings")
if st.sidebar.button("Force Global Refresh"):
    st.cache_data.clear()
    sync_all_data()
    st.rerun()

with st.sidebar.expander("Advanced: NAV Backfill Tool"):
    st.caption("Reconstruct historical NAV from all past order data.")
    bf_date = st.text_input("Start Date", "2025-01-01")
    if st.button("Trigger Backfill"):
        from jobs.backfill import backfill_nav_from_orders
        try:
            path = backfill_nav_from_orders(start=bf_date)
            st.success(f"Backfill successful: {path}")
        except Exception as e:
            st.error(f"Backfill failed: {e}")
