#!/usr/bin/env python3
"""
load_mysql.py
=============
Processes raw minute-level cryptocurrency CSVs from the data/ directory,
aggregates them into 1-hour OHLCV candlestick bars, detects exchange outages,
exports cleaned CSV files into database/data/, and loads everything into MySQL.

Usage:
    # Set your MySQL password in PowerShell:
    $env:MYSQL_PASSWORD="your_password"
    python database/sql/load_mysql.py

Design Principles:
    - Relative paths: Portable across teammates' systems.
    - Zero modification to teammate's raw CSVs in data/.
    - Exact reproduction of Task 1 aggregation logic (first, max, min, last, sum, count).
    - Dynamic calculation and verification of the 18 outages (23 hours each = 414 empty hours).
    - Idempotent database loading using INSERT ... ON DUPLICATE KEY UPDATE.
    - Secure credential handling via environment variables (MYSQL_PASSWORD).
"""

import getpass
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import pymysql


# -----------------------------------------------------------------------------
# Configuration & Paths (Relative to Repository Root)
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DATA_DIR = REPO_ROOT / "database" / "data"

SYMBOLS = ["BTCUSD", "ETHUSD", "LTCUSD"]
CSV_FILES = {
    "BTCUSD": "gemini_BTCUSD_2020_1min.csv",
    "ETHUSD": "gemini_ETHUSD_2020_1min.csv",
    "LTCUSD": "gemini_LTCUSD_2020_1min.csv",
}

# MySQL connection settings from environment with sensible local defaults
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = int(os.getenv("MYSQL_PORT", 3306))
DB_USER = os.getenv("MYSQL_USER", "root")
DB_NAME = os.getenv("MYSQL_DB", "crypto_pipeline")


def get_db_password() -> str:
    """Retrieve MySQL password from environment or prompt securely."""
    password = os.getenv("MYSQL_PASSWORD")
    if password is not None:
        return password
    
    print("[INFO] MYSQL_PASSWORD environment variable not set.")
    try:
        return getpass.getpass("Enter MySQL password: ")
    except Exception:
        print("[ERROR] Could not read password interactively.", file=sys.stderr)
        sys.exit(1)


def process_symbol_data(symbol: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Read raw 1-minute CSV for a given symbol, sort chronologically,
    aggregate to hourly OHLCV bars, and identify outage gaps.
    
    Returns:
        (observed_hourly_bars, data_gaps_df)
    """
    csv_path = DATA_DIR / CSV_FILES[symbol]
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing raw CSV file: {csv_path}")

    print(f"\n[1/4] Reading {symbol} data from {csv_path.name}...")
    # Read raw columns; do not use corrupted 'Unix Timestamp'
    df = pd.read_csv(
        csv_path,
        usecols=["Date", "Symbol", "Open", "High", "Low", "Close", "Volume"],
        dtype={"Symbol": "string", "Open": "float64", "High": "float64",
               "Low": "float64", "Close": "float64", "Volume": "float64"}
    )

    # 1. Parse timestamps and sort chronologically (raw CSV is in reverse order)
    df["timestamp"] = pd.to_datetime(df["Date"], format="mixed")
    df = df.sort_values("timestamp").reset_index(drop=True)

    print(f"      Loaded {len(df):,} minute rows from {df['timestamp'].min()} to {df['timestamp'].max()}.")

    # 2. Resample to hourly bars using exact Task 1 aggregation rules
    #    Open=first, High=max, Low=min, Close=last, Volume=sum, minutes=count
    print(f"[2/4] Aggregating {symbol} into 1-hour OHLCV candlesticks...")
    hourly = (
        df.set_index("timestamp")
        .resample("h")
        .agg(
            open_price=("Open", "first"),
            high_price=("High", "max"),
            low_price=("Low", "min"),
            close_price=("Close", "last"),
            volume=("Volume", "sum"),
            minute_count=("Close", "size"),
        )
    )
    hourly["symbol"] = symbol

    # 3. Dynamic Outage Detection (matching Task 1 notebook logic)
    missing = hourly["minute_count"].eq(0)
    total_missing_hours = int(missing.sum())

    # Contiguous run-length encoding of missing hours
    run_id = missing.ne(missing.shift(fill_value=False)).cumsum()
    gap_runs = hourly[missing].groupby(run_id)

    gaps_records: List[Dict] = []
    for _, group in gap_runs:
        gap_start = group.index.min()
        gap_end = group.index.max()
        duration_hours = len(group)
        gaps_records.append({
            "symbol": symbol,
            "gap_start": gap_start,
            "gap_end": gap_end,
            "duration_hours": duration_hours,
            "notes": f"Exchange outage ({duration_hours}-hour gap)"
        })

    gaps_df = pd.DataFrame(gaps_records)

    # 4. Strict Validation against EDA findings
    print(f"[3/4] Validating {symbol} against Task 1 baseline:")
    print(f"      Total hourly intervals: {len(hourly):,}")
    print(f"      Observed trading hours: {(~missing).sum():,}")
    print(f"      Missing hours (outages): {total_missing_hours} (Expected: 414)")
    print(f"      Outage events detected: {len(gaps_df)} (Expected: 18)")

    assert total_missing_hours == 414, (
        f"Validation error for {symbol}: expected 414 missing hours, got {total_missing_hours}"
    )
    assert len(gaps_df) == 18, (
        f"Validation error for {symbol}: expected 18 outages, got {len(gaps_df)}"
    )
    assert (gaps_df["duration_hours"] == 23).all(), (
        f"Validation error for {symbol}: all outages must be exactly 23 hours"
    )
    print(f"      [OK] Baseline assertions passed for {symbol}!")

    # Filter out empty hours for the database fact table (gaps are stored in data_gaps)
    observed_bars = hourly[~missing].reset_index()

    return observed_bars, gaps_df


def load_to_mysql(
    all_bars: pd.DataFrame,
    all_gaps: pd.DataFrame,
    password: str
) -> None:
    """Load aggregated hourly bars and data gaps into MySQL using batch inserts."""
    print(f"\n[4/4] Connecting to MySQL at {DB_HOST}:{DB_PORT}/{DB_NAME} as user '{DB_USER}'...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=password,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )

    try:
        with conn.cursor() as cursor:
            # 1. Fetch symbol_id mapping from symbols table
            cursor.execute("SELECT symbol_id, symbol_code FROM symbols;")
            symbol_rows = cursor.fetchall()
            symbol_map = {row["symbol_code"]: row["symbol_id"] for row in symbol_rows}
            print(f"      Found symbols in database: {symbol_map}")

            if not all(sym in symbol_map for sym in SYMBOLS):
                raise ValueError(
                    f"Database symbols {list(symbol_map.keys())} do not cover required {SYMBOLS}. "
                    "Make sure schema.sql has been executed."
                )

            # 2. Insert Data Gaps (54 total rows across 3 coins)
            print(f"\n      Inserting {len(all_gaps)} outage records into data_gaps...")
            insert_gap_sql = """
                INSERT INTO data_gaps (symbol_id, gap_start, gap_end, duration_hours, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    gap_end = VALUES(gap_end),
                    duration_hours = VALUES(duration_hours),
                    notes = VALUES(notes);
            """
            gap_data = [
                (
                    symbol_map[row["symbol"]],
                    row["gap_start"].strftime("%Y-%m-%d %H:%M:%S"),
                    row["gap_end"].strftime("%Y-%m-%d %H:%M:%S"),
                    int(row["duration_hours"]),
                    row["notes"]
                )
                for _, row in all_gaps.iterrows()
            ]
            cursor.executemany(insert_gap_sql, gap_data)
            conn.commit()
            print(f"      [OK] data_gaps loaded successfully ({cursor.rowcount} rows affected).")

            # 3. Batch Insert Hourly Bars (32,961 total rows)
            batch_size = 5000
            total_bars = len(all_bars)
            print(f"\n      Inserting {total_bars:,} hourly bars into hourly_bars in batches of {batch_size}...")

            insert_bar_sql = """
                INSERT INTO hourly_bars (
                    symbol_id, bar_time, open_price, high_price, low_price,
                    close_price, volume, minute_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    open_price = VALUES(open_price),
                    high_price = VALUES(high_price),
                    low_price = VALUES(low_price),
                    close_price = VALUES(close_price),
                    volume = VALUES(volume),
                    minute_count = VALUES(minute_count);
            """

            bar_records = [
                (
                    symbol_map[row["symbol"]],
                    row["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                    round(float(row["open_price"]), 4),
                    round(float(row["high_price"]), 4),
                    round(float(row["low_price"]), 4),
                    round(float(row["close_price"]), 4),
                    round(float(row["volume"]), 8),
                    int(row["minute_count"])
                )
                for _, row in all_bars.iterrows()
            ]

            for i in range(0, total_bars, batch_size):
                chunk = bar_records[i : i + batch_size]
                cursor.executemany(insert_bar_sql, chunk)
                conn.commit()
                print(f"      Loaded bars {min(i + batch_size, total_bars):,} of {total_bars:,}...")

            print(f"      [OK] hourly_bars loaded successfully.")

            # 4. Final Database Verification Queries
            print("\n" + "=" * 60)
            print("DATABASE VERIFICATION SUMMARY")
            print("=" * 60)
            cursor.execute("""
                SELECT s.symbol_code, COUNT(b.bar_id) AS total_bars,
                       MIN(b.bar_time) AS earliest_bar, MAX(b.bar_time) AS latest_bar
                FROM symbols s
                LEFT JOIN hourly_bars b ON s.symbol_id = b.symbol_id
                GROUP BY s.symbol_code
                ORDER BY s.symbol_code;
            """)
            for row in cursor.fetchall():
                print(f"Symbol {row['symbol_code']}: {row['total_bars']:,} bars ({row['earliest_bar']} to {row['latest_bar']})")

            cursor.execute("""
                SELECT s.symbol_code, COUNT(g.gap_id) AS total_gaps,
                       SUM(g.duration_hours) AS total_empty_hours
                FROM symbols s
                LEFT JOIN data_gaps g ON s.symbol_id = g.symbol_id
                GROUP BY s.symbol_code
                ORDER BY s.symbol_code;
            """)
            print("-" * 60)
            for row in cursor.fetchall():
                print(f"Outages {row['symbol_code']}: {row['total_gaps']} gaps, {row['total_empty_hours']} total empty hours")
            print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Database transaction failed: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()
        print("Database connection closed.")


def main():
    print("=" * 70)
    print("Formative 1: Time Series Pipeline - MySQL Data Loader (Task 2)")
    print("=" * 70)

    # Ensure output data directory exists
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_bars_list = []
    all_gaps_list = []

    # Process all 3 coins
    for sym in SYMBOLS:
        bars_df, gaps_df = process_symbol_data(sym)
        all_bars_list.append(bars_df)
        all_gaps_list.append(gaps_df)

    combined_bars = pd.concat(all_bars_list, ignore_index=True)
    combined_gaps = pd.concat(all_gaps_list, ignore_index=True)

    # Export cleaned datasets to database/data/ for portability
    bars_csv = OUTPUT_DATA_DIR / "hourly_bars.csv"
    gaps_csv = OUTPUT_DATA_DIR / "data_gaps.csv"
    print(f"\nExporting cleaned hourly bars to: {bars_csv.relative_to(REPO_ROOT)}")
    combined_bars.to_csv(bars_csv, index=False)
    print(f"Exporting detected data gaps to:   {gaps_csv.relative_to(REPO_ROOT)}")
    combined_gaps.to_csv(gaps_csv, index=False)

    # Load into MySQL
    password = get_db_password()
    load_to_mysql(combined_bars, combined_gaps, password)

    print("\n[SUCCESS] Step 3 complete! MySQL database is fully loaded and verified.")


if __name__ == "__main__":
    main()
