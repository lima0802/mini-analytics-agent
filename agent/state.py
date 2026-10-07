"""The agent's state: one typed dict that every node reads and partially updates.

Each node returns only the keys it changes; LangGraph merges that update into the state.
"""

import operator
from typing import Annotated, Literal, Required, TypedDict

Intent = Literal["answer", "clarify", "out_of_scope"]


class AgentState(TypedDict, total=False):  # total=False: keys appear as nodes fill them in
    # Input (the only keys the caller must provide)
    question: Required[str]
    request_id: str

    # route: can we answer this from our data?
    intent: Intent
    route_reason: str  # one sentence from the router; for clarify, the question to ask the user

    # retrieve_context: the parts of the semantic model the LLM gets to see
    context: str

    # generate_sql -> validate
    sql: str  # raw SQL from the LLM (untrusted)
    sql_reasoning: str  # the LLM's one-line why, from the tool arguments (for debugging and traces)
    validated_sql: str | None  # SQL that passed validate_sql(); the ONLY SQL we execute

    # Every failed attempt (validation or execution) appends one message.
    # The reducer operator.add appends instead of overwriting, so the list is the retry history.
    errors: Annotated[list[str], operator.add]

    # execute
    rows: list[dict] | None  # result rows as plain dicts (JSON-friendly for tracing)

    # synthesize / abstain
    answer: str
    abstained: bool
