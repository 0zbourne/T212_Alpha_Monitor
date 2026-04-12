import json
import time
from pathlib import Path

# Try to import streamlit for caching, fallback to a simple decorator
try:
    import streamlit as st
    cache_data = st.cache_data
except ImportError:
    def cache_data(ttl=None):
        return lambda f: f
    st = None

CURRENCY_CACHE_PATH = Path("data") / "currency_cache.json"

def _load_currency_cache() -> dict:
    if CURRENCY_CACHE_PATH.exists():
        try:
            return json.loads(CURRENCY_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_currency_cache(data: dict):
    CURRENCY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURRENCY_CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

def infer_yf_symbol(t212_ticker: str) -> str | None:
    """Infers the yfinance ticker symbol from a Trading 212 ticker."""
    t = (t212_ticker or "").strip().upper()
    if "_US_" in t:
        return t.split("_")[0]
    core = t.replace("_GBX", "").replace("_GB", "").replace("_EQ", "").split("_")[0]
    if core.endswith("L") and len(core) >= 4:
        core = core[:-1]
    if core and core.isalpha() and 1 <= len(core) <= 5:
        return f"{core}.L"
    return None

@cache_data(ttl=24 * 3600)
def get_ticker_currency(ysym: str) -> str:
    """Detects the currency for a given yfinance symbol with caching."""
    if not ysym:
        return "USD"
    
    cache = _load_currency_cache()
    if ysym in cache:
        return cache[ysym]
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(ysym)
        info = ticker.info or {}
        raw_ccy = str(info.get("currency", "")).upper().strip()
        
        if raw_ccy in ("GBX", "GBP", "GBPOUND", "PENCE", "PENNY", "GB PENCE"):
            result = "GBX"
        elif raw_ccy == "USD":
            result = "USD"
        elif raw_ccy == "EUR":
            result = "EUR"
        else:
            result = raw_ccy or ("GBX" if ysym.endswith(".L") else "USD")
            
        cache[ysym] = result
        _save_currency_cache(cache)
        return result
    except Exception:
        return "GBX" if ysym.endswith(".L") else "USD"

def convert_to_gbp(price: float, currency: str, usd_to_gbp_rate: float = 1.0) -> float:
    """Converts a price to GBP based on its currency code."""
    if currency == "GBX":
        return price / 100.0  # Pence to Pounds
    if currency == "USD":
        return price * usd_to_gbp_rate
    if currency == "EUR":
        return price * usd_to_gbp_rate * 0.85 # Approximation
    return price # Assume GBP
