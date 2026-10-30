"""Task 4: fetch the newest hourly bars from the API, preprocess them the same
way as the notebook, load the saved model, and forecast the next-hour close.

Run from the repository root (the API must be running):
    python src/predict.py                       # MySQL endpoints, BTCUSD
    python src/predict.py --source mongo        # MongoDB endpoints
"""
import argparse
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.base import BaseEstimator, RegressorMixin

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "model" / "persistence_model.pkl"
FEATURE_ORDER_PATH = ROOT / "model" / "feature_order.pkl"
MAX_FILL_HOURS = 2  # same rule as the notebook: fill gaps of at most 2 hours


class PersistenceRegressor(BaseEstimator, RegressorMixin):
    """Same class as in notebook/eda.ipynb. It must exist here so the saved
    pickle can be loaded. The forecast is the current close (column 0)."""

    def fit(self, X, y=None):
        values = np.asarray(X)
        if values.ndim != 2 or values.shape[1] < 1:
            raise ValueError("Expected a 2-D matrix with the close in column 0.")
        self.n_features_in_ = values.shape[1]
        return self

    def predict(self, X):
        values = np.asarray(X, dtype=float)
        if values.ndim == 1:
            return values
        if values.ndim != 2 or values.shape[1] < 1:
            raise ValueError("Expected a 2-D matrix with the close in column 0.")
        return values[:, 0]


class _Unpickler(pickle.Unpickler):
    """The notebook pickled the class under __main__, so point it to this file."""

    def find_class(self, module, name):
        if name == "PersistenceRegressor":
            return PersistenceRegressor
        return super().find_class(module, name)


def fetch_bars(base_url, source, symbol, hours):
    """Step 1: fetch the latest bar, then the bars of the previous `hours` hours."""
    prefix = f"{base_url}/api/{source}/bars"
    latest = requests.get(f"{prefix}/latest", params={"symbol": symbol}, timeout=15)
    latest.raise_for_status()
    latest_bar = latest.json()

    end = datetime.fromisoformat(latest_bar["timestamp"])
    start = end - timedelta(hours=hours)
    window = requests.get(
        f"{prefix}",
        params={"symbol": symbol, "start": start.isoformat(), "end": end.isoformat()},
        timeout=15,
    )
    window.raise_for_status()
    return latest_bar, window.json()


def preprocess(bars):
    """Step 2: same cleaning as Task 1: UTC hourly index, numeric types,
    short gaps filled with the previous close, longer gaps left missing."""
    frame = pd.DataFrame(bars)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    price_cols = ["open_price", "high_price", "low_price", "close_price", "volume"]
    frame[price_cols] = frame[price_cols].astype(float)
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    frame = frame.rename(columns={"close_price": "close"})

    hourly = frame.asfreq("h")  # exposes missing hours as NaN rows
    missing = hourly["close"].isna()
    run_id = (missing != missing.shift()).cumsum()
    run_length = missing.groupby(run_id).transform("sum")
    fill_mask = missing & (run_length <= MAX_FILL_HOURS)
    hourly.loc[fill_mask, "close"] = hourly["close"].ffill()[fill_mask]
    return hourly


def build_features(hourly, feature_order):
    """Take the newest hour that has a close and arrange columns as the model expects."""
    usable = hourly.dropna(subset=["close"])
    if usable.empty:
        raise ValueError("No usable close price in the fetched window.")
    row = usable.iloc[[-1]]
    return row, row[feature_order].to_numpy(dtype=float)


def main():
    parser = argparse.ArgumentParser(description="Forecast the next-hour close.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--source", choices=["mysql", "mongo"], default="mysql")
    parser.add_argument("--symbol", default="BTCUSD")
    parser.add_argument("--hours", type=int, default=24, help="hours of history to fetch")
    args = parser.parse_args()

    try:
        latest_bar, bars = fetch_bars(args.url, args.source, args.symbol, args.hours)
    except requests.RequestException as exc:
        sys.exit(f"Could not reach the API at {args.url}. Is Docker running? ({exc})")
    print(f"[1] Fetched {len(bars)} bars from {args.source}; latest: {latest_bar['timestamp']}")

    hourly = preprocess(bars)
    print(f"[2] Preprocessed to {len(hourly)} hourly rows "
          f"({int(hourly['close'].isna().sum())} hours still missing)")

    with FEATURE_ORDER_PATH.open("rb") as f:
        feature_order = pickle.load(f)
    with MODEL_PATH.open("rb") as f:
        model = _Unpickler(f).load()
    print(f"[3] Loaded model {type(model).__name__} with features {feature_order}")

    row, features = build_features(hourly, feature_order)
    prediction = float(model.predict(features)[0])
    current_time = row.index[0]
    print(f"[4] Forecast for {args.symbol} at {current_time + pd.Timedelta(hours=1)} UTC: "
          f"${prediction:,.2f}  (current close ${float(row['close'].iloc[0]):,.2f})")
    if int(row["minute_count"].iloc[0]) < 60:
        print(f"    Note: the latest bar is a partial hour "
              f"({int(row['minute_count'].iloc[0])} minutes of trades).")


if __name__ == "__main__":
    main()