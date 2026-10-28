# MongoDB Architecture & Schema Design - Crypto Pipeline

This document outlines the MongoDB schema design for the `crypto_pipeline` database, specifies collection structures with illustrative sample documents, provides a field mapping guide for the Task 3 REST API, details indexing strategies, and compares this design against both relational MySQL and alternative NoSQL patterns (such as day-bucketing).

---

## 1. Database & Collection Overview

* **Database Name**: `crypto_pipeline`
* **Target Collections**:
  1. **`hourly_bars`**: Cleaned, 1-hour OHLCV candlestick records (32,961 documents).
  2. **`data_gaps`**: Identified 23-hour exchange downtime intervals (54 documents).

---

## 2. Collection Schemas & Sample Documents

> [!NOTE]
> The sample documents below are **illustrative representations** of the document structure and BSON types. Exact live documents can be copied directly from MongoDB Compass after running the loader script.

### Collection 1: `hourly_bars`
Stores individual hourly candlestick bars. Field names match the MySQL schema where possible to ensure consistent object serialization for the Task 3 REST API.

#### Illustrative Sample Document:
```json
{
  "_id": ObjectId("671f1a2b3c4d5e6f7a8b9c01"),
  "symbol": "BTCUSD",
  "timestamp": ISODate("2021-01-01T00:00:00.000Z"),
  "open_price": 28979.74,
  "high_price": 29108.58,
  "low_price": 28765.0,
  "close_price": 29078.48,
  "volume": 46.99566066,
  "minute_count": 60,
  "created_at": ISODate("2026-10-28T02:00:00.000Z")
}
```

#### Field Specifications:
| Field | BSON / JS Type | Description | Constraints |
| :--- | :--- | :--- | :--- |
| `_id` | `ObjectId` | MongoDB default primary key. | Unique |
| `symbol` | `String` | Trading pair code (`"BTCUSD"`, `"ETHUSD"`, `"LTCUSD"`). | Indexed |
| `timestamp` | `Date` (ISODate) | UTC hour start timestamp (64-bit millisecond precision). | Indexed |
| `open_price` | `Double` | Price of the first trade in the hour. | $> 0$ |
| `high_price` | `Double` | Maximum price recorded during the hour. | $\ge \text{open, low, close}$ |
| `low_price` | `Double` | Minimum price recorded during the hour. | $\le \text{open, high, close}$ |
| `close_price` | `Double` | Price of the last trade in the hour. | $> 0$ |
| `volume` | `Double` | Cumulative trading volume across the hour. | $\ge 0$ |
| `minute_count`| `Int32` | Number of raw 1-minute trades aggregated (1 to 60). | $1 \le x \le 60$ |
| `created_at` | `Date` | Record ingestion timestamp. | Default `new Date()` |

#### Indexes for `hourly_bars`:
1. **Compound Unique Index**:
   ```javascript
   db.hourly_bars.createIndex(
     { symbol: 1, timestamp: 1 },
     { unique: true, name: "uq_symbol_timestamp" }
   )
   ```
   * **Purpose**: Prevents duplicate hourly records for the same coin, and accelerates range queries filtering by symbol and timestamp (e.g. `{ symbol: "BTCUSD", timestamp: { $gte: ..., $lte: ... } }`).
2. **Secondary Index**:
   ```javascript
   db.hourly_bars.createIndex(
     { timestamp: 1 },
     { name: "idx_timestamp" }
   )
   ```
   * **Purpose**: Optimizes cross-asset time-slice queries (e.g., fetching all coins at a given UTC hour).

---

### Collection 2: `data_gaps`
Stores known 23-hour exchange downtime intervals where no trades occurred.

#### Illustrative Sample Document:
```json
{
  "_id": ObjectId("671f1a2b3c4d5e6f7a8b9c02"),
  "symbol": "BTCUSD",
  "gap_start": ISODate("2020-01-09T01:00:00.000Z"),
  "gap_end": ISODate("2020-01-09T23:00:00.000Z"),
  "duration_hours": 23,
  "notes": "Exchange outage (23-hour gap)",
  "created_at": ISODate("2026-10-28T02:00:00.000Z")
}
```

#### Indexes for `data_gaps`:
```javascript
db.data_gaps.createIndex(
  { symbol: 1, gap_start: 1 },
  { unique: true, name: "uq_symbol_gap_start" }
)
```

---

## 3. Field Mapping Table for Task 3 API Developer

To ensure seamless integration across both databases in Task 3, use this mapping:

### `hourly_bars` Mapping:
| MySQL Column | MongoDB Field | Type in MySQL | Type in MongoDB | Relationship / Status |
| :--- | :--- | :--- | :--- | :--- |
| `bar_id` | `_id` | `BIGINT` (PK) | `ObjectId` (PK) | Primary record identifier for CRUD (`GET /bars/:id`) |
| `symbol_id` (via `symbols.symbol_code`)| `symbol` | `VARCHAR(10)` | `String` | Coin pair (`BTCUSD`, `ETHUSD`, `LTCUSD`). Denormalized in Mongo. |
| `bar_time` | `timestamp` | `DATETIME` (UTC) | BSON `Date` (ISODate) | Start of hour in UTC. Both databases indexed for range queries. |
| `open_price` | `open_price` | `DECIMAL(18, 4)` | `Double` | **Identical** name and meaning |
| `high_price` | `high_price` | `DECIMAL(18, 4)` | `Double` | **Identical** name and meaning |
| `low_price` | `low_price` | `DECIMAL(18, 4)` | `Double` | **Identical** name and meaning |
| `close_price` | `close_price` | `DECIMAL(18, 4)` | `Double` | **Identical** name and meaning |
| `volume` | `volume` | `DECIMAL(24, 8)` | `Double` | **Identical** name and meaning |
| `minute_count`| `minute_count`| `TINYINT UNSIGNED` | `Int32` | **Identical** name and meaning (1-60) |
| `created_at` | `created_at` | `TIMESTAMP` | BSON `Date` | Record ingestion timestamp |

### `data_gaps` Mapping:
| MySQL Column | MongoDB Field | Type in MySQL | Type in MongoDB | Relationship / Status |
| :--- | :--- | :--- | :--- | :--- |
| `gap_id` | `_id` | `INT` (PK) | `ObjectId` (PK) | Unique outage ID |
| `symbol_id` (via `symbols.symbol_code`)| `symbol` | `VARCHAR(10)` | `String` | Coin pair (`BTCUSD`, `ETHUSD`, `LTCUSD`) |
| `gap_start` | `gap_start` | `DATETIME` (UTC) | BSON `Date` (ISODate) | **Identical** name (first missing hour, inclusive) |
| `gap_end` | `gap_end` | `DATETIME` (UTC) | BSON `Date` (ISODate) | **Identical** name (last missing hour, inclusive) |
| `duration_hours` | `duration_hours` | `INT` | `Int32` | **Identical** name (always 23) |
| `notes` | `notes` | `VARCHAR(255)` | `String` | **Identical** name |

---

## 4. Architecture Rationale: One Document per Hour vs Day-Bucketing

In MongoDB time-series design, two common modeling choices exist:
1. **Flat Model (One Document per Hour)**: Chosen for this project.
2. **Bucket Pattern (One Document per Day with an embedded array of 24 hourly bars)**.

### Comparison Table:

| Criterion | Flat Model (1 Doc / Hour) - **OUR CHOICE** | Bucket Pattern (1 Doc / Day) |
| :--- | :--- | :--- |
| **REST API CRUD (Task 3)** | **Simple & Direct**: Every bar has its own `_id`. Updating or deleting a bar is a single `updateOne({ _id }, ...)` or `deleteOne({ _id })`. | **Complex**: Requires array mutation operators (`$pull`, `$elemMatch`, positional `$[]`), which are harder to implement and debug in REST controllers. |
| **Outage & Irregularity** | **Natural Representation**: Missing hours simply don't exist. Gaps do not distort document structure. | **Sparse / Inconsistent Arrays**: During 23-hour outages, daily documents contain only 1 bar instead of 24, creating irregular array shapes. |
| **Document Resizing** | **Zero Resizing**: Document size is fixed upon insertion. Memory allocation in WiredTiger is optimal. | **Frequent Resizing**: Appending new hourly bars throughout the day triggers in-place document growth and potential page reallocations. |
| **Data Size (33K rows)** | **Negligible Footprint**: 32,961 documents take $\approx 6 \text{ MB}$ of RAM. Well within MongoDB limits (no risk of the 16MB document cap). | Saves slight indexing overhead, but unnecessary at this scale. |
| **Aggregation & Filtering** | **Native**: Filtering by date range (`$gte`, `$lte`) works directly on the indexed `timestamp` field. | Requires unwinding arrays (`$unwind`) before filtering and aggregation, adding CPU overhead. |

**Conclusion**: For pre-aggregated hourly data supporting a REST CRUD API (Task 3), the **flat model (one document per hour)** provides the cleanest balance of developer ergonomics, predictable memory usage, and direct field-name parity with SQL.

---

## 5. Comparison: MongoDB vs. MySQL Relational Design

| Aspect | MySQL (Task 2 SQL) | MongoDB (Task 2 Mongo) |
| :--- | :--- | :--- |
| **Data Model** | Normalized relational model (`symbols` dimension table + `hourly_bars` fact table). | Denormalized document model (symbol code `"BTCUSD"` embedded directly in each document). |
| **Join Requirements** | Requires `JOIN symbols ON ...` to resolve symbol code. | No joins needed; each document is self-contained. |
| **Referential Integrity**| Enforced by database engine via Foreign Keys (`ON DELETE RESTRICT`). | Managed at application/API layer. |
| **Primary Key** | Synthetic `BIGINT AUTO_INCREMENT` (`bar_id`). | Native 12-byte BSON `ObjectId` (`_id`). |
| **Natural / Unique Key**| `UNIQUE KEY (symbol_id, bar_time)` | `createIndex({ symbol: 1, timestamp: 1 }, { unique: true })` |
| **Timestamp Storage** | `DATETIME` (UTC text representation). | BSON `Date` (64-bit UTC epoch integer). |
| **Numeric Precision** | Fixed-point `DECIMAL(18, 4)` and `DECIMAL(24, 8)`. | BSON 64-bit floating-point (`Double`) or `Decimal128`. |
