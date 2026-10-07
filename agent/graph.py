"""Wire the nodes into a LangGraph StateGraph.

START -> route --answer--> retrieve_context -> generate_sql -> validate --ok--> execute --ok--> synthesize -> END
           |                                       ^              |               |
           +--clarify / out_of_scope--+            +----error-----+-----error-----+   (max MAX_RETRIES retries)
                                      v                           |               |
                                   abstain <------- too many -----+---------------+
                                      |
                                     END
"""

import sys
import uuid

from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.state import AgentState

MAX_RETRIES = 2  # 1 first attempt + 2 retries, then abstain
MAX_CHARS = 200  # print_state: shorten long values (the semantic context is ~3000 chars)


# --- Conditional edges: plain functions that read the state and return the NEXT node's name ---


def after_route(state: AgentState) -> str:
    return "retrieve_context" if state["intent"] == "answer" else "abstain"


def after_validate(state: AgentState) -> str:
    # Written by Li.
    if state["validated_sql"] is not None:
        return "execute"
    return "generate_sql" if len(state.get("errors", [])) <= MAX_RETRIES else "abstain"


def after_execute(state: AgentState) -> str:
    if state.get("rows") is not None:
        return "synthesize"
    if len(state.get("errors", [])) <= MAX_RETRIES:
        return "generate_sql"
    return "abstain"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("route", nodes.route)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("generate_sql", nodes.generate_sql)
    graph.add_node("validate", nodes.validate)
    graph.add_node("execute", nodes.execute)
    graph.add_node("synthesize", nodes.synthesize)
    graph.add_node("abstain", nodes.abstain)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["retrieve_context", "abstain"])
    graph.add_edge("retrieve_context", "generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_conditional_edges("validate", after_validate, ["execute", "generate_sql", "abstain"])
    graph.add_conditional_edges("execute", after_execute, ["synthesize", "generate_sql", "abstain"])
    graph.add_edge("synthesize", END)
    graph.add_edge("abstain", END)

    return graph.compile()


def print_state(node: str, state: dict) -> None:
    """Print the FULL state after a node, one key per line."""
    print(f"\n=== state after {node} ===")
    for key, value in state.items():
        text = repr(value)
        if len(text) > MAX_CHARS:
            text = f"{text[:MAX_CHARS]}... ({len(text)} chars)"
        print(f"  {key}: {text}")


if __name__ == "__main__":
    # Run: uv run python -m agent.graph
    app = build_graph()

    # Ask any question: uv run python -m agent.graph "What was the open rate in BU_UK?"
    text = sys.argv[1] if len(sys.argv) > 1 else "How many sends per business unit?"
    request_id = uuid.uuid4().hex
    question = {"question": text, "request_id": request_id}
    # LangSmith trace name + metadata. The same request_id is the Snowflake QUERY_TAG,
    # so one id links the trace to the query in QUERY_HISTORY.
    config = {"run_name": "mini-analytics-agent", "metadata": {"request_id": request_id}}
    # Two stream modes at once: each step yields ("updates", {node: changes}) and then
    # ("values", full_state). We remember the node name from "updates" to label "values".
    node = "input"  # the first "values" chunk is the input, before any node has run
    for mode, chunk in app.stream(question, config, stream_mode=["updates", "values"]):
        if mode == "updates":
            node = next(iter(chunk))  # {"generate_sql": {...}} -> "generate_sql"
        else:
            print_state(node, chunk)
