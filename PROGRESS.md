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

## Open governance gap (found Wed 7 Oct while writing the golden set)

`BU_RAP` is attached to `EMAIL_SENDS` only. `SEND_PERFORMANCE` has no `business_unit` column and no
policy, so `SELECT SUM(sent) FROM SEND_PERFORMANCE` returns ALL 8 markets to role PUBLIC.
Fix (Li runs it, in `sql/02_policies.sql`): a second row access policy on `SEND_PERFORMANCE` whose body
looks up the send's business_unit in `EMAIL_SENDS` (mapping-table pattern), or expose only a secure
view that joins the two. Until then the golden SQL always joins through `EMAIL_SENDS`.

Day 3 (Wed 7 Oct), external eval in LangSmith:

- `evals/evaluators.py`: `execution_match` (compares result rows, ignores row/column order and names,
  rounds to 4 dp, `None` for should-abstain questions) and `abstained_correctly` (Li wrote it)
- `evals/golden.yaml`: 15 questions (12 answer, 1 out_of_scope, 1 clarify, 1 unsafe), each with a
  `tests:` capability; none copied from the verified queries (avoids few-shot leakage). Li wrote #15.
- `evals/run_langsmith.py`: dataset from golden.yaml (reference rows from Snowflake under PUBLIC),
  `evaluate()` with both evaluators, git commit + model in metadata, `max_concurrency=1` (QUERY_TAG is
  per session)
- `route` is real: `RouteDecision` (Literal intent -> enum), runs AFTER `retrieve_context`, fails closed;
  Li wrote the `clarify` rule. SQL prompt: "return only the columns the question asks for".
- Experiments (one run each, all `+dirty`):
  | experiment | abstained_correctly | execution_match | p50 |
  |---|---|---|---|
  | baseline (route stub) | 0.79 (3 abstain fail) | 1.00 | 5.5s |
  | route-llm | 1.00 | 0.91 (avg question: right value + 2 extra columns) | 7.4s |
  | cols-and-clarify | 1.00 | 1.00 | 7.5s |
  Lessons: 100% on the first run = eval too easy; one run per experiment cannot separate a change from
  LLM variance (use `num_repetitions=3`); refusal must be structural (route), not prose in synthesize.

## Next: Thursday 8 Oct (CI/CD)

Blockers and gaps for CI (check before writing `ci.yml`):
- Snowflake from CI: `db.py` asks for an MFA code with `input()`, impossible in GitHub Actions.
  Needs key-pair auth (admin sets `RSA_PUBLIC_KEY` on the user, see open action at the top).
  Without it, CI can run ruff + pytest only, and the eval gate stays a local step.
- Eval gate: `run_langsmith.py` never fails. Add a threshold check (e.g. both scores >= baseline)
  that ends with `sys.exit(1)`, so the PR job goes red.
- GitHub secrets: `ANTHROPIC_API_KEY` (a CI workspace key), `LANGSMITH_API_KEY` (a Service Key, not
  a personal token), Snowflake account/user/private key.
- Offline tests: add a pytest for the graph with fake LLM nodes (retry cap, clarify -> abstain), so CI
  covers the graph without API keys.

Plan:
- [ ] `.github/workflows/ci.yml`: ruff + pytest on every push; eval as merge gate on PRs
- [ ] Deploy job on merge to main: apply `sql/`, upload the semantic model to `PROD`, tag the release
- [ ] Talk-through: Docker image, staged rollout, rollback

Deferred (after CI/CD):
- [ ] Internal eval: `sql/03_eval_runs.sql` + `evals/run_eval.py` (EVAL_RUNS), LAG regression query,
      check both paths give the same accuracy
- [ ] Break it: remove a synonym, see the regression
- [ ] Fix the governance gap on `SEND_PERFORMANCE` (above)
- [ ] Li: three sentences graph vs ReAct vs plan-and-execute; `verified_by`/`verified_at` on
      `delivered_bu_de_august_2026`

## Interview questions to revisit

Monday 5 Oct (answers to be filled in by Li):
1. Your agent's SQL passed `validate_sql()`. Name three other things that still stop it from deleting data or seeing another market's rows.
2. Why is the validator's error message returned to the LLM instead of just raising an exception, and why do we execute `result.sql` rather than the LLM's original string?
3. A service account must query Snowflake from CI, but MFA is enforced. What are your options, and which would you pick?
4. Why does the model never write against raw tables?
