"""
THE STARBIT ENGINE — agent graph definition.

Flow:

    START
      |
      v
   Databit (SQL) <---retry (self-correction)---.
      |                                         |
      | success                          error, retries left
      v                                         |
   Pixelcraft (viz) --------------------------->'
      |
      v
    Spirit (critic) ---revise--> Databit (one more pass)
      |
      | approved / rounds exhausted
      v
   Reporter (compile final report)
      |
      v
     END

This mirrors how a real production agent system is structured:
every node does ONE job, state is explicit and typed, and control
flow (retries, revisions) is expressed as graph edges rather than
buried in if/else spaghetti inside a single giant function.
"""
# LangGraph 0.2.34's checkpoint module unconditionally prints a
# pending-deprecation warning from a newer langchain-core internal
# ("allowed_objects" default) the moment it's imported -- it re-registers
# its own warnings filter at the point the warning fires, which means
# the normal warnings.filterwarnings() approach can't reliably suppress
# it (whichever filter registers last wins, and that's theirs). It's
# harmless -- we don't use LangGraph's checkpointing at all -- so we
# just swallow stderr for the one import statement that triggers it.
import sys as _sys
import io as _io

_original_stderr = _sys.stderr
_sys.stderr = _io.StringIO()
try:
    from langgraph.graph import StateGraph, START, END
finally:
    _sys.stderr = _original_stderr

from agents.state import StarbitState
from agents.databit import databit_node, databit_should_retry
from agents.pixelcraft import pixelcraft_node
from agents.spirit import spirit_node, spirit_should_revise
from agents.reporter import reporter_node


def build_graph():
    graph = StateGraph(StarbitState)

    graph.add_node("databit", databit_node)
    graph.add_node("pixelcraft", pixelcraft_node)
    graph.add_node("spirit", spirit_node)
    graph.add_node("reporter", reporter_node)

    graph.add_edge(START, "databit")

    # Self-correction loop: Databit retries its own failed SQL
    graph.add_conditional_edges(
        "databit",
        databit_should_retry,
        {
            "retry": "databit",
            "give_up": "reporter",
            "success": "pixelcraft",
        },
    )

    graph.add_edge("pixelcraft", "spirit")

    # Review loop: Spirit can send work back to Databit for a fresh pass
    graph.add_conditional_edges(
        "spirit",
        spirit_should_revise,
        {
            "revise": "databit",
            "approved": "reporter",
        },
    )

    graph.add_edge("reporter", END)

    return graph.compile()


# Compiled once at import time and reused across requests.
starbit_graph = build_graph()


def run_starbit(session_id: str, question: str, schema_text: str) -> StarbitState:
    initial_state: StarbitState = {
        "session_id": session_id,
        "question": question,
        "schema_text": schema_text,
        "sql_query": None,
        "sql_error": None,
        "sql_retry_count": 0,
        "query_result_json": None,
        "query_result_summary": None,
        "figure_json": None,
        "chart_rationale": None,
        "review_verdict": None,
        "review_feedback": None,
        "review_round": 0,
        "trace": [],
        "final_report": None,
    }
    final_state = starbit_graph.invoke(initial_state)
    return final_state
