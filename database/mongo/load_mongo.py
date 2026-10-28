#!/usr/bin/env python3
"""
load_mongo.py
=============
Loads cleaned hourly cryptocurrency candlestick bars and outage records
from database/data/ into MongoDB.

Usage:
    python database/mongo/load_mongo.py
    # Or to drop and recreate collections:
    python database/mongo/load_mongo.py --drop

Design Principles:
    - Reads only from database/data/ (zero interaction with data/).
    - Timestamps converted to native Python datetime (UTC) -> BSON Date (ISODate).
    - Creates compound unique index on {symbol: 1, timestamp: 1} and secondary on {timestamp: 1}.
    - Idempotent bulk upserts (UpdateOne with upsert=True) in 5,000 document batches.
    - Configurable connection via MONGO_URI and MONGO_DB environment variables.
    - Validates expected counts: 32,961 hourly bars and 54 data gaps.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError


# -----------------------------------------------------------------------------
# Configuration & Paths (Relative to Repository Root)
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_DATA_DIR = REPO_ROOT / "database" / "data"

HOURLY_BARS_CSV = INPUT_DATA_DIR / "hourly_bars.csv"
DATA_GAPS_CSV = INPUT_DATA_DIR / "data_gaps.csv"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = os.getenv("MONGO_DB", "crypto_pipeline")

BATCH_SIZE = 5000
EXPECTED_TOTAL_BARS = 32961
EXPECTED_BARS_PER_COIN = 10987
EXPECTED_TOTAL_GAPS = 54
EXPECTED_GAPS_PER_COIN = 18


def get_mongo_client() -> MongoClient:
    """Establish and verify MongoDB connection."""
    print(f"[1/4] Connecting to MongoDB at '{MONGO_URI}'...")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Force a server round-trip to verify connection
        client.admin.command("ping")
        server_info = client.server_info()
        print(f"      [OK] Connected to MongoDB v{server_info.get('version', 'unknown')}!")
        return client
    except PyMongoError as e:
        print(f"[ERROR] Failed to connect to MongoDB: {e}", file=sys.stderr)
        print("        Ensure MongoDB service is running on localhost:27017.", file=sys.stderr)
        sys.exit(1)


def setup_indexes(db, drop_existing: bool = False) -> None:
    """Create collections and enforce unique and secondary indexes."""
    print(f"\n[2/4] Setting up collections and indexes in '{MONGO_DB}'...")
    
    if drop_existing:
        print("      Flag --drop detected: Dropping existing collections...")
        db.hourly_bars.drop()
        db.data_gaps.drop()

    # 1. hourly_bars indexes
    print("      Creating indexes on 'hourly_bars'...")
    # Compound unique index: prevents duplicate bars per coin/hour and speeds up range queries
    db.hourly_bars.create_index(
        [("symbol", 1), ("timestamp", 1)],
        unique=True,
        name="uq_symbol_timestamp"
    )
    # Secondary index: optimizes cross-symbol time queries
    db.hourly_bars.create_index(
        [("timestamp", 1)],
        name="idx_timestamp"
    )

    # 2. data_gaps index
    print("      Creating unique index on 'data_gaps'...")
    db.data_gaps.create_index(
        [("symbol", 1), ("gap_start", 1)],
        unique=True,
        name="uq_symbol_gap_start"
    )
    print("      [OK] Indexes ready.")


def load_hourly_bars(db) -> None:
    """Read hourly_bars.csv, parse UTC timestamps, and bulk upsert into MongoDB."""
    if not HOURLY_BARS_CSV.exists():
        raise FileNotFoundError(
            f"Missing file: {HOURLY_BARS_CSV}. Please run database/sql/load_mysql.py first to export it."
        )

    print(f"\n[3/4] Ingesting hourly candlestick bars from {HOURLY_BARS_CSV.name}...")
    df = pd.read_csv(HOURLY_BARS_CSV)

    # Convert timestamps to Python datetime objects in UTC (becomes native BSON ISODate)
    # Using format="mixed" to accurately parse the exported ISO format strings
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.to_pydatetime()

    total_rows = len(df)
    now_utc = datetime.now(timezone.utc)
    print(f"      Parsed {total_rows:,} rows. Starting bulk upserts (batch size: {BATCH_SIZE})...")

    collection = db.hourly_bars
    operations: List[UpdateOne] = []
    upserted_count = 0
    modified_count = 0

    for idx, row in df.iterrows():
        doc = {
            "symbol": str(row["symbol"]),
            "timestamp": row["timestamp"],
            "open_price": round(float(row["open_price"]), 4),
            "high_price": round(float(row["high_price"]), 4),
            "low_price": round(float(row["low_price"]), 4),
            "close_price": round(float(row["close_price"]), 4),
            "volume": round(float(row["volume"]), 8),
            "minute_count": int(row["minute_count"]),
            "created_at": now_utc
        }

        # Idempotent upsert matching on natural business key (symbol + timestamp)
        operations.append(
            UpdateOne(
                filter={"symbol": doc["symbol"], "timestamp": doc["timestamp"]},
                update={"$set": doc},
                upsert=True
            )
        )

        if len(operations) >= BATCH_SIZE:
            result = collection.bulk_write(operations, ordered=False)
            upserted_count += result.upserted_count
            modified_count += result.modified_count
            operations.clear()
            print(f"      Processed {min(idx + 1, total_rows):,} of {total_rows:,} bars...")

    if operations:
        result = collection.bulk_write(operations, ordered=False)
        upserted_count += result.upserted_count
        modified_count += result.modified_count
        operations.clear()

    print(f"      [OK] hourly_bars load complete: {upserted_count} inserted, {modified_count} updated.")


def load_data_gaps(db) -> None:
    """Read data_gaps.csv, parse UTC dates, and bulk upsert into MongoDB."""
    if not DATA_GAPS_CSV.exists():
        raise FileNotFoundError(f"Missing file: {DATA_GAPS_CSV}.")

    print(f"\n[4/4] Ingesting exchange outage records from {DATA_GAPS_CSV.name}...")
    df = pd.read_csv(DATA_GAPS_CSV)

    df["gap_start"] = pd.to_datetime(df["gap_start"], utc=True).dt.to_pydatetime()
    df["gap_end"] = pd.to_datetime(df["gap_end"], utc=True).dt.to_pydatetime()

    now_utc = datetime.now(timezone.utc)
    collection = db.data_gaps
    operations: List[UpdateOne] = []

    for _, row in df.iterrows():
        doc = {
            "symbol": str(row["symbol"]),
            "gap_start": row["gap_start"],
            "gap_end": row["gap_end"],
            "duration_hours": int(row["duration_hours"]),
            "notes": str(row["notes"]),
            "created_at": now_utc
        }
        operations.append(
            UpdateOne(
                filter={"symbol": doc["symbol"], "gap_start": doc["gap_start"]},
                update={"$set": doc},
                upsert=True
            )
        )

    if operations:
        collection.bulk_write(operations, ordered=False)

    print(f"      [OK] data_gaps load complete ({len(operations)} records).")


def verify_database(db) -> None:
    """Verify document counts and per-symbol distribution against Task 1 baseline."""
    print("\n" + "=" * 65)
    print("MONGODB VERIFICATION SUMMARY")
    print("=" * 65)

    # 1. Check hourly_bars per symbol
    bars_pipeline = [
        {
            "$group": {
                "_id": "$symbol",
                "total_bars": {"$sum": 1},
                "earliest_bar": {"$min": "$timestamp"},
                "latest_bar": {"$max": "$timestamp"}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    bars_summary = list(db.hourly_bars.aggregate(bars_pipeline))
    total_bars_found = sum(item["total_bars"] for item in bars_summary)

    for item in bars_summary:
        print(
            f"Symbol {item['_id']}: {item['total_bars']:,} bars "
            f"({item['earliest_bar'].strftime('%Y-%m-%d %H:%M')} to {item['latest_bar'].strftime('%Y-%m-%d %H:%M')})"
        )

    # 2. Check data_gaps per symbol
    gaps_pipeline = [
        {
            "$group": {
                "_id": "$symbol",
                "total_gaps": {"$sum": 1},
                "total_empty_hours": {"$sum": "$duration_hours"}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    gaps_summary = list(db.data_gaps.aggregate(gaps_pipeline))
    total_gaps_found = sum(item["total_gaps"] for item in gaps_summary)

    print("-" * 65)
    for item in gaps_summary:
        print(f"Outages {item['_id']}: {item['total_gaps']} gaps, {item['total_empty_hours']} total empty hours")

    print("=" * 65)
    print(f"Total hourly_bars documents: {total_bars_found:,} (Expected: {EXPECTED_TOTAL_BARS:,})")
    print(f"Total data_gaps documents:   {total_gaps_found:,} (Expected: {EXPECTED_TOTAL_GAPS:,})")
    print("=" * 65)

    # Assertions for script automated exit code
    assert total_bars_found == EXPECTED_TOTAL_BARS, (
        f"Validation failed: expected {EXPECTED_TOTAL_BARS:,} bars, found {total_bars_found:,}"
    )
    assert total_gaps_found == EXPECTED_TOTAL_GAPS, (
        f"Validation failed: expected {EXPECTED_TOTAL_GAPS:,} gaps, found {total_gaps_found:,}"
    )
    for item in bars_summary:
        assert item["total_bars"] == EXPECTED_BARS_PER_COIN, (
            f"Validation failed: {item['_id']} has {item['total_bars']} bars, expected {EXPECTED_BARS_PER_COIN}"
        )
    for item in gaps_summary:
        assert item["total_gaps"] == EXPECTED_GAPS_PER_COIN, (
            f"Validation failed: {item['_id']} has {item['total_gaps']} gaps, expected {EXPECTED_GAPS_PER_COIN}"
        )

    print("\n[SUCCESS] All MongoDB counts and constraints verified successfully!")


def main():
    parser = argparse.ArgumentParser(description="Load cryptocurrency datasets into MongoDB.")
    parser.add_argument("--drop", action="store_true", help="Drop existing collections before loading.")
    args = parser.parse_args()

    print("=" * 65)
    print("Formative 1: Time Series Pipeline - MongoDB Data Loader (Task 2)")
    print("=" * 65)

    client = get_mongo_client()
    db = client[MONGO_DB]

    setup_indexes(db, drop_existing=args.drop)
    load_hourly_bars(db)
    load_data_gaps(db)
    verify_database(db)


if __name__ == "__main__":
    main()
