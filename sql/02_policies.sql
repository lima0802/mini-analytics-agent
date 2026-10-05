-- 02_policies.sql
-- Admin script. Li runs this as SYSADMIN after 00_seed.sql.
-- One row access policy (which ROWS a role sees) and one masking policy (what VALUE a role sees).
--
-- Account constraint: Li cannot create roles, so we compare two roles Li already has:
--   SYSADMIN = admin view (sees everything)
--   PUBLIC   = stand-in for AGENT_RO, the role the agent connects with (sees a subset, masked)
-- Note: masking and row access policies need Snowflake Enterprise edition or higher.

USE ROLE SYSADMIN;
USE WAREHOUSE AGENT_WH;
USE SCHEMA MINI_AGENT.DEV;

------------------------------------------------------------------------------
-- 1. Read-only access for PUBLIC (SYSADMIN owns these objects, so it can grant on them)
--    PUBLIC is every user in the account. Fine here ONLY because the schema is synthetic.
------------------------------------------------------------------------------
GRANT USAGE ON WAREHOUSE AGENT_WH TO ROLE PUBLIC;
GRANT USAGE ON DATABASE MINI_AGENT TO ROLE PUBLIC;
GRANT USAGE ON SCHEMA MINI_AGENT.DEV TO ROLE PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA MINI_AGENT.DEV TO ROLE PUBLIC;

------------------------------------------------------------------------------
-- 2. Row access policy: SYSADMIN sees all business units, everyone else only BU_UK and BU_DE
--    The body is a boolean evaluated per row; FALSE means the row is silently filtered out.
--    Production pattern: look up allowed business units in a mapping table instead of hard-coding.
------------------------------------------------------------------------------
CREATE ROW ACCESS POLICY IF NOT EXISTS BU_RAP
  AS (business_unit STRING) RETURNS BOOLEAN ->
    CURRENT_ROLE() = 'SYSADMIN'
    OR business_unit IN ('BU_UK', 'BU_DE');

ALTER TABLE EMAIL_SENDS ADD ROW ACCESS POLICY BU_RAP ON (business_unit);

------------------------------------------------------------------------------
-- 3. Masking policy: SYSADMIN sees the real email, everyone else sees '*****@example.com'
--    The body returns the value to show; input and output type must match the column type.
------------------------------------------------------------------------------
-- Written by Li: SYSADMIN sees the value; everyone else gets the part before '@' replaced.
-- '^[^@]+' = from the start (^), one or more (+) characters that are not '@' ([^@]).
CREATE MASKING POLICY IF NOT EXISTS EMAIL_MASK
  AS (val STRING) RETURNS STRING ->
    CASE
      WHEN CURRENT_ROLE() = 'SYSADMIN' THEN val            -- admin: real email
      ELSE REGEXP_REPLACE(val, '^[^@]+', '*****')         -- others: *****@example.com
    END;

ALTER TABLE EMAIL_SENDS MODIFY COLUMN owner_email SET MASKING POLICY EMAIL_MASK;

------------------------------------------------------------------------------
-- 4. Same query, two roles. Compare the results.
--    Secondary roles OFF, so only the primary role counts (otherwise SYSADMIN leaks into PUBLIC).
------------------------------------------------------------------------------
USE SECONDARY ROLES NONE;

USE ROLE SYSADMIN;
SELECT CURRENT_ROLE() AS role, business_unit, COUNT(*) AS sends, MIN(owner_email) AS sample_email
FROM MINI_AGENT.DEV.EMAIL_SENDS
GROUP BY business_unit
ORDER BY business_unit;
-- Expect: 8 business units, 50 sends each, real emails

USE ROLE PUBLIC;
USE WAREHOUSE AGENT_WH;
SELECT CURRENT_ROLE() AS role, business_unit, COUNT(*) AS sends, MIN(owner_email) AS sample_email
FROM MINI_AGENT.DEV.EMAIL_SENDS
GROUP BY business_unit
ORDER BY business_unit;
-- Expect: only BU_DE and BU_UK, emails masked

-- Leak check: SEND_PERFORMANCE has no BUSINESS_UNIT column, so the policy does not protect it.
SELECT COUNT(*) AS sends_visible FROM MINI_AGENT.DEV.SEND_PERFORMANCE;
-- Expect 400, not 100. Joining to EMAIL_SENDS filters it; querying it alone does not.
-- Worse: SEND_SK ends in the business unit, so the key itself reveals the hidden markets.

USE ROLE SYSADMIN;
USE SECONDARY ROLES ALL;

------------------------------------------------------------------------------
-- To change a policy later: ALTER ... SET BODY (CREATE OR REPLACE fails while it is attached)
--   ALTER MASKING POLICY EMAIL_MASK SET BODY -> <new expression>;
-- To undo:
--   ALTER TABLE EMAIL_SENDS DROP ROW ACCESS POLICY BU_RAP;
--   ALTER TABLE EMAIL_SENDS MODIFY COLUMN owner_email UNSET MASKING POLICY;
------------------------------------------------------------------------------
