#!/usr/bin/env python3
"""
queries.py
==========
Analytical MongoDB queries for crypto_pipeline database using PyMongo.
Directly mirrors the 5 SQL queries in database/sql/queries.sql.

Usage:
    python database/mongo/queries.py

Design:
    - Connects to MongoDB at mongodb://localhost:27017/ (configurable via MONGO_URI).
    - Database: crypto_pipeline.
    - Strictly read-only operations (zero modifications).
    - Uses native BSON Date (datetime with timezone.utc) for range filters.
    - Each query is preceded by its exact mongosh equivalent in comments.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pandas as pd
from pymongo import MongoClient
from pymongo.errors import PyMongoError


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB = os.getenv("MONGO_DB", "crypto_pipeline")


def get_db():
    """Connect to MongoDB and return database instance."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        return client[MONGO_DB]
    except PyMongoError as e:
        print(f"[ERROR] Could not connect to MongoDB at {MONGO_URI}: {e}", file=sys.stderr)
        sys.exit(1)


def print_section(title: str) -> None:
    """Print standard section banner."""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


# =============================================================================
# QUERY 1: Latest Hourly Bar per Symbol
# =============================================================================
# Equivalent mongosh query:
# -----------------------------------------------------------------------------
# db.hourly_bars.aggregate([
#   { $sort: { timestamp: -1 } },
#   {
#     $group: {
#       _id: "$symbol",
#       timestamp: { $first: "$timestamp" },
#       open_price: { $first: "$open_price" },
#       high_price: { $first: "$high_price" },
#       low_price: { $first: "$low_price" },
#       close_price: { $first: "$close_price" },
#       volume: { $first: "$volume" },
#       minute_count: { $first: "$minute_count" }
#     }
#   },
#   { $sort: { _id: 1 } },
#   {
#     $project: {
#       _id: 0,
#       symbol: "$_id",
#       timestamp: 1,
#       open_price: 1,
#       high_price: 1,
#       low_price: 1,
#       close_price: 1,
#       volume: 1,
#       minute_count: 1
#     }
#   }
# ])
# =============================================================================
def query_1_latest_bar(db):
    print_section("QUERY 1: Latest Hourly Bar per Symbol")
    pipeline = [
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": "$symbol",
                "timestamp": {"$first": "$timestamp"},
                "open_price": {"$first": "$open_price"},
                "high_price": {"$first": "$high_price"},
                "low_price": {"$first": "$low_price"},
                "close_price": {"$first": "$close_price"},
                "volume": {"$first": "$volume"},
                "minute_count": {"$first": "$minute_count"},
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "symbol": "$_id",
                "timestamp": 1,
                "open_price": 1,
                "high_price": 1,
                "low_price": 1,
                "close_price": 1,
                "volume": 1,
                "minute_count": 1,
            }
        },
    ]
    results = list(db.hourly_bars.aggregate(pipeline))
    df = pd.DataFrame(results)
    if not df.empty:
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    print(df.to_string(index=False))


# =============================================================================
# QUERY 2: BTCUSD Bars between 2021-01-01 00:00 and 04:00 UTC
# =============================================================================
# Equivalent mongosh query:
# -----------------------------------------------------------------------------
# db.hourly_bars.find(
#   {
#     symbol: "BTCUSD",
#     timestamp: {
#       $gte: ISODate("2021-01-01T00:00:00.000Z"),
#       $lte: ISODate("2021-01-01T04:00:00.000Z")
#     }
#   },
#   {
#     _id: 0,
#     symbol: 1,
#     timestamp: 1,
#     open_price: 1,
#     high_price: 1,
#     low_price: 1,
#     close_price: 1,
#     volume: 1,
#     minute_count: 1
#   }
# ).sort({ timestamp: 1 })
# =============================================================================
def query_2_btc_range(db):
    print_section("QUERY 2: BTCUSD Bars between 2021-01-01 00:00 and 04:00 UTC")
    start = datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2021, 1, 1, 4, 0, 0, tzinfo=timezone.utc)

    filter_doc = {
        "symbol": "BTCUSD",
        "timestamp": {"$gte": start, "$lte": end},
    }
    projection = {
        "_id": 0,
        "symbol": 1,
        "timestamp": 1,
        "open_price": 1,
        "high_price": 1,
        "low_price": 1,
        "close_price": 1,
        "volume": 1,
        "minute_count": 1,
    }

    results = list(db.hourly_bars.find(filter_doc, projection).sort("timestamp", 1))
    df = pd.DataFrame(results)
    if not df.empty:
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    print(df.to_string(index=False))


# =============================================================================
# QUERY 3: Monthly Summary per Symbol (2020-01, 2020-12, 2021-04)
# =============================================================================
# Equivalent mongosh query:
# -----------------------------------------------------------------------------
# db.hourly_bars.aggregate([
#   {
#     $addFields: {
#       month_label: {
#         $dateToString: { format: "%Y-%m", date: "$timestamp" }
#       }
#     }
#   },
#   {
#     $match: {
#       month_label: { $in: ["2020-01", "2020-12", "2021-04"] }
#     }
#   },
#   {
#     $group: {
#       _id: { symbol: "$symbol", month_label: "$month_label" },
#       avg_close: { $avg: "$close_price" },
#       min_price: { $min: "$low_price" },
#       max_price: { $max: "$high_price" },
#       total_volume: { $sum: "$volume" },
#       total_bars: { $sum: 1 }
#     }
#   },
#   { $sort: { "_id.symbol": 1, "_id.month_label": 1 } },
#   {
#     $project: {
#       _id: 0,
#       symbol: "$_id.symbol",
#       month_label: "$_id.month_label",
#       avg_close: { $round: ["$avg_close", 2] },
#       min_price: { $round: ["$min_price", 2] },
#       max_price: { $round: ["$max_price", 2] },
#       total_volume: { $round: ["$total_volume", 2] },
#       total_bars: 1
#     }
#   }
# ])
# =============================================================================
def query_3_monthly_summary(db):
    print_section("QUERY 3: Monthly Summary per Symbol (2020-01, 2020-12, 2021-04)")
    pipeline = [
        {
            "$addFields": {
                "month_label": {
                    "$dateToString": {"format": "%Y-%m", "date": "$timestamp"}
                }
            }
        },
        {
            "$match": {
                "month_label": {"$in": ["2020-01", "2020-12", "2021-04"]}
            }
        },
        {
            "$group": {
                "_id": {
                    "symbol": "$symbol",
                    "month_label": "$month_label",
                },
                "avg_close": {"$avg": "$close_price"},
                "min_price": {"$min": "$low_price"},
                "max_price": {"$max": "$high_price"},
                "total_volume": {"$sum": "$volume"},
                "total_bars": {"$sum": 1},
            }
        },
        {
            "$sort": {
                "_id.symbol": 1,
                "_id.month_label": 1,
            }
        },
        {
            "$project": {
                "_id": 0,
                "symbol": "$_id.symbol",
                "month_label": "$_id.month_label",
                "avg_close": {"$round": ["$avg_close", 2]},
                "min_price": {"$round": ["$min_price", 2]},
                "max_price": {"$round": ["$max_price", 2]},
                "total_volume": {"$round": ["$total_volume", 2]},
                "total_bars": 1,
            }
        },
    ]
    results = list(db.hourly_bars.aggregate(pipeline))
    df = pd.DataFrame(results)
    print(df.to_string(index=False))


# =============================================================================
# QUERY 4: Highest-Volume Hour per Symbol with Percentage Change
# =============================================================================
# Equivalent mongosh query:
# -----------------------------------------------------------------------------
# db.hourly_bars.aggregate([
#   { $sort: { volume: -1 } },
#   {
#     $group: {
#       _id: "$symbol",
#       peak_bar: { $first: "$$ROOT" }
#     }
#   },
#   { $sort: { _id: 1 } },
#   {
#     $project: {
#       _id: 0,
#       symbol: "$_id",
#       peak_volume_hour: "$peak_bar.timestamp",
#       max_volume: "$peak_bar.volume",
#       open_price: "$peak_bar.open_price",
#       close_price: "$peak_bar.close_price",
#       pct_change: {
#         $round: [
#           {
#             $multiply: [
#               {
#                 $divide: [
#                   { $subtract: ["$peak_bar.close_price", "$peak_bar.open_price"] },
#                   "$peak_bar.open_price"
#                 ]
#               },
#               100
#             ]
#           },
#           2
#         ]
#       }
#     }
#   }
# ])
# =============================================================================
def query_4_peak_volume(db):
    print_section("QUERY 4: Highest-Volume Hour per Symbol with % Change")
    pipeline = [
        {"$sort": {"volume": -1}},
        {
            "$group": {
                "_id": "$symbol",
                "peak_bar": {"$first": "$$ROOT"},
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "symbol": "$_id",
                "peak_volume_hour": "$peak_bar.timestamp",
                "max_volume": "$peak_bar.volume",
                "open_price": "$peak_bar.open_price",
                "close_price": "$peak_bar.close_price",
                "pct_change": {
                    "$round": [
                        {
                            "$multiply": [
                                {
                                    "$divide": [
                                        {"$subtract": ["$peak_bar.close_price", "$peak_bar.open_price"]},
                                        "$peak_bar.open_price",
                                    ]
                                },
                                100,
                            ]
                        },
                        2,
                    ]
                },
            }
        },
    ]
    results = list(db.hourly_bars.aggregate(pipeline))
    df = pd.DataFrame(results)
    if not df.empty:
        df["peak_volume_hour"] = df["peak_volume_hour"].dt.strftime("%Y-%m-%d %H:%M:%S")
    print(df.to_string(index=False))


# =============================================================================
# QUERY 5: First 5 BTCUSD Outages with Pre-Close and Post-Open Prices
# =============================================================================
# Equivalent mongosh script:
# -----------------------------------------------------------------------------
# db.data_gaps.find({ symbol: "BTCUSD" }).sort({ gap_start: 1 }).limit(5).forEach(gap => {
#   const preTime = new Date(gap.gap_start.getTime() - 3600000);
#   const postTime = new Date(gap.gap_end.getTime() + 3600000);
#   const preBar = db.hourly_bars.findOne({ symbol: gap.symbol, timestamp: preTime });
#   const postBar = db.hourly_bars.findOne({ symbol: gap.symbol, timestamp: postTime });
#   const jumpPct = ((postBar.open_price - preBar.close_price) / preBar.close_price * 100).toFixed(2);
#   printjson({
#     symbol: gap.symbol,
#     gap_start: gap.gap_start,
#     gap_end: gap.gap_end,
#     duration_hours: gap.duration_hours,
#     pre_outage_close: preBar.close_price,
#     post_outage_open: postBar.open_price,
#     outage_price_jump_pct: parseFloat(jumpPct)
#   });
# });
#
# Alternatively, using MongoDB $lookup aggregation:
# db.data_gaps.aggregate([
#   { $match: { symbol: "BTCUSD" } },
#   { $sort: { gap_start: 1 } },
#   { $limit: 5 },
#   {
#     $lookup: {
#       from: "hourly_bars",
#       let: { sym: "$symbol", pre_time: { $dateSubtract: { startDate: "$gap_start", unit: "hour", amount: 1 } } },
#       pipeline: [
#         { $match: { $expr: { $and: [ { $eq: ["$symbol", "$$sym"] }, { $eq: ["$timestamp", "$$pre_time"] } ] } } }
#       ],
#       as: "pre_bar"
#     }
#   },
#   {
#     $lookup: {
#       from: "hourly_bars",
#       let: { sym: "$symbol", post_time: { $dateAdd: { startDate: "$gap_end", unit: "hour", amount: 1 } } },
#       pipeline: [
#         { $match: { $expr: { $and: [ { $eq: ["$symbol", "$$sym"] }, { $eq: ["$timestamp", "$$post_time"] } ] } } }
#       ],
#       as: "post_bar"
#     }
#   },
#   { $unwind: "$pre_bar" },
#   { $unwind: "$post_bar" },
#   {
#     $project: {
#       _id: 0,
#       symbol: 1,
#       gap_start: 1,
#       gap_end: 1,
#       duration_hours: 1,
#       pre_outage_close: "$pre_bar.close_price",
#       post_outage_open: "$post_bar.open_price",
#       outage_price_jump_pct: {
#         $round: [
#           {
#             $multiply: [
#               { $divide: [ { $subtract: ["$post_bar.open_price", "$pre_bar.close_price"] }, "$pre_bar.close_price" ] },
#               100
#             ]
#           },
#           2
#         ]
#       }
#     }
#   }
# ])
# =============================================================================
def query_5_outages_jump(db):
    print_section("QUERY 5: First 5 BTCUSD Outages with Pre/Post Outage Price Impact")
    gaps = list(
        db.data_gaps.find({"symbol": "BTCUSD"}).sort("gap_start", 1).limit(5)
    )

    records: List[Dict[str, Any]] = []
    for gap in gaps:
        # Pre-outage hour: 1 hour before gap_start
        pre_time = gap["gap_start"] - timedelta(hours=1)
        # Post-outage hour: 1 hour after gap_end
        post_time = gap["gap_end"] + timedelta(hours=1)

        pre_bar = db.hourly_bars.find_one({"symbol": gap["symbol"], "timestamp": pre_time})
        post_bar = db.hourly_bars.find_one({"symbol": gap["symbol"], "timestamp": post_time})

        pre_close = pre_bar["close_price"] if pre_bar else None
        post_open = post_bar["open_price"] if post_bar else None

        if pre_close and post_open:
            pct_jump = round(((post_open - pre_close) / pre_close) * 100, 2)
        else:
            pct_jump = None

        records.append({
            "symbol": gap["symbol"],
            "gap_start": gap["gap_start"].strftime("%Y-%m-%d %H:%M:%S"),
            "gap_end": gap["gap_end"].strftime("%Y-%m-%d %H:%M:%S"),
            "duration_hours": gap["duration_hours"],
            "pre_outage_close": pre_close,
            "post_outage_open": post_open,
            "outage_price_jump_pct": pct_jump,
        })

    df = pd.DataFrame(records)
    print(df.to_string(index=False))


def main():
    print("=" * 80)
    print("Formative 1: Time Series Pipeline - MongoDB Analytical Queries (Task 2)")
    print(f"Connecting to: {MONGO_URI} (Database: {MONGO_DB})")
    print("=" * 80)

    db = get_db()

    query_1_latest_bar(db)
    query_2_btc_range(db)
    query_3_monthly_summary(db)
    query_4_peak_volume(db)
    query_5_outages_jump(db)

    print("\n" + "=" * 80)
    print("[SUCCESS] All 5 MongoDB queries executed successfully.")
    print("=" * 80)


if __name__ == "__main__":
    main()
