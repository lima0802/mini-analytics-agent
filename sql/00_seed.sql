-- 00_seed.sql
-- Admin script. Li runs this once as SYSADMIN, after 01_roles.sql section 1.
-- Creates 3 SYNTHETIC email-marketing tables (SFMC-style shape) in MINI_AGENT.DEV.
-- Every code, id and email here is invented. Never copy client rows into this schema.
-- Re-running replaces the tables with new random numbers (and detaches policies), so run it once.

USE ROLE SYSADMIN;
USE WAREHOUSE AGENT_WH;
USE SCHEMA MINI_AGENT.DEV;

-- Remove the first version of the seed (marketing campaigns), if it was run.
DROP TABLE IF EXISTS CHANNELS;
DROP TABLE IF EXISTS CAMPAIGNS;
DROP TABLE IF EXISTS DAILY_PERFORMANCE;

------------------------------------------------------------------------------
-- BUSINESS_UNITS: 8 fictional business units (one per country)
------------------------------------------------------------------------------
CREATE OR REPLACE TABLE BUSINESS_UNITS (
  business_unit  STRING,   -- e.g. 'BU_UK'
  country_name   STRING,
  region         STRING
) AS
SELECT * FROM VALUES
  ('BU_UK', 'United Kingdom', 'North'),
  ('BU_DE', 'Germany',        'Central'),
  ('BU_FR', 'France',         'Central'),
  ('BU_NL', 'Netherlands',    'North'),
  ('BU_SE', 'Sweden',         'North'),
  ('BU_ES', 'Spain',          'South'),
  ('BU_IT', 'Italy',          'South'),
  ('BU_PL', 'Poland',         'Central');

------------------------------------------------------------------------------
-- EMAIL_SENDS: 400 sends in Q3 2026, one row per send
-- SEND_SK = send id + business unit, same shape as a real SFMC key, fake values.
-- BUSINESS_UNIT drives the row access policy; OWNER_EMAIL drives the masking policy.
------------------------------------------------------------------------------
CREATE OR REPLACE TABLE EMAIL_SENDS AS
WITH ids AS (
  SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS n   -- 1..400, no gaps
  FROM TABLE(GENERATOR(ROWCOUNT => 400))
)
SELECT
  (9000000 + n)::STRING || '_' || bu.business_unit                         AS send_sk,
  9000000 + n                                                              AS send_id,
  bu.business_unit,
  DATEADD(day, UNIFORM(0, 91, RANDOM()), '2026-07-01'::DATE)               AS send_date,
  ARRAY_CONSTRUCT('Newsletter', 'Promotional', 'Triggered', 'Transactional')[MOD(n, 4)]::STRING
                                                                           AS email_type,
  'owner' || MOD(n, 12) || '@example.com'                                  AS owner_email
FROM ids
JOIN (SELECT business_unit, ROW_NUMBER() OVER (ORDER BY business_unit) - 1 AS bu_idx
      FROM BUSINESS_UNITS) bu
  ON MOD(ids.n, 8) = bu.bu_idx;

------------------------------------------------------------------------------
-- SEND_PERFORMANCE: one row per send
-- Funnel: sent -> delivered (95-99%) -> opens (15-45%) -> clicks (5-20% of opens)
--         bounces = sent - delivered; unsubscribes 0-0.5% of delivered
------------------------------------------------------------------------------
CREATE OR REPLACE TABLE SEND_PERFORMANCE AS
WITH base AS (
  SELECT send_sk, UNIFORM(2000, 80000, RANDOM()) AS sent
  FROM EMAIL_SENDS
)
SELECT
  send_sk,
  sent,
  ROUND(sent * UNIFORM(95, 99, RANDOM()) / 100)          AS delivered,
  sent - delivered                                       AS bounces,      -- reuses the alias above
  ROUND(delivered * UNIFORM(15, 45, RANDOM()) / 100)     AS opens,
  ROUND(opens * UNIFORM(5, 20, RANDOM()) / 100)          AS clicks,
  ROUND(delivered * UNIFORM(0, 50, RANDOM()) / 10000)    AS unsubscribes
FROM base;

------------------------------------------------------------------------------
-- Check
------------------------------------------------------------------------------
SELECT 'BUSINESS_UNITS' AS t, COUNT(*) AS n FROM BUSINESS_UNITS
UNION ALL SELECT 'EMAIL_SENDS', COUNT(*) FROM EMAIL_SENDS
UNION ALL SELECT 'SEND_PERFORMANCE', COUNT(*) FROM SEND_PERFORMANCE;
-- Expect 8 / 400 / 400
