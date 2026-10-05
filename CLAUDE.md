# Mini analytics agent: 4-day practice project

## Who I am and why this exists

I am Li, a senior data and AI consultant. I have an interview on Friday 9 Oct for a senior AI engineer role building a conversational analytics (text-to-SQL) agent on Snowflake. I have built a similar system before at architecture level. This repo is a from-scratch miniature rebuild so that I understand every line of the Python, and so that I practise evaluation, observability and CI/CD hands-on.

The goal is my understanding, not finished code. I have 1.5 to 2 hours per day, Monday 5 Oct to Thursday 8 Oct.

## How to work with me (important)

- Work in small steps: one file or one function at a time. Stop after each step and wait for me.
- Before writing code, say in two or three sentences what we are about to build and why.
- After writing code, explain the Python constructs used (type hints, Pydantic, TypedDict, decorators, fixtures, context managers, async) as if I will be asked about them in an interview.
- Prefer plain, readable Python over clever abstractions. No extra frameworks beyond the stack below.
- Leave one small piece of each step for me to write myself (mark it `# TODO(Li)`), then review what I wrote.
- At the end of each session, ask me three interview-style questions about what we built, and update `PROGRESS.md` with what is done and what is next.
- Keep to the day's scope. If I drift, remind me of the time box.
- If you are unsure about a current API (LangGraph, LangSmith, Snowflake), check the installed version or the docs instead of guessing.
- At the start of each session, read `PROGRESS.md` first and pick up from "Next".

## Stack

- Python 3.11+, uv or venv + pip
- Snowflake (my own account, synthetic tables only), `snowflake-connector-python`, key-pair auth
- `sqlglot` (Snowflake dialect) for SQL validation
- `pydantic` for typed tool arguments
- `langgraph` for orchestration; one LLM provider via its official SDK or LangChain chat model (key in `.env`)
- `langsmith` for external tracing and evaluation
- `pytest`, `ruff`
- GitHub Actions for CI and CD

## Safety rules

- All data is synthetic. Never add real client data, names or schemas.
- Secrets live only in `.env` (git-ignored) and GitHub repo secrets. Never print or commit keys.
- The agent connects only with the read-only role `AGENT_RO`. Admin SQL (roles, policies) lives in `sql/` and I run it myself.
- Generated SQL must pass `validate_sql()` before execution: SELECT only, known objects only, LIMIT enforced.

## My Snowflake objects

- Account: see `.env` (not committed) / database `MINI_AGENT` / dev schema `DEV`
- Prod schema (created Thursday): `PROD`
- Warehouse `AGENT_WH`. Agent connects as `LIMA` with role `PUBLIC` (see account constraints in `PROGRESS.md`).
- Synthetic tables (created by `sql/00_seed.sql`):
  - `BUSINESS_UNITS`: business_unit (BU_UK ... BU_PL), country_name, region. Deliberately NOT in the semantic model.
  - `EMAIL_SENDS`: send_sk (PK), send_id, business_unit, send_date, email_type, owner_email (masked)
  - `SEND_PERFORMANCE`: send_sk (PK/FK), sent, delivered, bounces, opens, clicks, unsubscribes

## Target repo layout

```
sql/                  01_roles.sql, 02_policies.sql, 03_eval_runs.sql
semantic/             semantic_model.yaml
agent/                db.py, validator.py, state.py, nodes.py, graph.py, prompts.py
evals/                golden.yaml, evaluators.py, run_eval.py, run_langsmith.py
tests/                test_validator.py
.github/workflows/    ci.yml
PROGRESS.md  .env.example  pyproject.toml
```

## Plan by day

### Monday 5 Oct: Snowflake foundation and the deterministic core

1. `sql/01_roles.sql`: `AGENT_RO` role (SELECT on dev schema), service user with key-pair auth, XS warehouse with statement timeout and 60s auto-suspend.
2. `sql/02_policies.sql`: one row access policy and one masking policy; a query to run under two roles to see the difference.
3. `agent/db.py`: connect, set a query tag per request, return a DataFrame.
4. `semantic/semantic_model.yaml`: tables, metrics, dimensions, joins, synonyms, verified queries.
5. `agent/validator.py` + `tests/test_validator.py`: `validate_sql()` with sqlglot.
6. SQL drill: I write QUALIFY + ROW_NUMBER, LAG, running total, top-N per group by hand; you review.

### Tuesday 6 Oct: the agent in LangGraph

1. `agent/state.py`: typed state.
2. `agent/nodes.py`: route, retrieve semantic context, generate SQL (function calling with a Pydantic schema), validate, execute, synthesize (from the result only), abstain.
3. `agent/graph.py`: StateGraph, conditional edge that retries on validation or execution error (cap 2), then abstains.
4. Turn on LangSmith tracing; inspect one trace.
5. Test three questions: out of scope, ambiguous, and one that tries a DELETE.
6. I write three sentences: graph vs ReAct vs plan-and-execute.

### Wednesday 7 Oct: evaluation and observability, internal and external

1. `evals/evaluators.py`: `execution_match()` (compare result sets, order-insensitive) and `abstained_correctly()`.
2. `evals/golden.yaml`: 15 verified questions, 3 of which should be refused or clarified.
3. `sql/03_eval_runs.sql` + `evals/run_eval.py`: write one row per question to `EVAL_RUNS` (run id, git commit, pass/fail, latency, tokens, error type).
4. Regression query with LAG: questions that flipped from pass to fail.
5. `evals/run_langsmith.py`: same golden set as a LangSmith dataset, same evaluators; compare two experiments after a prompt change.
6. Break it: remove a synonym, see the regression in both places.

### Thursday 8 Oct: CI, CD, rehearsal

1. `.github/workflows/ci.yml`: ruff; pytest on the validator (every push); eval as merge gate on PRs (fail below threshold or last baseline).
2. Deploy job on merge to main: apply `sql/` and upload the semantic model to the prod schema; tag the release; record the tag in `EVAL_RUNS`.
3. Talk through (no build): Docker image for the agent, staged rollout, rollback.

## Definition of done for each step

The code runs, I can explain every line aloud, and `PROGRESS.md` is updated.
