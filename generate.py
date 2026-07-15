"""Generate correlation / beta / volatility data for the static site.

Reads the asset list and time horizons from ``public/config/`` and writes one
JSON file per view into ``public/data/`` (the frontend fetches these directly).

Design notes
------------
* Rolling correlations are computed **once per horizon** and reused for both the
  pairwise and the "1 vs all" views (the original recomputed them several times).
* Pairwise files no longer embed the raw price series — the frontend never used
  them, and they were the bulk of the ~1 MB-per-file payload.
* Output is a build artifact: nothing here should ever be committed to git.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timedelta
from itertools import combinations

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "public", "config")
DATA_DIR = os.path.join(ROOT, "public", "data")

# Base asset used for beta and for the "1 vs all" correlation view.
BETA_BASE = "BTC-USD"
ONE_VS_ALL_ASSETS = ["BTC-USD", "ETH-USD"]

YEARS_OF_HISTORY = 5
TRADING_DAYS = 252


def load_config():
    with open(os.path.join(CONFIG_DIR, "assets.json")) as f:
        assets = json.load(f)  # ticker -> display name
    with open(os.path.join(CONFIG_DIR, "time_horizons.json")) as f:
        horizons = json.load(f)  # day-count (str) -> display name
    return assets, horizons


def download_prices(tickers, start, end, max_retries=3, delay=10):
    """Download daily closing prices; returns a DataFrame (one column per ticker)."""
    data = pd.DataFrame()
    for ticker in tickers:
        for attempt in range(max_retries):
            try:
                print(f"Downloading {ticker}...")
                closes = yf.download(ticker, start=start, end=end, progress=False)["Close"]
                if not closes.empty:
                    data[ticker] = closes
                    print(f"  ok ({len(closes)} rows)")
                break
            except Exception as exc:  # noqa: BLE001 - network flakiness, retry
                if attempt == max_retries - 1:
                    print(f"  failed after {max_retries} attempts: {exc}")
                else:
                    wait = delay * (attempt + 1)
                    print(f"  attempt {attempt + 1} failed, retrying in {wait}s...")
                    time.sleep(wait)
        time.sleep(delay)  # be gentle with the API between tickers
    return data


def sanitize(value):
    """Recursively convert NaN floats to None so the JSON is valid."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def write_json(payload, filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(sanitize(payload), f)
    print(f"  wrote {filename}")


def series_dict(series):
    """A dropna'd pandas Series -> {'dates': [...], values under caller's key}."""
    valid = series.dropna()
    return valid.index.strftime("%Y-%m-%d").tolist(), valid.values.tolist()


def rolling_correlations(returns, period):
    """{(a, b): {'dates': [...], 'correlation': [...]}} for every asset pair."""
    corr = returns.rolling(window=f"{period}D", min_periods=int(period)).corr()
    out = {}
    for a, b in combinations(returns.columns, 2):
        pair = corr.xs(a, level=1)[b].dropna()
        out[(a, b)] = {
            "dates": pair.index.strftime("%Y-%m-%d").tolist(),
            "correlation": pair.values.tolist(),
        }
    return out


def rolling_beta(returns, base, period):
    window = f"{period}D"
    min_periods = int(period)
    base_var = returns[base].rolling(window=window, min_periods=min_periods).var()
    out = {}
    for asset in returns.columns:
        if asset == base:
            continue
        cov = returns[asset].rolling(window=window, min_periods=min_periods).cov(returns[base])
        dates, values = series_dict(cov / base_var)
        out[asset] = {"dates": dates, "beta": values}
    return out


def rolling_volatility(returns, period):
    window = f"{period}D"
    min_periods = int(period)
    out = {}
    for asset in returns.columns:
        vol = returns[asset].rolling(window=window, min_periods=min_periods).std() * np.sqrt(TRADING_DAYS)
        dates, values = series_dict(vol)
        out[asset] = {"dates": dates, "volatility": values}
    return out


def build(assets, horizons):
    os.makedirs(DATA_DIR, exist_ok=True)
    tickers = list(assets.keys())
    horizon_keys = list(horizons.keys())

    end = datetime.now()
    start = end - timedelta(days=YEARS_OF_HISTORY * 365)
    prices = download_prices(tickers, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    available = [t for t in tickers if t in prices.columns]
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"Warning: no data for {missing}; skipping those assets.")

    returns = prices[available].ffill().pct_change(fill_method=None)

    # Compute rolling correlations once per horizon and reuse everywhere.
    print("Computing rolling correlations...")
    corr_by_period = {p: rolling_correlations(returns, int(p)) for p in horizon_keys}

    # --- Pairwise correlation files: data/{a}_vs_{b}.json ---
    print("Writing pairwise correlation files...")
    for a, b in combinations(available, 2):
        write_json(
            {"correlations": {horizons[p]: corr_by_period[p][(a, b)] for p in horizon_keys}},
            f"{a}_vs_{b}.json",
        )

    # --- "1 vs all" files: data/{asset}_{period}_correlations.json ---
    print("Writing 1-vs-all correlation files...")
    for base in ONE_VS_ALL_ASSETS:
        if base not in available:
            continue
        for p in horizon_keys:
            correlations = {}
            for other in available:
                if other == base:
                    continue
                key = (base, other) if (base, other) in corr_by_period[p] else (other, base)
                correlations[assets[other]] = corr_by_period[p][key]
            write_json(
                {"asset": assets[base], "period": horizons[p], "correlations": correlations},
                f"{base}_{p}_correlations.json",
            )

    # --- Beta files: data/beta_BTC-USD_{period}.json ---
    if BETA_BASE in available:
        print("Writing beta files...")
        for p in horizon_keys:
            write_json(rolling_beta(returns, BETA_BASE, int(p)), f"beta_{BETA_BASE}_{p}.json")

    # --- Volatility files: data/volatility_{period}.json ---
    print("Writing volatility files...")
    for p in horizon_keys:
        write_json(rolling_volatility(returns, int(p)), f"volatility_{p}.json")

    print("Done.")


if __name__ == "__main__":
    build(*load_config())
