"""Graph nodes. Each node takes the state and returns ONLY the keys it changes.

All nodes are real. LLM nodes (route, generate_sql, synthesize) go through call_claude().
"""

from functools import lru_cache
from typing import Literal

import anthropic
import snowflake.connector
from dotenv import load_dotenv
from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from agent.db import run_query
from agent.prompts import (
    ROUTE_SYSTEM_PROMPT,
    SQL_SYSTEM_PROMPT,
    SYNTHESIZE_SYSTEM_PROMPT,
    build_sql_request,
    build_synthesize_request,
    format_semantic_context,
    load_semantic_model,
)
from agent.state import AgentState
from agent.validator import load_allowed_tables, validate_sql

ALLOWED_TABLES = load_allowed_tables()
SEMANTIC_MODEL = load_semantic_model()  # read once at import, not on every question

MODEL = "claude-opus-5-5"


class GeneratedSQL(BaseModel):
    """Arguments of the submit_sql tool: the exact shape Claude must fill in."""

    # extra="forbid" -> "additionalProperties": false in the schema (strict tools require it)
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(description="One sentence: which tables, metric and filters you used.")
    sql: str = Field(description="One Snowflake SELECT statement that answers the question.")


# The tool definition sent to Claude. The schema is generated from the Pydantic model,
# so the model class is the single source of truth for the arguments.
SUBMIT_SQL_TOOL = {
    "name": "submit_sql",
    "description": "Submit the single Snowflake SELECT query that answers the user's question.",
    "strict": True,  # the API guarantees Claude's arguments match input_schema
    "input_schema": GeneratedSQL.model_json_schema(),
}


class RouteDecision(BaseModel):
    """Arguments of the submit_route tool."""

    model_config = ConfigDict(extra="forbid")

    # Literal -> "enum" in the JSON schema: Claude can only pick one of these three strings.
    intent: Literal["answer", "clarify", "out_of_scope"]
    reason: str = Field(description="One sentence for the user. For clarify: the question to ask.")


SUBMIT_ROUTE_TOOL = {
    "name": "submit_route",
    "description": "Submit the routing decision for the user's question.",
    "strict": True,
    "input_schema": RouteDecision.model_json_schema(),
}


@lru_cache(maxsize=1)
def get_llm() -> anthropic.Anthropic:
    """One client per process, created on first use (so importing this module needs no key)."""
    load_dotenv()
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def _trace_outputs(response) -> dict:
    """What LangSmith stores for the llm run: the message plus token usage it can display."""
    usage = response.usage
    return {
        "message": response.model_dump(),
        "usage_metadata": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
        },
    }


# langsmith's wrap_anthropic() fails with anthropic 1.x (it still patches the removed
# client.completions), so we trace the one call site ourselves. With LANGSMITH_TRACING=true,
# every call becomes an "llm" run inside the node's trace: prompt, response, tokens, latency.
@traceable(
    run_type="llm",
    name="claude",
    process_outputs=_trace_outputs,
    metadata={"ls_provider": "anthropic", "ls_model_name": MODEL},
)
def call_claude(**kwargs):
    """Every Claude call in the agent goes through here (shared settings + tracing)."""
    return get_llm().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        # If a safety classifier declines, the API retries on a fallback model inside the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        **kwargs,
    )


def route(state: AgentState) -> dict:
    """Claude decides answer / clarify / out_of_scope BEFORE any SQL is written."""
    response = call_claude(
        system=ROUTE_SYSTEM_PROMPT.format(context=state["context"]),
        messages=[{"role": "user", "content": state["question"]}],
        tools=[SUBMIT_ROUTE_TOOL],
        output_config={"effort": "low"},  # a 3-way classification: low effort is enough
    )
    tool_call = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "submit_route"), None
    )
    if tool_call is None:
        # No decision came back: fail closed (refuse) rather than guess "answer".
        return {"intent": "out_of_scope", "route_reason": "I could not classify this question."}
    decision = RouteDecision.model_validate(tool_call.input)
    return {"intent": decision.intent, "route_reason": decision.reason}


def retrieve_context(state: AgentState) -> dict:
    """Semantic model as prompt text: full schema + the verified examples closest to the question."""
    return {"context": format_semantic_context(SEMANTIC_MODEL, state["question"])}


def generate_sql(state: AgentState) -> dict:
    """Claude writes SQL by calling the submit_sql tool. We read the typed arguments, not free text."""
    user_message = build_sql_request(state["question"], state.get("sql"), state.get("errors", []))
    response = call_claude(
        system=SQL_SYSTEM_PROMPT.format(context=state["context"]),
        messages=[{"role": "user", "content": user_message}],
        tools=[SUBMIT_SQL_TOOL],
        # Forcing the tool (tool_choice "tool"/"any") is a 400 on this model: the prompt asks for it,
        # and below we check whether the call actually came back.
        output_config={"effort": "medium"},  # thinking is always on for Opus 5.5; effort sets depth
    )

    tool_call = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "submit_sql"), None
    )
    if tool_call is None:
        # Refused, or answered in prose. Empty SQL fails validation, which records the error
        # and spends one retry: the same path as bad SQL, no special case in the graph.
        return {"sql": "", "sql_reasoning": f"No tool call (stop_reason={response.stop_reason})"}

    # dict -> typed object; raises ValidationError if the arguments do not match the schema
    args = GeneratedSQL.model_validate(tool_call.input)
    return {"sql": args.sql, "sql_reasoning": args.reasoning}


def validate(state: AgentState) -> dict:
    result = validate_sql(state["sql"], ALLOWED_TABLES)
    if result.ok:
        return {"validated_sql": result.sql}
    # Clear validated_sql so a stale value from an earlier attempt can never be executed.
    return {"validated_sql": None, "errors": [f"Validation failed: {result.error}"]}


def execute(state: AgentState) -> dict:
    """Run the VALIDATED SQL (never the raw LLM string) under the agent's read-only role."""
    try:
        df = run_query(state["validated_sql"], state.get("request_id"))
    except snowflake.connector.errors.ProgrammingError as e:
        return {"rows": None, "errors": [f"Execution failed: {e.msg}"]}
    # DataFrame -> list of dicts: [{"BUSINESS_UNIT": "BU_DE", "SENDS": 50}, ...]
    return {"rows": df.to_dict(orient="records")}


def synthesize(state: AgentState) -> dict:
    """Claude writes the answer from the result rows ONLY (never from its own knowledge)."""
    rows = state["rows"]
    if not rows:
        return {"answer": "The query returned no results.", "abstained": False}

    response = call_claude(
        system=SYNTHESIZE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_synthesize_request(
                    state["question"], state["validated_sql"], rows
                ),
            }
        ],
        output_config={"effort": "low"},  # summarising a small table: low effort is enough
    )
    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"answer": answer or "I could not summarise the result.", "abstained": False}


def abstain(state: AgentState) -> dict:
    if state.get("intent") == "clarify":
        reason = state.get("route_reason") or "Your question is ambiguous. Could you rephrase it?"
    elif state.get("intent") == "out_of_scope":
        default = "I can only answer questions about the email-marketing data."
        reason = state.get("route_reason") or default
    else:
        reason = f"I could not produce a valid query. Last error: {state['errors'][-1]}"
    return {"answer": reason, "abstained": True}
