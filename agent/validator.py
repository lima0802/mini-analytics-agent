"""validate_sql(): the deterministic guardrail between LLM-generated SQL and Snowflake.

Rules, checked in code (never trusted to the prompt):
  1. The SQL parses (Snowflake dialect).
  2. Exactly one statement.
  3. Read-only: a SELECT / WITH / UNION query, with no write or session commands inside.
  4. Only tables listed in the semantic model (CTE names are fine).
  5. A LIMIT no larger than max_rows (added if missing, lowered if too high).
"""

from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

SEMANTIC_MODEL_PATH = Path(__file__).parent.parent / "semantic" / "semantic_model.yaml"
DEFAULT_MAX_ROWS = 1000

# Node types that write data or change the session. Rejected anywhere in the tree.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.Grant, exp.Use, exp.Command,
)  # fmt: skip


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    sql: str | None = None  # SQL to execute (LIMIT enforced), set when ok
    error: str | None = None  # why it failed, sent back to the LLM for a retry


def load_allowed_tables(path: Path = SEMANTIC_MODEL_PATH) -> set[str]:
    """Fully qualified, upper-case table names from the semantic model."""
    with open(path, encoding="utf-8") as f:
        model = yaml.safe_load(f)
    return {table["base_table"].upper() for table in model["tables"]}


def _qualified_name(table: exp.Table, database: str, schema: str) -> str:
    """email_sends -> MINI_AGENT.DEV.EMAIL_SENDS (unqualified names use the session defaults)."""
    return ".".join([table.catalog or database, table.db or schema, table.name]).upper()


def validate_sql(
    sql: str,
    allowed_tables: set[str],
    max_rows: int = DEFAULT_MAX_ROWS,
    database: str = "MINI_AGENT",
    schema: str = "DEV",
) -> ValidationResult:
    # 1. Parse
    try:
        statements = [s for s in sqlglot.parse(sql, read="snowflake") if s is not None]
    except sqlglot.errors.ParseError as e:
        return ValidationResult(ok=False, error=f"SQL does not parse: {e}")

    # 2. Exactly one statement
    # Zero (empty input) or several (e.g. "SELECT 1; DROP TABLE x") are both rejected.
    if len(statements) != 1:
        return ValidationResult(
            ok=False, error=f"Expected exactly one SQL statement, got {len(statements)}."
        )
    tree = statements[0]

    # 3. Read-only
    if not isinstance(tree, exp.Query):
        return ValidationResult(
            ok=False, error=f"Only SELECT queries are allowed, got {tree.key.upper()}."
        )
    forbidden = next(tree.find_all(*FORBIDDEN_NODES), None)
    if forbidden is not None:
        return ValidationResult(
            ok=False, error=f"{forbidden.key.upper()} is not allowed inside a query."
        )

    # 4. Known tables only
    # TABLE(...) functions (e.g. INFORMATION_SCHEMA.QUERY_HISTORY) read outside the catalog.
    if tree.find(exp.TableFromRows) is not None:
        return ValidationResult(ok=False, error="Table functions like TABLE(...) are not allowed.")
    cte_names = {cte.alias.upper() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not table.db and table.name.upper() in cte_names:
            continue  # a reference to a CTE defined in this query, not a real table
        name = _qualified_name(table, database, schema)
        if name not in allowed_tables:
            allowed = ", ".join(sorted(allowed_tables))
            return ValidationResult(
                ok=False, error=f"Unknown table {name}. Allowed tables: {allowed}."
            )

    # 5. Row cap
    limit = tree.args.get("limit")
    value = limit.expression if limit is not None else None
    if not (isinstance(value, exp.Literal) and value.is_int and int(value.name) <= max_rows):
        tree = tree.limit(max_rows)  # missing, not a plain number, or too high

    return ValidationResult(ok=True, sql=tree.sql(dialect="snowflake"))
