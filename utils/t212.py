import os
import json
import base64
import time
import requests
from pathlib import Path

# Try to import streamlit for secrets, fallback to None
try:
    import streamlit as st
except ImportError:
    st = None

def get_auth_headers() -> dict:
    """
    Get Trading 212 authentication headers.
    Supports Basic (KEY:SECRET) and Apikey (Apikey KEY).
    Reads from environment variables and streamlit secrets.
    """
    # Try environment variables first
    key = os.getenv("T212_API_KEY", "").strip()
    secret = os.getenv("T212_API_SECRET", "").strip()

    # Try Streamlit secrets if not in environment
    if st and not key:
        try:
            key = str(st.secrets.get("T212_API_KEY", "")).strip()
            secret = str(st.secrets.get("T212_API_SECRET", "")).strip()
        except Exception:
            pass

    if key and secret:
        token = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}

    if key:
        if key.lower().startswith("apikey "):
            return {"Authorization": key, "Accept": "application/json"}
        return {"Authorization": f"Apikey {key}", "Accept": "application/json"}

    return {}

def paged_get(url: str, base_url: str = "https://live.trading212.com") -> list:
    """Perform a paged GET request to the Trading 212 API."""
    items = []
    next_url = url
    headers = get_auth_headers()
    
    for _ in range(100): # Safety limit
        r = requests.get(next_url, headers=headers, timeout=20)
        
        # Handle rate limiting
        if r.status_code == 429:
            time.sleep(60)
            continue
            
        r.raise_for_status()
        payload = r.json()
        
        chunk = payload.get("items", payload if isinstance(payload, list) else [])
        if isinstance(chunk, list):
            items.extend(chunk)
            
        next_path = payload.get("nextPagePath")
        if not next_path:
            break
            
        next_url = base_url.rstrip("/") + next_path
        time.sleep(1.0) # Respectful delay
        
    return items

def fetch_to_file(url: str, out_path: Path, timeout: int = 20):
    """Fetch JSON from URL and cache to file. Returns data or None."""
    headers = get_auth_headers()
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    except Exception:
        if out_path.exists():
            try:
                return json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None

def extract_cash_balance(obj) -> tuple[float | None, str | None]:
    """
    Recursively extract cash balance from T212 JSON response.
    Returns (amount, path_found).
    """
    preferred = {
        "free", "freecash", "free_funds",
        "availablecash", "available_funds",
        "cashbalance", "cash_balance", "available"
    }
    deny = {"id", "total", "invested", "ppl", "result", "blocked"}
    found = []

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                lk = str(k).lower()
                if "piecash" in lk or lk in deny:
                    continue
                newp = f"{path}.{k}" if path else k
                if isinstance(v, (dict, list)):
                    walk(v, newp)
                else:
                    last = newp.split(".")[-1].lower()
                    if last in preferred:
                        try:
                            fv = float(v)
                            if fv >= 0:
                                found.append((newp, fv))
                        except Exception:
                            pass
        elif isinstance(o, list):
            for i, it in enumerate(o):
                walk(it, f"{path}[{i}]")

    walk(obj)
    if found:
        return found[0][1], found[0][0]
    return None, None
