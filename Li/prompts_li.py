"""Prompt text for the LLM nodes, and the semantic model rendered as plain text for the prompt."""

import re
from pathlib import Path

import yaml

SEMANTIC_MODEL_PATH = Path(__file__).parent / "semantic_model.yaml"

SQL_SYSTEM_PROMPT = """You write one Snowflake SELECT query that answers the user's question.

Rules:
- Use only the tables, columns, joins and metric formulas in the data description below.
- Always use full table names (MINI_AGENT.DEV.<TABLE>).
- Read-only: SELECT (or WITH ... SELECT) only.
- Return your answer by calling the submit_sql tool. Do not answer in plain text.

Data description:
{context}"""

def load_semantic_model(path: Path = SEMANTIC_MODEL_PATH)-> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _words(text: str) -> set[str]:
    """'What was the open rate?' -> {'what', 'was', 'the', 'open', 'rate'}"""
    return set(re.findall(r"[a-z0-9_]+", text.lower()))

def _overlap(a: str, b: str) -> int:
    """How many distinct words two questions share. Higher = more similar."""
    return len(_words(a) & _words(b))

def select_examples(question:str, verified_queries: list[dict], k: int = 2) -> list[dict]:
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

def format_semantic_context(model:dict, question:str) -> str:
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
