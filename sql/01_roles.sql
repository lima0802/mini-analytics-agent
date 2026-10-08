-- 01_roles.sql
-- Admin script. Li runs this by hand in a Snowsight worksheet; the agent never runs it.
-- Creates: XS warehouse with guardrails, read-only role AGENT_RO, service user AGENT_SVC (key-pair only).
-- Names: database MINI_AGENT, dev schema DEV. Find-and-replace if yours differ.
-- Safe to re-run: every statement is IF NOT EXISTS or a grant.
--
-- ACCOUNT CONSTRAINT (5 Oct): Li's user has no USERADMIN/SECURITYADMIN on this account,
-- so only section 1 was run. Sections 2-4 are the target design, kept for CI/CD and the interview.
-- Stand-in until then: the agent connects as LIMA with role PUBLIC (see 02_policies.sql, agent/db.py).

------------------------------------------------------------------------------
-- 0. Key pair (run in a terminal, NOT in Snowflake). Keep both files outside the repo.
--    openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
--    openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
--    Private key path goes in .env (SNOWFLAKE_PRIVATE_KEY_PATH). Public key goes to Snowflake in step 4.
------------------------------------------------------------------------------

------------------------------------------------------------------------------
-- 1. Database, schema and warehouse (SYSADMIN owns objects)
------------------------------------------------------------------------------
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS MINI_AGENT;
CREATE SCHEMA IF NOT EXISTS MINI_AGENT.DEV;

CREATE WAREHOUSE IF NOT EXISTS AGENT_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60                         -- seconds idle before it stops billing
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 60         -- kill any query running longer than 60s
  STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 30  -- give up if queued longer than 30s
  COMMENT = 'Warehouse for the text-to-SQL agent';

------------------------------------------------------------------------------
-- 2. Read-only role (USERADMIN creates roles and users)
------------------------------------------------------------------------------
USE ROLE USERADMIN;

CREATE ROLE IF NOT EXISTS AGENT_RO
  COMMENT = 'Read-only role for the text-to-SQL agent';

------------------------------------------------------------------------------
-- 3. Grants (SECURITYADMIN holds MANAGE GRANTS)
------------------------------------------------------------------------------
USE ROLE SECURITYADMIN;

-- Hang the custom role under SYSADMIN so admins inherit it (Snowflake best practice).
GRANT ROLE AGENT_RO TO ROLE SYSADMIN;

GRANT USAGE ON WAREHOUSE AGENT_WH TO ROLE AGENT_RO;
GRANT USAGE ON DATABASE MINI_AGENT TO ROLE AGENT_RO;
GRANT USAGE ON SCHEMA MINI_AGENT.DEV TO ROLE AGENT_RO;

-- Existing objects
GRANT SELECT ON ALL TABLES IN SCHEMA MINI_AGENT.DEV TO ROLE AGENT_RO;
GRANT SELECT ON ALL VIEWS IN SCHEMA MINI_AGENT.DEV TO ROLE AGENT_RO;

GRANT SELECT ON FUTURE TABLES IN SCHEMA MINI_AGENT.DEV TO ROLE AGENT_RO;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA MINI_AGENT.DEV TO ROLE AGENT_RO;

------------------------------------------------------------------------------
-- 4. Service user: no password, key-pair auth only
------------------------------------------------------------------------------
USE ROLE USERADMIN;

CREATE USER IF NOT EXISTS AGENT_SVC
  TYPE = SERVICE                 -- service users cannot have a password or use MFA/SSO
  DEFAULT_ROLE = AGENT_RO
  DEFAULT_WAREHOUSE = AGENT_WH
  DEFAULT_NAMESPACE = 'MINI_AGENT.DEV'
  COMMENT = 'Service user for the text-to-SQL agent';

-- Paste the body of rsa_key.pub (without the BEGIN/END lines) in the worksheet only.
-- Do not save the key into this file.
-- ALTER USER AGENT_SVC SET RSA_PUBLIC_KEY = '<PASTE_PUBLIC_KEY_BODY>';

USE ROLE SECURITYADMIN;
GRANT ROLE AGENT_RO TO USER AGENT_SVC;

------------------------------------------------------------------------------
-- 5. Check it worked
------------------------------------------------------------------------------
SHOW GRANTS TO ROLE AGENT_RO;
DESC USER AGENT_SVC;             -- RSA_PUBLIC_KEY_FP should be filled after the ALTER above

-- Negative test: this must fail with "Insufficient privileges".
USE ROLE AGENT_RO;
USE WAREHOUSE AGENT_WH;
CREATE TABLE MINI_AGENT.DEV.SHOULD_FAIL (x INT);
