-- 04_prod.sql
-- Admin script. Li runs this as SYSADMIN, once, after 02_policies.sql. Safe to re-run.
-- Creates the PROD schema next to DEV: same tables, a stage for the semantic model.
--
-- The deploy job (job 4, on merge to main) does NOT run this file: creating schemas and granting
-- access are admin actions (least privilege for CI). The deploy job only uploads the semantic
-- model to the stage below and records the release in OPS.EVAL_RUNS.

USE ROLE SYSADMIN;
USE WAREHOUSE AGENT_WH;

CREATE SCHEMA IF NOT EXISTS MINI_AGENT.PROD;

------------------------------------------------------------------------------
-- 1. Tables: ZERO-COPY CLONES of DEV
--    A clone shares DEV's storage (no data copied, no extra cost until rows change) and keeps
--    the row access and masking policies attached to the source columns.
--    Real projects load PROD from the source pipeline instead; for synthetic data a clone is right.
--    Note: the governance gap travels with the clone. SEND_PERFORMANCE has no row access policy
--    (see PROGRESS.md), so it is unprotected in PROD too until that gap is fixed.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS MINI_AGENT.PROD.EMAIL_SENDS      CLONE MINI_AGENT.DEV.EMAIL_SENDS;
CREATE TABLE IF NOT EXISTS MINI_AGENT.PROD.SEND_PERFORMANCE CLONE MINI_AGENT.DEV.SEND_PERFORMANCE;

------------------------------------------------------------------------------
-- 2. Stage for the semantic model
--    The deploy job PUTs semantic/semantic_model.yaml here. Snowflake Cortex Analyst reads its
--    semantic models from a stage in the same way, so this is the production-shaped location.
------------------------------------------------------------------------------
CREATE STAGE IF NOT EXISTS MINI_AGENT.PROD.SEMANTIC_MODELS
  COMMENT = 'Semantic model YAML, uploaded by the deploy job on every merge to main';

------------------------------------------------------------------------------
-- 3. Read-only access for the agent's role (PUBLIC, stand-in for AGENT_RO)
------------------------------------------------------------------------------
GRANT USAGE ON SCHEMA MINI_AGENT.PROD TO ROLE PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA MINI_AGENT.PROD TO ROLE PUBLIC;

------------------------------------------------------------------------------
-- 4. Checks
------------------------------------------------------------------------------
-- Policies came along with the clone (expect BU_RAP and EMAIL_MASK on PROD.EMAIL_SENDS):
SELECT policy_name, policy_kind, ref_column_name
FROM TABLE(MINI_AGENT.INFORMATION_SCHEMA.POLICY_REFERENCES(
  ref_entity_name => 'MINI_AGENT.PROD.EMAIL_SENDS', ref_entity_domain => 'table'));

-- Same row counts as DEV (as SYSADMIN: all 8 business units):
SELECT 'DEV' AS env, COUNT(*) AS sends FROM MINI_AGENT.DEV.EMAIL_SENDS
UNION ALL
SELECT 'PROD', COUNT(*) FROM MINI_AGENT.PROD.EMAIL_SENDS;

-- After the grants, as the agent's role: only BU_UK and BU_DE should come back.
-- USE ROLE PUBLIC;
-- SELECT business_unit, COUNT(*) FROM MINI_AGENT.PROD.EMAIL_SENDS GROUP BY 1;
