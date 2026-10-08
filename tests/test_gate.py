"""Tests for the eval merge gate (evals/gate.py). No LangSmith, no LLM: fake results only."""

from types import SimpleNamespace

from evals.gate import THRESHOLDS, average_scores, failed_gates


def fake_row(**scores) -> dict:
    """One row shaped like langsmith.evaluate() output: evaluator key -> score."""
    results = [SimpleNamespace(key=key, score=score) for key, score in scores.items()]
    return {"evaluation_results": {"results": results}}


def test_average_scores_skips_not_applicable():
    rows = [
        fake_row(execution_match=True, abstained_correctly=True),
        fake_row(execution_match=False, abstained_correctly=True),
        fake_row(execution_match=None, abstained_correctly=False),  # None = should-abstain question
    ]
    averages = average_scores(rows)
    assert averages["execution_match"] == 0.5  # 1 of 2: the None is left out, not counted as 0
    assert averages["abstained_correctly"] == 2 / 3


# --- These pass once Li's TODO in evals/gate.py is done ---------------------


def test_gate_passes_when_all_scores_meet_thresholds():
    assert failed_gates({"abstained_correctly": 1.0, "execution_match": 0.92}, THRESHOLDS) == []


def test_gate_fails_on_one_unsafe_answer():
    failures = failed_gates({"abstained_correctly": 0.93, "execution_match": 1.0}, THRESHOLDS)
    assert len(failures) == 1
    assert "abstained_correctly" in failures[0]


def test_gate_fails_when_an_evaluator_is_missing():
    # Nothing measured is not a pass.
    failures = failed_gates({"execution_match": 1.0}, THRESHOLDS)
    assert any("abstained_correctly" in f for f in failures)
