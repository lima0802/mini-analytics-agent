"""Tests for validate_sql(). No Snowflake connection needed: the validator is pure Python."""

import pytest

from agent.validator import load_allowed_tables, validate_sql


@pytest.fixture(scope="module")
def allowed() -> set[str]:
    """Allowed tables, read once from the real semantic model."""
    return load_allowed_tables()


# --- Accepted queries -------------------------------------------------------


def test_missing_limit_is_added(allowed):
    result = validate_sql("SELECT * FROM email_sends", allowed)
    assert result.ok
    assert result.sql.endswith("LIMIT 1000")


def test_small_limit_is_kept(allowed):
    result = validate_sql("SELECT * FROM email_sends LIMIT 10", allowed)
    assert result.ok
    assert result.sql.endswith("LIMIT 10")


def test_large_limit_is_capped(allowed):
    result = validate_sql("SELECT * FROM MINI_AGENT.DEV.EMAIL_SENDS LIMIT 5000", allowed)
    assert result.ok
    assert result.sql.endswith("LIMIT 1000")


def test_join_and_cte_are_allowed(allowed):
    sql = """
        WITH perf AS (SELECT * FROM send_performance)
        SELECT s.business_unit, SUM(p.opens) AS opens
        FROM email_sends s JOIN perf p ON s.send_sk = p.send_sk
        GROUP BY s.business_unit
    """
    assert validate_sql(sql, allowed).ok


# --- Rejected queries -------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM email_sends",
        "UPDATE email_sends SET email_type = 'x'",
        "INSERT INTO email_sends SELECT * FROM email_sends",
        "DROP TABLE email_sends",
        "CREATE TABLE copy AS SELECT * FROM email_sends",
        "GRANT SELECT ON email_sends TO ROLE public",
        "USE ROLE SYSADMIN",
        "ALTER SESSION SET QUERY_TAG = 'x'",
    ],
)
def test_write_and_session_commands_are_rejected(allowed, sql):
    result = validate_sql(sql, allowed)
    assert not result.ok
    assert result.sql is None


def test_unknown_table_is_rejected_with_helpful_error(allowed):
    result = validate_sql("SELECT * FROM business_units", allowed)
    assert not result.ok
    assert "MINI_AGENT.DEV.EMAIL_SENDS" in result.error  # tells the LLM what it may use


def test_table_function_is_rejected(allowed):
    result = validate_sql("SELECT * FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())", allowed)
    assert not result.ok


def test_unparseable_sql_is_rejected(allowed):
    assert not validate_sql("SELECT FROM WHERE", allowed).ok


# --- These two pass once Li's TODO in validator.py is done ------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE email_sends",
        "SELECT * FROM email_sends; SELECT * FROM send_performance",
    ],
)
def test_multiple_statements_are_rejected(allowed, sql):
    assert not validate_sql(sql, allowed).ok


def test_empty_sql_is_rejected(allowed):
    assert not validate_sql("", allowed).ok
