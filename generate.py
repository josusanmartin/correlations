"""Build the site's single data file: ``public/data/prices.json``.

The refactored architecture ships *raw aligned prices once* and computes every
metric (correlation, beta, volatility, the whole matrix) in the browser. So this
script does one job — download prices, align them to a common business-day
calendar, and dump a compact JSON. No correlation math happens here anymore.

Output shape::

    {
      "generated": "2026-07-15",
      "assets":   {"BTC-USD": "BTCUSD", ...},   # ticker -> display name
      "dates":    ["2021-07-19", ...],           # business days, ascending
      "prices":   {"BTC-USD": [30123.5, ...]}    # aligned to `dates`, null before listing
    }

The result is a build artifact — it is git-ignored and must never be committed
(committing regenerated data daily is what bloated the old history to ~20 GB).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "public", "config")
DATA_DIR = os.path.join(ROOT, "public", "data")

YEARS_OF_HISTORY = 5
SIG_FIGS = 6  # price precision kept in the JSON (returns stay accurate to ~1e-4)


def load_assets():
    with open(os.path.join(CONFIG_DIR, "assets.json")) as f:
        return json.load(f)  # ticker -> display name


def download_close(ticker, start, end, max_retries=3, delay=8):
    """Return a Series of adjusted closes for one ticker (empty on failure)."""
    for attempt in range(max_retries):
        try:
            print(f"Downloading {ticker}...")
            df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
            close = df["Close"]
            if isinstance(close, pd.DataFrame):  # newer yfinance returns MultiIndex columns
                close = close.iloc[:, 0]
            if not close.empty:
                print(f"  ok ({len(close)} rows)")
                return close
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry
            if attempt == max_retries - 1:
                print(f"  failed after {max_retries} attempts: {exc}")
            else:
                time.sleep(delay * (attempt + 1))
    return pd.Series(dtype="float64")


def build_price_frame(assets, start, end):
    """Download every ticker and align to a common business-day calendar."""
    columns = {}
    for ticker in assets:
        series = download_close(ticker, start, end)
        if not series.empty:
            series.index = pd.to_datetime(series.index)
            columns[ticker] = series
        else:
            print(f"Warning: no data for {ticker}; it will be omitted.")
        time.sleep(1)  # be gentle with the API

    frame = pd.DataFrame(columns).sort_index()
    business_days = pd.bdate_range(frame.index.min(), frame.index.max())
    # Reindex onto business days, carrying the last known close (drops weekend
    # crypto prints so crypto and equities share one trading calendar).
    return frame.reindex(frame.index.union(business_days)).sort_index().ffill().reindex(business_days)


def round_sig(x, figs=SIG_FIGS):
    if pd.isna(x):
        return None
    return float(f"{x:.{figs}g}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    assets = load_assets()

    end = datetime.now()
    start = end - timedelta(days=YEARS_OF_HISTORY * 365)
    frame = build_price_frame(assets, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    present = [t for t in assets if t in frame.columns]
    payload = {
        "generated": end.strftime("%Y-%m-%d"),
        "assets": {t: assets[t] for t in present},
        "dates": frame.index.strftime("%Y-%m-%d").tolist(),
        "prices": {t: [round_sig(v) for v in frame[t]] for t in present},
    }

    out = os.path.join(DATA_DIR, "prices.json")
    with open(out, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    size_mb = os.path.getsize(out) / 1e6
    print(f"\nWrote {out}: {len(present)} assets x {len(payload['dates'])} days ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
