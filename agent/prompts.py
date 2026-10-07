"""Prompt text for the LLM nodes, and the semantic model rendered as plain text for the prompt."""

import json
import re
from pathlib import Path

import yaml

SEMANTIC_MODEL_PATH = Path(__file__).parent.parent / "semantic" / "semantic_model.yaml"

SQL_SYSTEM_PROMPT = """You write one Snowflake SELECT query that answers the user's question.

Rules:
- Use only the tables, columns, joins and metric formulas in the data description below.
- Always use full table names (MINI_AGENT.DEV.<TABLE>).
- Read-only: SELECT (or WITH ... SELECT) only.
- Return only the columns the question asks for: no extra helper columns.
- Return your answer by calling the submit_sql tool. Do not answer in plain text.

Data description:
{context}"""

ROUTE_SYSTEM_PROMPT = """You decide what an analytics agent should do with a user's question.
The agent can only run ONE read-only SQL query on the data described below.

Choose one intent:
- answer: the question can be answered from the tables, columns and metrics below. This includes
  new calculations built from those columns (averages, shares, filters, rankings).
- clarify: the question is about this data, but an important detail is missing or ambiguous
    and different reasonable interpretations would produce different numbers (for example, the
    metric, time period, or population is unclear). Ask one concise question to resolve it.
- out_of_scope: the question needs data that is not described below, is not about this data at
  all, or asks to change data (insert, update, delete, drop).

When in doubt between answer and clarify, prefer answer: only clarify when the two readings would
give different numbers. Write `reason` as one sentence for the user; for clarify, make it the
question you would ask them.
Return your decision by calling the submit_route tool.

Data description:
{context}"""

SYNTHESIZE_SYSTEM_PROMPT = """You answer a business question from the result of a SQL query.

Rules:
- Use ONLY the numbers and values in the result rows. Do not add facts, causes, benchmarks
  or numbers that are not in the rows. If the rows do not answer the question, say so.
- Rates are fractions between 0 and 1: show them as percentages with one decimal.
- The data is filtered by the user's access rights: never call a total "company-wide".
- If the result was truncated, say the answer covers only the rows shown.
- Two to four sentences, plain text, no markdown."""

MAX_ROWS_IN_PROMPT = 50  # bound the prompt size; the validator allows up to 1000 rows


def load_semantic_model(path: Path = SEMANTIC_MODEL_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _words(text: str) -> set[str]:
    """'What was the open rate?' -> {'what', 'was', 'the', 'open', 'rate'}"""
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _overlap(a: str, b: str) -> int:
    """How many distinct words two questions share. Higher = more similar."""
    return len(_words(a) & _words(b))


def select_examples(question: str, verified_queries: list[dict], k: int = 2) -> list[dict]:
    """The k verified queries most similar to the question (simple word-overlap retrieval)."""
    ranked = sorted(
        verified_queries, key=lambda vq: _overlap(question, vq["question"]), reverse=True
    )
    return ranked[:k]


def _format_column(col: dict) -> str:
    line = f"    - {col['name']} ({col['data_type']}): {col.get('description', '')}"
    if col.get("synonyms"):
        line += f" Also called: {', '.join(col['synonyms'])}."
    if col.get("sample_values"):
        line += f" Values: {', '.join(col['sample_values'])}."
    return line


def format_semantic_context(model: dict, question: str) -> str:
    """Everything the LLM may know about the data, as compact text."""
    lines = [f"Data: {model['description'].strip()}", "", "Tables (use these full names):"]
    for table in model["tables"]:
        lines.append(f"- {table['base_table']} (alias {table['name']}): {table['description']}")
        columns = (
            table.get("dimensions", []) + table.get("time_dimensions", []) + table.get("facts", [])
        )
        lines += [_format_column(col) for col in columns]

    lines += ["", "Joins (the only allowed join paths):"]
    lines += [
        f"- {rel['join_condition']} ({rel['join_type']} join)" for rel in model["relationships"]
    ]

    lines += ["", "Metrics (always use these exact formulas):"]
    for metric in model["metrics"]:
        synonyms = (
            f" Also called: {', '.join(metric['synonyms'])}." if metric.get("synonyms") else ""
        )
        lines.append(
            f"- {metric['name']} = {metric['expr']}. {metric['description'].strip()}{synonyms}"
        )

    lines += ["", "Verified examples:"]
    for vq in select_examples(question, model["verified_queries"]):
        lines += [f"Question: {vq['question']}", "SQL:", vq["sql"].strip(), ""]

    return "\n".join(lines)


def build_sql_request(question: str, previous_sql: str | None, errors: list[str]) -> str:
    """The user message for generate_sql. On a retry it also carries the last failure."""
    if not errors:
        return question
    return (
        f"Original question: {question}\n\n"
        f"SQL that failed:\n{previous_sql}\n\n"
        f"Most recent error: {errors[-1]}\n\n"
        "Fix the error and call submit_sql again."
    )


def build_synthesize_request(question: str, sql: str, rows: list[dict]) -> str:
    """The user message for synthesize: the question, the SQL that ran, and the rows as JSON."""
    shown = rows[:MAX_ROWS_IN_PROMPT]
    truncated = f" (showing first {len(shown)} of {len(rows)})" if len(rows) > len(shown) else ""
    # default=str: Snowflake returns Decimal and date values, which json cannot serialise itself
    rows_json = json.dumps(shown, default=str, indent=1)
    return f"Question: {question}\n\nSQL that ran:\n{sql}\n\nResult rows{truncated}:\n{rows_json}"
