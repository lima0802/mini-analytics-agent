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

Day 2 (Tue 6 + Wed 7 Oct):

- SQL drill (`sql/drill.sql`): QUALIFY + ROW_NUMBER, LAG, running total with frame clause, top-N per group
- LLM provider: Anthropic, official `anthropic` SDK, model `claude-opus-5-5`. Key in a workspace-scoped
  Console key (`ANTHROPIC_API_KEY`). Org-level keys need an `anthropic-workspace-id` header.
- `agent/state.py`: `TypedDict` state, `errors` with `operator.add` reducer = retry history
- `agent/nodes.py`:
  - `generate_sql`: function calling. Tool `submit_sql` with `strict: true`, schema from Pydantic
    `GeneratedSQL`. Forced `tool_choice` is a 400 on Opus 5.5, so the prompt asks and the code checks.
  - `validate` (real), `execute` (Snowflake via `run_query`, `ProgrammingError` -> `errors`; Li fixed a
    reducer double-count bug), `synthesize` (rows only, effort low, empty result answered without LLM)
  - `call_claude()` + `@traceable`: langsmith's `wrap_anthropic` breaks on anthropic 1.x (patches the
    removed `client.completions`), so we trace our own call site with `usage_metadata`
- `agent/graph.py`: retry cap 2 then abstain (verified: 3 attempts, 3 errors, abstained), print full
  state after every node (`stream_mode=["updates", "values"]`), question from the command line,
  `request_id` in LangSmith metadata and Snowflake QUERY_TAG
- First real end-to-end run: Claude SQL -> sqlglot -> Snowflake (only BU_UK, BU_DE via `BU_RAP`) -> answer
- LangSmith tracing on; trace inspected: generate_sql 4.98s / 2,356 tokens, synthesize 2.05s,
  execute 277s = waiting for the MFA code (lazy connection; cold start, not Snowflake)

Lessons worth telling:
- Synthesis once said "delivered" for an `EMAILS_SENT` column; the next run said "sent". Right numbers,
  wrong meaning, intermittent: needs an eval on faithfulness, not just on SQL results.
- Auth errors (`DatabaseError`) are not retried: the LLM cannot fix them. Retry only what the model can fix.
- `load_dotenv()` does not override existing env vars, and an EMPTY inherited var still counts as set
  (VS Code had loaded the old empty `LANGSMITH_API_KEY`). Restart VS Code after changing `.env`.

## Next: Wednesday 7 Oct (evals)

- [ ] `evals/evaluators.py`: `execution_match()` (order-insensitive) and `abstained_correctly()`
- [ ] `evals/golden.yaml`: 15 verified questions, 3 to refuse or clarify
- [ ] `evals/run_langsmith.py`: dataset + `evaluate()` with both evaluators (warm the Snowflake connection
      first so MFA is asked once). Baseline experiment = `route` still a stub.
- [ ] Make `route` real (LLM classifier, same function-calling pattern) = the "change one prompt"
      experiment; compare the two experiments in the UI (the 3 refusal questions should flip)
- [ ] `sql/03_eval_runs.sql` + `evals/run_eval.py` (EVAL_RUNS), LAG regression query
- [ ] Break it: remove a synonym, see the regression in both places
- [ ] Still open from Day 2: run the 3 tests (out of scope, ambiguous, DELETE) with a real `route`;
      Li writes three sentences: graph vs ReAct vs plan-and-execute; add `verified_by`/`verified_at` to
      Li's verified query `delivered_bu_de_august_2026`

## Later

- Thursday 8 Oct: CI (ruff, pytest, eval gate), CD to prod schema, release tag, rollout talk-through.
  CI needs key-pair auth for Snowflake (see open action above) and a LangSmith Service Key.

## Interview questions to revisit

Monday 5 Oct (answers to be filled in by Li):
1. Your agent's SQL passed `validate_sql()`. Name three other things that still stop it from deleting data or seeing another market's rows.
2. Why is the validator's error message returned to the LLM instead of just raising an exception, and why do we execute `result.sql` rather than the LLM's original string?
3. A service account must query Snowflake from CI, but MFA is enforced. What are your options, and which would you pick?
4. Why does the model never write against raw tables?
