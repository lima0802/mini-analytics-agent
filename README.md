Governed text-to-SQL analytics agent on Snowflake with LangGraph, evaluation and CI/CD. Learning project on synthetic data.

## The SQL validator: a runtime guardrail, tested in CI

`validate_sql()` in [agent/validator.py](agent/validator.py) decides whether SQL is safe to run:
SELECT only, one statement, known tables only, no `TABLE(...)` functions, row limit enforced.
The same function is used at two different moments, for two different purposes:

| | At runtime (the agent) | In CI (the tests) |
|---|---|---|
| Where | `validate` node in [agent/nodes.py](agent/nodes.py) | [tests/test_validator.py](tests/test_validator.py), run by [.github/workflows/ci.yml](.github/workflows/ci.yml) |
| When | Every question a user asks | Every push and every pull request |
| Input | The SQL the LLM just wrote (unknown, untrusted) | Fixed example SQL (`DELETE ...`, `SELECT ... LIMIT 5000`, ...) |
| Question it answers | Is **this query** safe to run? | Does **the validator itself** still work correctly? |
| If it fails | The query is blocked; the LLM retries (max 2), then the agent abstains | The pull request goes red; the broken code cannot be merged |

The runtime check is the smoke detector; CI is testing the smoke detector whenever someone
changes the wiring. The agent trusts `validate_sql()` to block a `DELETE` on every run. If a later
edit weakened it, the agent would keep working and look fine until the day the LLM wrote a
`DELETE`. The unit tests catch that at the moment of the code change instead.

The tests need no database, no LLM and no secrets (sqlglot only parses the SQL text), so they are
fast, free and deterministic, and run on every push. The slower, paid LLM evaluation
([evals/](evals/)) checks answer quality and runs on pull requests.

The validator is one layer of several: the read-only Snowflake role, the row access and masking
policies, and the statement timeout still apply even if a query passes validation.

## How the tests, the eval and the gate fit together

Four files, in two separate pairs. They only share the CI workflow:

```
                         ┌──────────────────────── CI: every push (job 2, pytest) ───────────────────────┐
                         │                                                                               │
  agent/validator.py ◄── tests/test_validator.py                  evals/gate.py ◄── tests/test_gate.py   │
  (the guardrail)        tests the validator                       (the rule)        tests the rule      │
        ▲                                                              ▲                                  │
        │ used at runtime                                              │ used after each eval             │
        │                                                              │                                  │
  agent/nodes.py                                              evals/run_langsmith.py                      │
  (validate node, every question)                             (runs the eval, then the gate → exit 1)     │
                                                                       ▲                                  │
                                                                       └── CI: pull requests (job 3)
```

| File | Role | Calls / is called by |
|---|---|---|
| [evals/gate.py](evals/gate.py) | **The rule**: average each evaluator's scores, compare with thresholds | Called by `run_langsmith.py`; tested by `test_gate.py` |
| [evals/run_langsmith.py](evals/run_langsmith.py) | **Runs** the real eval (agent + LLM + Snowflake + LangSmith), then the gate; exits 0 or 1 | Imports `gate.py`; run by job 3 on pull requests |
| [tests/test_gate.py](tests/test_gate.py) | **Tests the rule** with fake results | Imports `gate.py`; run by job 2 on every push |
| [tests/test_validator.py](tests/test_validator.py) | **Tests the SQL guardrail** with real SQL strings | Imports `agent/validator.py`, not `gate.py`; run by job 2 on every push |

`gate.py` sits in the middle of its trio: the real eval uses it to decide pass or fail, and
`test_gate.py` checks that the decision rule itself is right. `test_validator.py` is a separate
pair with `agent/validator.py`; it sits next to `test_gate.py` only because pytest runs everything
in `tests/` together (18 validator tests + 4 gate tests).

The pattern behind both pairs: **every decision that protects something has its own unit test.**
The validator protects the database; the gate protects `main`.

Both test files import the real function, give it a fixed input and assert the output, with no
Snowflake, no LLM and no network. They differ in where the input comes from:

- `test_validator.py` uses **real inputs**, because they are cheap: SQL strings. A pytest fixture
  reads the allowed tables from the real semantic model once; `parametrize` runs one test per SQL
  string.
- `test_gate.py` uses a **fake** (a test double), because the real input comes from
  `langsmith.evaluate()`: slow, paid and external. `SimpleNamespace(key=..., score=...)` has the
  same shape as LangSmith's result objects, which is all the code under test reads (duck typing).

## Why ruff is a CI check

[Ruff](https://docs.astral.sh/ruff/) does two jobs, both run by the `lint` job in
[.github/workflows/ci.yml](.github/workflows/ci.yml):

- `ruff check .` is a **linter**: it reads the code without running it and flags likely bugs and
  risky patterns. Version 0.16 enables a broad default rule set, including pyflakes (`F`),
  bugbear (`B`), pylint (`PL`) and pyupgrade (`UP`).
- `ruff format --check .` is a **formatter check**: it fails if any file is not in the standard
  layout, without changing the file.

Real catches in this project, all before the code ran:

| Rule | What ruff flagged | Why it mattered |
|---|---|---|
| `F841` unused variable | `errors = state.get("errors", [])` left in `execute` after a fix | Leftover from a reducer bug that double-counted retries; dead code that hid the old logic |
| `F821` undefined name | `score` returned by an evaluator while its TODO was still unwritten | Would have crashed on the first eval run; an unfinished function cannot slip through |
| `PLW1510` `subprocess.run` without `check=` | `git rev-parse` in `run_langsmith.py` | A failing git command would silently record an empty commit hash in every experiment |

Why it belongs in CI, as the first and cheapest gate:

- **Fast and free**: about 10 seconds, no secrets, no database, no LLM. It fails before the slower
  checks spend time or money.
- **Catches a different class of error than tests**: tests check the paths they exercise; the
  linter reads every line, including error branches tests rarely reach.
- **Removes style from code review**: formatting is decided by the tool, so reviews discuss logic,
  not spacing. Every file looks the same, whoever (or whatever AI assistant) wrote it.
- **Same result everywhere**: the ruff version is pinned in `uv.lock` and installed with
  `uv sync --frozen`, so local and CI apply exactly the same rules. A ruff upgrade can add rules,
  so it is a deliberate change in its own pull request, not a surprise.

Configuration lives in `[tool.ruff]` in [pyproject.toml](pyproject.toml): line length 100,
Python 3.11 syntax, and `Li/` (hand-written practice copies) excluded.
