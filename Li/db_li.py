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

APP_NAME = 'mini-analytics-agent'

def _auth_kwargs() -> dict[str,str]:
   """key-pair auth when a key path is set; password only as a fallback."""
   key_path = os.getenv("SNOWFLAKE_KEY_PATH")
   if key_path:
       return {
           "private_key_file": key_path}
   return {"private_key_file": os.getenv("SNOWFLAKE_PASSWORD")}

@lru_cache
def get_connection() -> SnowflakeConnection:
    """Log in once per process and reuse the connection (login takes about a second)."""
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        role=os.getenv("SNOWFLAKE_ROLE"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        session_parameters={
            "STATEMENT_TIMEOUT_IN_SECONDS": 60  # set timeout to 60 seconds
        },
        **_auth_kwargs(),
    )
    # Only the primary role's privileges are applied; so SYSADMIN cannot leak in as a secondary role.
    with conn.cursor() as cur:
        cur.execute("USE SECONDARY ROLES NONE")
    return conn

def build_query_tag(request_id: str) -> str:
    """Build a query tag for Snowflake queries."""
    return json.dumps({"app": APP_NAME, "request_id": request_id})

def run_query(sql: str, request_id: str | None = None) -> pd.DataFrame:
    """Run a query against Snowflake and return the results as a DataFrame."""
    request_id = request_id or str(uuid.uuid4())
    query_tag = build_query_tag(request_id)
    conn = get_connection()
    with conn.cursor() as cur:
        # QUERY_TAG is a session setting, so we set it before each request's query.
        cur.execute("ALTER SESSION SET QUERY_TAG = %s", (build_query_tag(request_id),))
        cur.execute(sql)
        return cur.fetch_pandas_all()

if __name__ == "__main__":
    # Smoke test: python -m agent.db
    print(run_query("SELECT CURRENT_USER() AS usr, CURRENT_ROLE() AS role, CURRENT_WAREHOUSE() AS wh"))
    print(
            run_query(
                "SELECT business_unit, COUNT(*) AS sends FROM EMAIL_SENDS "
                "GROUP BY business_unit ORDER BY business_unit"
            )
        )
