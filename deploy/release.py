"""Deploy to PROD: run by the deploy job in CI on every merge to main.

Run:  uv run python -m deploy.release v2026.10.08-1

1. Apply the idempotent SQL files (safe to run on every deploy: CREATE ... IF NOT EXISTS).
   Admin SQL (roles, policies, grants, the PROD schema itself) is NOT applied here: Li runs it by
   hand, so CI never holds the privilege to change who can see what.
2. Upload semantic/semantic_model.yaml to the PROD stage.
3. Record the release (tag, commit, model) in OPS.EVAL_RUNS.

Needs key-pair auth (SNOWFLAKE_PRIVATE_KEY_PATH): CI cannot type an MFA code.
"""

import subprocess
import sys
import uuid
from pathlib import Path

from agent.db import get_connection
from agent.nodes import MODEL

ROOT = Path(__file__).parent.parent
SQL_TO_APPLY = [ROOT / "sql" / "03_eval_runs.sql"]  # idempotent files only
SEMANTIC_MODEL = ROOT / "semantic" / "semantic_model.yaml"
STAGE = "@MINI_AGENT.PROD.SEMANTIC_MODELS"


def apply_sql(cursor, path: Path) -> None:
    # execute_string runs every statement in the file, in order (a cursor runs only one)
    for _ in cursor.connection.execute_string(path.read_text(encoding="utf-8")):
        pass
    print(f"Applied {path.name}")


def upload_semantic_model(cursor) -> None:
    # PUT copies a local file to a Snowflake stage. AUTO_COMPRESS=FALSE keeps it a plain .yaml
    # (readable by Cortex Analyst and by people); OVERWRITE=TRUE replaces the previous release.
    cursor.execute(
        f"PUT file://{SEMANTIC_MODEL.as_posix()} {STAGE} AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
    )
    print(f"Uploaded {SEMANTIC_MODEL.name} to {STAGE}")


def record_release(cursor, release_tag: str, git_commit: str) -> None:
    run_id = uuid.uuid4().hex
    cursor.execute(
        "INSERT INTO MINI_AGENT.OPS.EVAL_RUNS "
        "(RUN_ID, RUN_TYPE, GIT_COMMIT, RELEASE_TAG, MODEL) "
        "VALUES (%s, %s, %s, %s, %s)",
        (run_id, "release", git_commit, release_tag, MODEL),
    )
    print(f"Recorded release {release_tag} in OPS.EVAL_RUNS")


if __name__ == "__main__":
    tag = sys.argv[1]
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    # The role comes from SNOWFLAKE_ROLE, set by the deploy job: SYSADMIN (stand-in for a DEPLOYER
    # role) owns OPS and the PROD stage. The agent itself always runs as PUBLIC (read-only).
    with get_connection().cursor() as cur:
        for sql_file in SQL_TO_APPLY:
            apply_sql(cur, sql_file)
        upload_semantic_model(cur)
        record_release(cur, tag, commit)
    print(f"Deployed {tag} ({commit})")
