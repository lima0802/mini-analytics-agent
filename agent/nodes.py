"""Graph nodes. Each node takes the state and returns ONLY the keys it changes.

Skeleton: the LLM nodes are stubs that return fixed values, so the graph runs without an LLM
or Snowflake. `validate` is already real. We replace the stubs one by one.
"""

from agent.prompts import format_semantic_context, load_semantic_model
from agent.state import AgentState
from agent.validator import load_allowed_tables, validate_sql

ALLOWED_TABLES = load_allowed_tables()
SEMANTIC_MODEL = load_semantic_model()  # read once at import, not on every question


def route(state: AgentState) -> dict:
    # STUB: later an LLM decides answer / clarify / out_of_scope.
    return {"intent": "answer"}


def retrieve_context(state: AgentState) -> dict:
    """Semantic model as prompt text: full schema + the verified examples closest to the question."""
    return {"context": format_semantic_context(SEMANTIC_MODEL, state["question"])}


def generate_sql(state: AgentState) -> dict:
    # STUB: later the LLM writes SQL from question + context + the last error.
    # The first attempt is deliberately bad, so you can watch the retry loop.
    if not state.get("errors"):
        return {"sql": "DELETE FROM email_sends"}
    return {"sql": "SELECT business_unit, COUNT(*) AS sends FROM email_sends GROUP BY 1"}


def validate(state: AgentState) -> dict:
    result = validate_sql(state["sql"], ALLOWED_TABLES)
    if result.ok:
        return {"validated_sql": result.sql}
    # Clear validated_sql so a stale value from an earlier attempt can never be executed.
    return {"validated_sql": None, "errors": [f"Validation failed: {result.error}"]}


def execute(state: AgentState) -> dict:
    # STUB: later run_query(state["validated_sql"], state["request_id"]) from agent/db.py.
    return {
        "rows": [{"BUSINESS_UNIT": "BU_DE", "SENDS": 50}, {"BUSINESS_UNIT": "BU_UK", "SENDS": 50}]
    }


def synthesize(state: AgentState) -> dict:
    # STUB: later the LLM writes the answer from the rows ONLY (never from its own knowledge).
    return {"answer": f"(stub) Got {len(state['rows'])} rows.", "abstained": False}


def abstain(state: AgentState) -> dict:
    if state.get("intent") == "clarify":
        reason = "Your question is ambiguous. Could you rephrase it more specifically?"
    elif state.get("intent") == "out_of_scope":
        reason = "I can only answer questions about the email-marketing data."
    else:
        reason = f"I could not produce a valid query. Last error: {state['errors'][-1]}"
    return {"answer": reason, "abstained": True}
