-- drill.sql — Advanced SQL drill (about 20 minutes). Li writes, Claude reviews.
-- Run in Snowsight as SYSADMIN (sees all 8 business units). Synthetic data from 00_seed.sql.

USE ROLE SYSADMIN;
USE WAREHOUSE AGENT_WH;
USE SCHEMA MINI_AGENT.DEV;

------------------------------------------------------------------------------
-- 1. QUALIFY + ROW_NUMBER: the most recent send per business unit
--    Returns: 8 rows (one per business_unit) with send_sk, send_date, email_type.
--    Hint: ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC) and keep row 1 with QUALIFY.
--    Think: two sends on the same latest day? Add a second ORDER BY column as tie-breaker.
------------------------------------------------------------------------------
-- Why the tie-breaker: without send_sk, two sends on the same day get ROW_NUMBER 1 and 2
-- in an arbitrary order, so the "latest send" can change between runs (non-deterministic).
SELECT business_unit, send_sk, send_date, email_type
FROM EMAIL_SENDS
QUALIFY ROW_NUMBER() OVER (PARTITION BY business_unit ORDER BY send_date DESC, send_sk DESC) = 1
ORDER BY business_unit;


------------------------------------------------------------------------------
-- 2. LAG: day-over-day change in emails sent, per business unit
--    Returns: business_unit, send_date, daily_sent, prev_daily_sent, change.
--    Hint: first aggregate SUM(p.sent) per business_unit and send_date in a CTE (join both tables),
--          then LAG(daily_sent) OVER (PARTITION BY ... ORDER BY ...).
--    Think: what is prev_daily_sent on each business unit's first day, and why?
------------------------------------------------------------------------------
-- First day: LAG returns NULL (no earlier row in the partition), so change is NULL too.
-- Careful: LAG means "previous ROW", i.e. the previous day WITH sends, not the previous
-- calendar day. For true calendar day-over-day, join to a date spine first.
WITH daily AS (
  SELECT s.business_unit, s.send_date, SUM(p.sent) AS daily_sent
  FROM EMAIL_SENDS s
  JOIN SEND_PERFORMANCE p ON s.send_sk = p.send_sk
  GROUP BY s.business_unit, s.send_date
)
SELECT
  business_unit,
  send_date,
  daily_sent,
  LAG(daily_sent) OVER (PARTITION BY business_unit ORDER BY send_date) AS prev_daily_sent,
  daily_sent - prev_daily_sent                                          AS change
FROM daily
ORDER BY business_unit, send_date;


------------------------------------------------------------------------------
-- 3. Running total WITH an explicit frame clause: cumulative emails sent per business unit
--    Returns: business_unit, send_date, daily_sent, cumulative_sent.
--    Hint: SUM(daily_sent) OVER (PARTITION BY ... ORDER BY ...
--                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
--    Bonus: 7-day moving average with ROWS BETWEEN 6 PRECEDING AND CURRENT ROW.
--    Think: without a frame clause the default is RANGE, not ROWS. When does that give a
--           different answer?
------------------------------------------------------------------------------
-- ROWS vs RANGE: with ties in the ORDER BY (same send_date twice in a partition), RANGE treats
-- the tied rows as one peer group and gives them all the same total; ROWS adds them one by one.
-- Here daily is unique per (business_unit, send_date), so both match; on raw EMAIL_SENDS they differ.
-- Moving average: 6 PRECEDING = the last 7 ROWS (days with sends), not 7 calendar days.
WITH daily AS (
  SELECT s.business_unit, s.send_date, SUM(p.sent) AS daily_sent
  FROM EMAIL_SENDS s
  JOIN SEND_PERFORMANCE p ON s.send_sk = p.send_sk
  GROUP BY s.business_unit, s.send_date
)
SELECT
  business_unit,
  send_date,
  daily_sent,
  SUM(daily_sent) OVER (
    PARTITION BY business_unit ORDER BY send_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS cumulative_sent,
  AVG(daily_sent) OVER (
    PARTITION BY business_unit ORDER BY send_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS moving_avg_7_rows
FROM daily
ORDER BY business_unit, send_date;


------------------------------------------------------------------------------
-- 4. Top-N per group: the 3 sends with the highest click rate in each email_type
--    click rate = clicks / NULLIF(delivered, 0)
--    Returns: 12 rows (4 email types x 3), email_type, send_sk, click_rate, rank.
--    Hint: same QUALIFY pattern as exercise 1, with <= 3.
--    Think: ROW_NUMBER vs RANK vs DENSE_RANK when two sends tie. Which one can return more than 3?
------------------------------------------------------------------------------
-- Ties: ROW_NUMBER always gives exactly 3 (arbitrary among ties); RANK (1,1,3) and
-- DENSE_RANK (1,1,2) can return more than 3 rows per group. Pick based on the business question.
-- NULLS LAST: in Snowflake, DESC puts NULLs FIRST by default, so a NULL click rate
-- (delivered = 0) would otherwise rank as the "best" send.
SELECT
  s.email_type,
  s.send_sk,
  p.clicks / NULLIF(p.delivered, 0) AS click_rate,
  ROW_NUMBER() OVER (
    PARTITION BY s.email_type
    ORDER BY p.clicks / NULLIF(p.delivered, 0) DESC NULLS LAST
  ) AS rank_in_type
FROM EMAIL_SENDS s
JOIN SEND_PERFORMANCE p ON s.send_sk = p.send_sk
QUALIFY rank_in_type <= 3
ORDER BY s.email_type, rank_in_type;


------------------------------------------------------------------------------
-- 5. Read one query profile (no SQL to write)
--    Run exercise 2 or 3, then in Snowsight: Monitoring > Query History > click the query >
--    Query Profile. Note down:
--      - the operators, bottom to top (TableScan, Join, Aggregate, WindowFunction, ...)
--      - Most Expensive Nodes: which operator took the most time?
--      - Partitions scanned vs partitions total (pruning)
--      - Bytes spilled to local/remote storage (should be 0 here)
------------------------------------------------------------------------------
