# Progress

Interview: Friday 9 Oct. Time box: 1.5 to 2 hours per day. Full plan in `CLAUDE.md`.

## Account constraints (found Monday 5 Oct)

- No USERADMIN / SECURITYADMIN: cannot create `AGENT_RO` or `AGENT_SVC`. `01_roles.sql` sections 2-4 kept as the target design, not run.
- Stand-in: the agent connects as `LIMA` with role `PUBLIC` (read-only on `MINI_AGENT`), secondary roles off.
- No `MODIFY PROGRAMMATIC AUTHENTICATION METHODS` on `LIMA`: cannot register the public key. MFA (TOTP) is enforced on password logins.
  Local dev: password + 6-digit MFA code typed once per run (`db.py` prompts for it).
- **Open action for Li:** ask the Snowflake admin to run `ALTER USER LIMA SET RSA_PUBLIC_KEY = '...'` (or grant the privilege). Without it, Thursday's CI cannot log in to Snowflake.
- uv env lives outside OneDrive (`UV_PROJECT_ENVIRONMENT=C:\Users\LiMa\.venvs\mini-analytics-agent`). Delete the stray `.venv` in the repo after restarting VS Code.

## Done

- Repo scaffolding, `CLAUDE.md`, `pyproject.toml` (uv, ruff, pytest)
- `sql/01_roles.sql`: XS warehouse `AGENT_WH` (60s statement timeout, 60s auto-suspend), database `MINI_AGENT.DEV`
- `sql/00_seed.sql`: synthetic SFMC-style data: `BUSINESS_UNITS` (8), `EMAIL_SENDS` (400), `SEND_PERFORMANCE` (400)
- Removed a copy of real client data from the project and switched to synthetic data (good interview story: "a sample is still client data")
- `sql/02_policies.sql`: row access policy `BU_RAP` (PUBLIC sees BU_UK, BU_DE) + masking policy `EMAIL_MASK` (Li wrote the body). Compared SYSADMIN vs PUBLIC.
- `agent/db.py`: connect, query tag per request (Li wrote `build_query_tag`), DataFrame out. Smoke test OK: `LIMA | PUBLIC | AGENT_WH`, only BU_DE and BU_UK.
- `semantic/semantic_model.yaml`: 2 tables, relationship, 5 metrics, synonyms, sample values, 4 verified queries (Li wrote one)
- `agent/validator.py` + `tests/test_validator.py`: parse, one statement, read-only, known tables, no `TABLE(...)` functions, row cap. 18 tests pass.

## Next: Tuesday 6 Oct

- [ ] 15 min: SQL drill moved from Monday: QUALIFY + ROW_NUMBER, LAG, running total, top-N per group (Li writes, Claude reviews)
- [ ] Tidy: copy fixes from review into practice file or delete `agent/db_li.py` (ruff fails on it); add `verified_by`/`verified_at` to Li's verified query
- [ ] Decide the LLM provider; add `LLM_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT` to `.env` and `.env.example` (names only)
- [ ] `agent/state.py`: typed state
- [ ] `agent/nodes.py`: route, retrieve semantic context, generate SQL (Pydantic schema), validate, execute, synthesize, abstain
- [ ] `agent/graph.py`: StateGraph, retry on validation/execution error (cap 2), then abstain
- [ ] LangSmith tracing on; inspect one trace
- [ ] Test: out of scope, ambiguous ("how many sends?"), and a DELETE attempt
- [ ] Li writes three sentences: graph vs ReAct vs plan-and-execute

## Later

- Wednesday 7 Oct: evaluators, golden set, `EVAL_RUNS`, regression query, LangSmith experiments
- Thursday 8 Oct: CI (ruff, pytest, eval gate), CD to prod schema, release tag, rollout talk-through

## Interview questions to revisit

Monday 5 Oct (answers to be filled in by Li):
1. Your agent's SQL passed `validate_sql()`. Name three other things that still stop it from deleting data or seeing another market's rows.
2. Why is the validator's error message returned to the LLM instead of just raising an exception, and why do we execute `result.sql` rather than the LLM's original string?
3. A service account must query Snowflake from CI, but MFA is enforced. What are your options, and which would you pick?
