"""Run the golden set as a LangSmith experiment.

Run:  uv run python -m evals.run_langsmith                 (experiment prefix "baseline")
      uv run python -m evals.run_langsmith route-llm       (any prefix, e.g. after a prompt change)
      uv run python -m evals.run_langsmith --recreate      (re-upload after editing golden.yaml)

1. Dataset: golden.yaml -> LangSmith dataset. Reference rows come from running each expected_sql
   in Snowflake under the agent's role, so the row access policy applies to the truth as well.
2. Target: the agent graph, run on one question at a time.
3. Evaluators: execution_match and abstained_correctly score every run; LangSmith stores the scores.
"""

import subprocess
import sys
import uuid
from pathlib import Path

import yaml
from langsmith import Client, evaluate

from agent.db import run_query
from agent.graph import build_graph
from agent.nodes import MODEL
from evals.evaluators import abstained_correctly, execution_match, normalise_value
from evals.gate import THRESHOLDS, average_scores, failed_gates

GOLDEN_PATH = Path(__file__).parent / "golden.yaml"
DATASET_NAME = "mini-analytics-agent-golden"


def json_safe(rows: list[dict] | None) -> list[dict] | None:
    """Snowflake returns Decimal / date / numpy values; LangSmith stores JSON. Same rules as the
    evaluators, so the reference rows and the agent's rows are converted identically."""
    if rows is None:
        return None
    return [{col: normalise_value(v) for col, v in row.items()} for row in rows]


def git_commit() -> str:
    """Short commit hash, with '+dirty' if there are uncommitted changes (results then are not
    reproducible from the commit alone)."""
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    return sha.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")


def ensure_dataset(client: Client, recreate: bool) -> None:
    """Upload golden.yaml once. Reusing the same dataset keeps experiments comparable."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        if not recreate:
            print(f"Reusing dataset '{DATASET_NAME}' (pass --recreate after editing golden.yaml)")
            return
        client.delete_dataset(dataset_name=DATASET_NAME)

    golden = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))["examples"]
    examples = []
    for ex in golden:
        rows = None
        if not ex["should_abstain"]:
            df = run_query(ex["expected_sql"], request_id=f"golden-{ex['name']}")
            rows = json_safe(df.to_dict(orient="records"))
        examples.append(
            {
                "inputs": {"question": ex["question"]},
                "outputs": {"rows": rows, "should_abstain": ex["should_abstain"]},
                "metadata": {"name": ex["name"], "category": ex["category"], "tests": ex["tests"]},
            }
        )

    dataset = client.create_dataset(DATASET_NAME, description="Golden questions, synthetic data")
    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"Uploaded {len(examples)} examples to '{DATASET_NAME}'")


APP = build_graph()


def target(inputs: dict) -> dict:
    """Run the agent on one golden question. LangSmith passes the example's inputs."""
    state = APP.invoke({"question": inputs["question"], "request_id": uuid.uuid4().hex})
    return {
        "rows": json_safe(state.get("rows")),
        "abstained": bool(state.get("abstained", False)),
        "answer": state.get("answer", ""),
        "sql": state.get("validated_sql"),
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prefix = args[0] if args else "baseline"

    # One Snowflake login (MFA prompt) BEFORE LangSmith starts printing progress.
    run_query("SELECT 1", request_id="eval-warmup")

    client = Client()
    ensure_dataset(client, recreate="--recreate" in sys.argv)

    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[execution_match, abstained_correctly],
        experiment_prefix=prefix,
        metadata={"git_commit": git_commit(), "model": MODEL},
        # One question at a time: all runs share ONE Snowflake session, and QUERY_TAG is a
        # session setting, so parallel runs would tag each other's queries.
        max_concurrency=1,
    )
    print(f"\nDone. Open the experiment '{results.experiment_name}' in LangSmith.")

    # Merge gate: exit code 1 turns the CI job red and blocks the pull request.
    averages = average_scores(results)
    for key, minimum in THRESHOLDS.items():
        print(f"  {key}: {averages.get(key, float('nan')):.2f}  (minimum {minimum:.2f})")
    failures = failed_gates(averages, THRESHOLDS)
    if failures:
        print("GATE FAILED: " + "; ".join(failures))
        sys.exit(1)
    print("GATE PASSED")
