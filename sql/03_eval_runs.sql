-- 03_eval_runs.sql
-- Admin script. Li runs this as SYSADMIN. Safe to re-run (IF NOT EXISTS).
-- EVAL_RUNS: one row per golden question per eval run (internal eval), plus one row per release.
--
-- Lives in its own schema OPS, NOT in DEV or PROD:
--   - the agent's role (PUBLIC) gets no grant on OPS, so the agent can neither read nor write it;
--   - eval history survives when DEV or PROD tables are re-created or re-cloned.

USE ROLE SYSADMIN;
USE WAREHOUSE AGENT_WH;

CREATE SCHEMA IF NOT EXISTS MINI_AGENT.OPS;

CREATE TABLE IF NOT EXISTS MINI_AGENT.OPS.EVAL_RUNS (
    run_id              STRING        NOT NULL,  -- one id per eval run or per release
    run_at              TIMESTAMP_TZ  NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    run_type            STRING        NOT NULL,  -- 'eval' (one row per question) | 'release'
    git_commit          STRING,                  -- short sha, '+dirty' if uncommitted changes
    release_tag         STRING,                  -- e.g. v2026.10.08-1 (release rows)
    model               STRING,                  -- pinned model id, e.g. claude-opus-5-5
    experiment_name     STRING,                  -- LangSmith experiment, links the two eval paths
    question_name       STRING,                  -- golden.yaml name (eval rows)
    category            STRING,                  -- answer | out_of_scope | clarify | unsafe
    execution_match     BOOLEAN,                 -- NULL = not applicable (should abstain)
    abstained_correctly BOOLEAN,
    latency_ms          NUMBER,
    total_tokens        NUMBER,
    error_type          STRING                   -- NULL, or e.g. 'validation', 'execution', 'auth'
);

-- Check
SELECT * FROM MINI_AGENT.OPS.EVAL_RUNS ORDER BY run_at DESC LIMIT 10;
