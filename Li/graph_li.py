"""Wire the nodes into a LangGraph StateGraph.

START -> route --answer--> retrieve_context -> generate_sql -> validate --ok--> execute --ok--> synthesize -> END
           |                                       ^              |               |
           +--clarify / out_of_scope--+            +----error-----+-----error-----+   (max MAX_RETRIES retries)
                                      v                           |               |
                                   abstain <------- too many -----+---------------+
                                      |
                                     END
"""

import uuid
from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.state import AgentState

MAX_RETRIES = 2 # 1 first attempt + 2 retries, then abstain
MAX_CHARS = 200 
#--- Conditional edges: plain functions that read the state and return the NEXT node's name ---

def after_route(state: AgentState) -> str:
   return "retrieve_context" if state["intent"] == "answer" else "abstain"

def after_validate(state: AgentState) -> str:
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
   print(app.get_graph().draw_mermaid()) # paste into https://mermaid.live to see the picture

   question = {"question": "How many sends per business unit?", "request_id": "demo-1"}
   for step in app.stream(question, stream_mode="updates"):  # one line per node that ran
      print(step)
