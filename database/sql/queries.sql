-- =============================================================================
-- Formative 1: Time Series Data Pipeline - Task 2 (MySQL Analytical Queries)
-- File: database/sql/queries.sql
-- Database: crypto_pipeline
--
-- This script contains 5 analytical SQL queries demonstrating:
--   1. Latest hourly candlestick per symbol (window functions)
--   2. Time-series slice for BTC within a date range (indexing & ordering)
--   3. Monthly price and volume summary per symbol (grouping & date formatting)
--   4. Peak volume hour per symbol (analytical ranking CTE)
--   5. Outage gap analysis with pre/post-gap price impact (joining fact & gap tables)
--
-- Note: Execute these queries directly in MySQL Workbench against your loaded
-- crypto_pipeline database to view and export the live result sets for your report.
-- =============================================================================

USE crypto_pipeline;

-- =============================================================================
-- QUERY 1: Latest Hourly Bar per Symbol
-- =============================================================================
-- Rationale:
--   Directly powers the Task 3 API ("latest record" endpoint) and Task 4 prediction
--   script to check the most current market state.
--
-- How it works:
--   Uses a Common Table Expression (CTE) with the ROW_NUMBER() window function.
--   It partitions the data by symbol and orders each partition by bar_time DESC
--   (newest first). Filtering by rn = 1 extracts the top (most recent) bar.
-- -----------------------------------------------------------------------------
WITH RankedBars AS (
    SELECT 
        s.symbol_code,
        b.bar_time,
        b.open_price,
        b.high_price,
        b.low_price,
        b.close_price,
        b.volume,
        b.minute_count,
        ROW_NUMBER() OVER (
            PARTITION BY b.symbol_id 
            ORDER BY b.bar_time DESC
        ) AS rn
    FROM hourly_bars b
    JOIN symbols s ON b.symbol_id = s.symbol_id
)
SELECT 
    symbol_code,
    bar_time,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    minute_count
FROM RankedBars
WHERE rn = 1
ORDER BY symbol_code;


-- =============================================================================
-- QUERY 2: BTC Bars in a Specific Date Range
-- =============================================================================
-- Rationale:
--   Supports the Task 3 API "records by date range" endpoint and Task 4's
--   requirement to fetch at least 168 hourly bars to construct moving average
--   and return lag features.
--
-- How it works:
--   Filters by symbol_code and an inclusive bar_time window. Because we have
--   a composite UNIQUE constraint on (symbol_id, bar_time) and an index on
--   bar_time, MySQL uses an index range scan rather than scanning the entire table.
-- -----------------------------------------------------------------------------
SELECT 
    s.symbol_code,
    b.bar_time,
    b.open_price,
    b.high_price,
    b.low_price,
    b.close_price,
    b.volume,
    b.minute_count
FROM hourly_bars b
JOIN symbols s ON b.symbol_id = s.symbol_id
WHERE s.symbol_code = 'BTCUSD'
  AND b.bar_time BETWEEN '2021-01-01 00:00:00' AND '2021-01-01 06:00:00'
ORDER BY b.bar_time ASC;


-- =============================================================================
-- QUERY 3: Monthly Average Close, Price Range, and Total Volume per Symbol
-- =============================================================================
-- Rationale:
--   Macro trend analysis: summarizes the 2020-2021 crypto market trend across all
--   tracked assets.
--
-- How it works:
--   Formats the bar_time into 'YYYY-MM' strings using DATE_FORMAT() and aliases
--   it as `month_label` (avoiding the MySQL reserved keyword `year_month`).
--   Groups records by asset and month, calculating aggregate metrics:
--   AVG(close_price), MIN(low_price), MAX(high_price), and SUM(volume).
-- -----------------------------------------------------------------------------
SELECT 
    s.symbol_code,
    DATE_FORMAT(b.bar_time, '%Y-%m') AS month_label,
    ROUND(AVG(b.close_price), 2) AS avg_close,
    ROUND(MIN(b.low_price), 2) AS min_price,
    ROUND(MAX(b.high_price), 2) AS max_price,
    ROUND(SUM(b.volume), 2) AS total_volume,
    COUNT(*) AS total_bars
FROM hourly_bars b
JOIN symbols s ON b.symbol_id = s.symbol_id
WHERE DATE_FORMAT(b.bar_time, '%Y-%m') IN ('2020-01', '2020-06', '2020-12', '2021-04')
GROUP BY s.symbol_code, DATE_FORMAT(b.bar_time, '%Y-%m')
ORDER BY s.symbol_code, month_label;


-- =============================================================================
-- QUERY 4: Highest-Volume Hour per Symbol (Peak Activity)
-- =============================================================================
-- Rationale:
--   Detects the single highest trading-volume hour for each coin and computes the
--   percentage price movement during that peak volume hour.
--   Observation: For all three coins, the highest-volume hour was a down hour
--   with negative percentage returns (-8.73%, -3.31%, -3.99%).
--
-- How it works:
--   Uses ROW_NUMBER() partitioned by symbol_id and ordered by volume DESC.
--   Computes the hourly percentage return: ((close - open) / open) * 100.
-- -----------------------------------------------------------------------------
WITH PeakVolume AS (
    SELECT 
        s.symbol_code,
        b.bar_time,
        b.volume,
        b.open_price,
        b.close_price,
        ROUND(((b.close_price - b.open_price) / b.open_price) * 100, 2) AS pct_change,
        ROW_NUMBER() OVER (
            PARTITION BY b.symbol_id 
            ORDER BY b.volume DESC
        ) AS rn
    FROM hourly_bars b
    JOIN symbols s ON b.symbol_id = s.symbol_id
)
SELECT 
    symbol_code,
    bar_time AS peak_volume_hour,
    volume AS max_volume,
    open_price,
    close_price,
    pct_change
FROM PeakVolume
WHERE rn = 1
ORDER BY symbol_code;


-- =============================================================================
-- QUERY 5: Outage Gap Analysis & Pre/Post Outage Price Impact
-- =============================================================================
-- Rationale:
--   Connects the data_gaps table with hourly_bars to measure the price movement
--   or change that occurred across the 23-hour exchange downtime intervals.
--
-- How it works:
--   Performs two LEFT JOINs from data_gaps back to hourly_bars:
--     - b_before joins at bar_time = gap_start - 1 hour (last trade before outage)
--     - b_after  joins at bar_time = gap_end + 1 hour (first trade after outage)
--   Calculates price gap percentage: ((post_open - pre_close) / pre_close) * 100.
-- -----------------------------------------------------------------------------
SELECT 
    s.symbol_code,
    g.gap_start,
    g.gap_end,
    g.duration_hours,
    b_before.close_price AS pre_outage_close,
    b_after.open_price AS post_outage_open,
    ROUND(
        ((b_after.open_price - b_before.close_price) / b_before.close_price) * 100, 
        2
    ) AS outage_price_jump_pct
FROM data_gaps g
JOIN symbols s ON g.symbol_id = s.symbol_id
LEFT JOIN hourly_bars b_before 
    ON g.symbol_id = b_before.symbol_id 
    AND b_before.bar_time = DATE_SUB(g.gap_start, INTERVAL 1 HOUR)
LEFT JOIN hourly_bars b_after 
    ON g.symbol_id = b_after.symbol_id 
    AND b_after.bar_time = DATE_ADD(g.gap_end, INTERVAL 1 HOUR)
WHERE s.symbol_code = 'BTCUSD'
ORDER BY g.gap_start ASC
LIMIT 5;
