"""Evaluators: score ONE agent run against ONE golden example.

Written in LangSmith's evaluator format, so `langsmith.evaluate(..., evaluators=[...])` can call
them directly. LangSmith passes arguments by name:
  outputs           what the agent returned: {"rows", "abstained", "answer", "sql"}
  reference_outputs the golden truth:        {"rows", "should_abstain"}
They are plain functions (no LLM, no Snowflake), so pytest and run_eval.py can call them too.
"""

import numbers
from datetime import date

ROUND_DIGITS = 4  # 0.21340001 and 0.2134 count as the same number


def normalise_value(value):
    """One cell -> a comparable value: numbers rounded to floats, dates as ISO strings."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, numbers.Number):  # int, float, Decimal and numpy numbers
        return round(float(value), ROUND_DIGITS)
    if isinstance(value, date):  # date, datetime and pandas Timestamp
        return value.isoformat()
    return str(value).strip()


def normalise_rows(rows: list[dict] | None) -> list[tuple]:
    """Rows -> a sorted list of value tuples, ignoring row order, column names and column order.

    Column names are ignored because the agent may alias a column differently
    (emails_sent vs total_sent) and still be right. The values must match.
    """
    if not rows:
        return []
    # key=repr: values can mix types (None, str, float), which cannot be compared with <
    normalised = [
        tuple(sorted((normalise_value(v) for v in row.values()), key=repr)) for row in rows
    ]
    return sorted(normalised, key=repr)


def execution_match(outputs: dict, reference_outputs: dict) -> dict:
    """Do the agent's result rows equal the golden result rows? Compares results, not SQL text."""
    if reference_outputs["should_abstain"]:
        # No correct rows exist for a question that should be refused: score it as "not applicable"
        # (None) so it does not count for or against execution accuracy.
        return {"key": "execution_match", "score": None, "comment": "n/a: should abstain"}

    actual = normalise_rows(outputs.get("rows"))
    expected = normalise_rows(reference_outputs["rows"])
    comment = f"{len(actual)} rows vs {len(expected)} expected"
    return {"key": "execution_match", "score": actual == expected, "comment": comment}


def abstained_correctly(outputs: dict, reference_outputs: dict) -> dict:
    """Did the agent refuse exactly when it should have?"""
    # Both matching decisions are correct; either mismatch is a failure.
    # In particular, failing to abstain when required is the riskier failure for a
    # governed analytics agent, but both mismatches receive a false score.
    score = outputs["abstained"] == reference_outputs["should_abstain"]
    return {"key": "abstained_correctly", "score": score}
