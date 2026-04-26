from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

DATA_DIR = Path("data")
NAV_CSV = DATA_DIR / "nav_daily.csv"

def _anchor_date_iso():
    """UTC date; if Saturday/Sunday roll back to Friday."""
    d = datetime.utcnow().date()
    if d.weekday() == 5:  # Sat
        d = d - timedelta(days=1)
    elif d.weekday() == 6:  # Sun
        d = d - timedelta(days=2)
    return d.isoformat()

def append_today_snapshot_if_missing(df, q_metrics: dict = None, path: Path = NAV_CSV):
    """
    Append/update today's NAV (GBP) and quality metrics to data/nav_daily.csv.
    Uses df['total_value_gbp'] column already computed in app.py.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_key = _anchor_date_iso()
    nav = float(pd.to_numeric(df["total_value_gbp"], errors="coerce").sum())

    if path.exists():
        nav_df = pd.read_csv(path, parse_dates=["date"])
        nav_df["date"] = nav_df["date"].dt.date.astype(str)
    else:
        nav_df = pd.DataFrame(columns=["date", "nav_gbp"])

    # Ensure quality columns exist
    for col in ["roce", "gm", "om", "cc", "ic", "fcf_yield"]:
        if col not in nav_df.columns:
            nav_df[col] = float("nan")

    q = q_metrics or {}
    new_data = {
        "nav_gbp": nav,
        "roce": q.get("roce"),
        "gm": q.get("gm"),
        "om": q.get("om"),
        "cc": q.get("cc"),
        "ic": q.get("ic"),
        "fcf_yield": q.get("fcf_yield")
    }

    if (nav_df["date"] == date_key).any():
        for k, v in new_data.items():
            if v is not None:
                nav_df.loc[nav_df["date"] == date_key, k] = float(v)
            else:
                if k not in nav_df.columns:
                    nav_df.loc[nav_df["date"] == date_key, k] = float("nan")
    else:
        new_row = {"date": date_key}
        new_row.update({k: (float(v) if v is not None else float("nan")) for k, v in new_data.items()})
        nav_df = pd.concat(
            [nav_df, pd.DataFrame([new_row])],
            ignore_index=True
        )

    nav_df = nav_df.sort_values("date")
    nav_df.to_csv(path, index=False)
    return nav_df
