"""Snowflake access for the agent: one reused connection, a query tag per request, rows as a DataFrame."""

import json
import os
import uuid
from functools import lru_cache

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector import SnowflakeConnection

load_dotenv()  # copies .env into os.environ (variables already set in the shell win)

APP_NAME = "mini-analytics-agent"


def _auth_kwargs() -> dict[str, str]:
    """Key-pair auth when a key path is set; otherwise password + MFA code (TOTP)."""
    key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        return {"private_key_file": key_path}
    # This account enforces MFA on password logins, so we also need the 6-digit
    # code from the authenticator app. Asked once per process (the connection is cached).
    passcode = input("Snowflake MFA code (6 digits): ").strip()
    return {"password": os.environ["SNOWFLAKE_PASSWORD"], "passcode": passcode}


@lru_cache(maxsize=1)
def get_connection() -> SnowflakeConnection:
    """Log in once per process and reuse the connection (login takes about a second)."""
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 60},
        **_auth_kwargs(),
    )
    # Only the primary role's privileges count, so SYSADMIN cannot leak in as a secondary role.
    with conn.cursor() as cur:
        cur.execute("USE SECONDARY ROLES NONE")
    return conn


def build_query_tag(request_id: str) -> str:
    """Query tag stored by Snowflake on every query, so we can find them in QUERY_HISTORY."""
    return json.dumps({"app": APP_NAME, "request_id": request_id})


def run_query(sql: str, request_id: str | None = None) -> pd.DataFrame:
    """Run one SQL statement tagged with the request id and return the rows as a DataFrame."""
    request_id = request_id or uuid.uuid4().hex
    conn = get_connection()
    with conn.cursor() as cur:
        # QUERY_TAG is a session setting, so we set it before each request's query.
        cur.execute("ALTER SESSION SET QUERY_TAG = %s", (build_query_tag(request_id),))
        cur.execute(sql)
        return cur.fetch_pandas_all()


if __name__ == "__main__":
    # Smoke test: python -m agent.db
    print(
        run_query("SELECT CURRENT_USER() AS usr, CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS wh")
    )
    print(
        run_query(
            "SELECT business_unit, COUNT(*) AS sends FROM EMAIL_SENDS "
            "GROUP BY business_unit ORDER BY business_unit"
        )
    )
