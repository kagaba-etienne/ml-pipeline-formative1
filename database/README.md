# Task 2: Database Design & Implementation (MySQL + MongoDB)

This directory contains the complete database implementation for **Task 2 of Formative 1: Building a Pipeline for Time Series Data**. It provides dual database support (Relational MySQL + Document MongoDB) for 1-hour aggregated cryptocurrency candlestick bars (`BTCUSD`, `ETHUSD`, `LTCUSD`) and exchange outage tracking.

---

## 1. Directory Structure

```text
database/
├── README.md               # Master documentation, reproduction guide, & Task 3 hand-off
├── requirements.txt        # Python package dependencies (pandas, pymysql, pymongo)
├── data/                   # Processed, portable CSV exports (Task 2 outputs)
│   ├── hourly_bars.csv     # 32,961 cleaned 1-hour OHLCV candlestick records
│   └── data_gaps.csv       # 54 exchange outage events (23-hour downtime intervals)
├── erd/                    # Entity-Relationship Diagram
│   ├── README.md           # ERD explanation & Workbench reverse-engineering guide
│   └── erd.png             # Visual ERD exported from MySQL Workbench
├── sql/                    # MySQL Relational Database Assets
│   ├── schema.sql          # DDL script creating crypto_pipeline & 4 normalized tables
│   ├── load_mysql.py       # Aggregates raw CSVs, verifies baseline, & loads MySQL
│   └── queries.sql         # 5 analytical SQL queries demonstrating pipeline capabilities
└── mongo/                  # MongoDB Document Database Assets
    ├── README.md           # MongoDB architecture, sample documents, & time-series design
    ├── load_mongo.py       # Bulk upsert loader storing native BSON Dates & indexes
    └── queries.py          # 5 analytical PyMongo queries mirroring the SQL queries
```

---

## 2. Step-by-Step Reproduction Guide (Windows PowerShell)

All commands below use standard Python and PowerShell without third-party CLI wrappers.

### Step 2.1: Prerequisites & Service Setup
1. **MySQL**: Ensure MySQL 8.0+ is installed and running on `localhost:3306`.
2. **MongoDB Community Server**: Ensure MongoDB 7.0+ (or 9.0+) is installed and running on `localhost:27017`.

### Step 2.2: Python Virtual Environment Setup
Open PowerShell at the repository root (`C:\Users\user\ml-pipeline-formative1`):

```powershell
# 1. Create a virtual environment
python -m venv .venv

# 2. If PowerShell blocks running scripts, enable script execution for CurrentUser:
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r database/requirements.txt
```

### Step 2.3: Execute MySQL Schema
Initialize the database and table structures.

#### Primary Method (Recommended): MySQL Workbench
1. Open **MySQL Workbench** and connect to your local MySQL instance.
2. Go to **File $\rightarrow$ Open SQL Script...** and select `database/sql/schema.sql`.
3. Click the **Execute (lightning bolt)** icon (or press `Ctrl + Shift + Enter`) to create the database and tables.

#### Optional Alternative: PowerShell CLI
If MySQL client binaries are available on your PATH:
```powershell
Get-Content database\sql\schema.sql -Raw | mysql -u root -p
```
*(You will be prompted to type your password securely).*

### Step 2.4: Build Hourly Data & Load MySQL
Run the MySQL loader. This reads raw minute CSVs from `data/` (read-only), resamples them to hourly bars, detects outages, exports `database/data/*.csv`, and bulk-loads MySQL:

```powershell
# Optional: set environment variable, or omit it to be prompted interactively
$env:MYSQL_PASSWORD="your_mysql_password"

python database/sql/load_mysql.py
```
*(If `$env:MYSQL_PASSWORD` is not set, the script will securely prompt you for it in the terminal).*

Expected result: **32,961** bars loaded into `hourly_bars` (10,987 per coin) and **54** outages loaded into `data_gaps`.

### Step 2.5: Load MongoDB
Ingest the cleaned datasets into MongoDB with BSON Date conversion and compound unique indexes:

```powershell
python database/mongo/load_mongo.py
```
Expected result: **32,961** documents in `hourly_bars` and **54** documents in `data_gaps`.

### Step 2.6: Execute Analytical Queries
Verify both database implementations:

1. **MySQL Queries**:
   - Open and execute `database/sql/queries.sql` in **MySQL Workbench** to view all 5 query results.
2. **MongoDB Queries**:
   - Run the PyMongo query suite in PowerShell:
     ```powershell
     python database/mongo/queries.py
     ```

---

## 3. Database Design Summary

### A. MySQL Relational Schema (`crypto_pipeline`)

| Table Name | Role | Primary Key | Key Indexes & Constraints |
| :--- | :--- | :--- | :--- |
| **`symbols`** | Lookup dimension | `symbol_id INT AUTO_INCREMENT` | `UNIQUE (symbol_code)` |
| **`hourly_bars`** | Fact table (OHLCV bars) | `bar_id BIGINT AUTO_INCREMENT` | `UNIQUE (symbol_id, bar_time)`, `INDEX (bar_time)`, `FK -> symbols` |
| **`data_gaps`** | Exchange outage records | `gap_id INT AUTO_INCREMENT` | `UNIQUE (symbol_id, gap_start)`, `INDEX (gap_start, gap_end)`, `FK -> symbols` |
| **`predictions`** | Model forecast storage | `prediction_id BIGINT AUTO_INCREMENT` | `UNIQUE (symbol_id, target_time, model_version)`, `INDEX (target_time)`, `FK -> symbols` |

* **Data Types**: Prices use `DECIMAL(18, 4)`, volume uses `DECIMAL(24, 8)` to prevent floating-point rounding errors. Timestamps use `DATETIME` in UTC.
* **Integrity**: Foreign keys enforce `ON DELETE RESTRICT` (protects historical records) and `ON UPDATE CASCADE`.

### B. MongoDB Document Collections (`crypto_pipeline`)

| Collection | Structure | Natural / Compound Key | Indexes |
| :--- | :--- | :--- | :--- |
| **`hourly_bars`** | Flat model (1 doc per hour) | `(symbol, timestamp)` | `{ symbol: 1, timestamp: 1 }` (Unique), `{ timestamp: 1 }` |
| **`data_gaps`** | 1 doc per outage event | `(symbol, gap_start)` | `{ symbol: 1, gap_start: 1 }` (Unique) |

* **BSON Types**: Timestamps are stored as native BSON `Date` (`ISODate`) objects in UTC for correct temporal sorting and range querying. Numeric values are BSON `Double` and `Int32`.
* **Architecture Choice**: The flat model (one document per hour) provides predictable document sizing, zero resizing overhead in WiredTiger, and 1:1 resource mapping for REST API CRUD operations.

---

## 4. Hand-off Note for Task 3 (REST API Developer)

Welcome to the data layer! Here is everything you need to build the Task 3 API endpoints (`POST`, `GET`, `PUT`, `DELETE`, "latest record", and "records by date range") against MySQL and MongoDB:

### 1. Exact Field & Column Mapping Table

| MySQL Column | MongoDB Field | API JSON Key | Type / Description |
| :--- | :--- | :--- | :--- |
| `bar_id` | `_id` | `id` / `bar_id` | Unique record identifier for CRUD (`GET /bars/:id`) |
| `symbols.symbol_code`| `symbol` | `symbol` | Trading pair (`"BTCUSD"`, `"ETHUSD"`, `"LTCUSD"`) |
| `bar_time` | `timestamp` | `timestamp` | Start of hour in UTC (`YYYY-MM-DDTHH:mm:ssZ`) |
| `open_price` | `open_price` | `open_price` | Price of first minute trade in hour (`Float` / `Double`) |
| `high_price` | `high_price` | `high_price` | Maximum minute high price in hour |
| `low_price` | `low_price` | `low_price` | Minimum minute low price in hour |
| `close_price` | `close_price` | `close_price` | Price of last minute trade in hour |
| `volume` | `volume` | `volume` | Cumulative trading volume across hour |
| `minute_count`| `minute_count`| `minute_count`| Minutes observed in hour ($1 \le x \le 60$) |

### 2. JSON Serialization Note (Decimal vs. Float)
- **Important**: MySQL connectors (PyMySQL, SQLAlchemy) return `DECIMAL` columns as Python `Decimal` objects. Most standard JSON serializers (e.g., standard `json.dumps` or basic Flask/FastAPI encoders) will raise `TypeError: Object of type Decimal is not JSON serializable`.
- Your API serialization layer must convert `Decimal` values to `float` (or `str`) before returning JSON responses to clients.

### 3. Record Identification & Idempotency
- **SQL Identification**: Individual records are accessed by primary key `bar_id` (`BIGINT`).
- **MongoDB Identification**: Individual documents are accessed by `_id` (`ObjectId`), or by the natural composite key `{"symbol": "...", "timestamp": ISODate(...)}`.
- **Duplicate Prevention**: Both databases enforce a unique constraint on `(symbol, timestamp)`. If a client POSTs an already existing hour, your API should catch the unique constraint violation and return HTTP `409 Conflict` (or update via upsert).

### 4. UTC Convention
- All timestamps in both MySQL (`DATETIME`) and MongoDB (BSON `Date`) are strictly in **UTC**.
- When clients pass ISO strings (e.g. `2021-01-01T00:00:00Z`), parse them as UTC before querying.

### 5. Critical Dataset Edge Case: Partial Hours
- In both databases, the very last candlestick bar in the dataset (`2021-04-20 00:00:00 UTC`) represents an **incomplete hour**:
  - `BTCUSD`: `minute_count = 3` (trades only occurred during the first 3 minutes: 00:00 to 00:02).
  - `ETHUSD`: `minute_count = 4` (trades only occurred during the first 4 minutes: 00:00 to 00:03).
  - `LTCUSD`: `minute_count = 4` (trades only occurred during the first 4 minutes: 00:00 to 00:03).
- Always include `minute_count` in API payloads so consumers can distinguish full 60-minute candles from partial candles.

### 6. Requirements for Downstream Task 4 (Forecasting Model)
- The Task 4 prediction script loads the trained model from Task 1 to predict the next hour's BTC close.
- **Time Window vs. Row Count**: Task 4 must request a **time window** covering the required span (e.g. `start_time = end_time - 168 hours`), rather than simply requesting `LIMIT 168` rows. Because of the 18 separate 23-hour exchange outages, requesting 168 rows might reach back much further in calendar time than 7 days.
- **Model Features**: The lag windows (1, 6, and 24 hours) and moving-average windows (24 and 168 hours) originate directly from the Task 1 notebook; please coordinate and confirm these feature windows with the Task 1 teammate before finalizing Task 4.
