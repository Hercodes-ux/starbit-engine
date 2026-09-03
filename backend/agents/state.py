"""
The shared state object that flows through every node in the
Starbit Engine graph. LangGraph merges each node's return dict
into this state -- think of it as the "party inventory" every
agent can read from and write to.
"""
from typing import TypedDict, Annotated
import operator


class AgentTrace(TypedDict):
    agent: str            # "databit" | "pixelcraft" | "spirit"
    kind: str              # "reasoning" | "tool_call" | "tool_result" | "self_correction" | "verdict"
    message: str
    payload: dict | None


class StarbitState(TypedDict):
    # --- inputs ---
    session_id: str
    question: str
    schema_text: str

    # --- Databit's working memory ---
    sql_query: str | None
    sql_error: str | None
    sql_retry_count: int
    query_result_json: str | None        # dataframe as JSON records, capped in size
    query_result_row_count: int | None    # TRUE total row count, before any preview truncation
    query_result_stats: dict | None       # TRUE per-column min/max, before any preview truncation
    query_result_summary: str | None      # human-readable summary Databit writes for the team

    # --- Pixelcraft's working memory ---
    figure_json: str | None
    chart_rationale: str | None

    # --- Spirit's working memory ---
    review_verdict: str | None            # "approved" | "revise"
    review_feedback: str | None
    review_round: int

    # --- shared trace log, appended to by every node ---
    trace: Annotated[list[AgentTrace], operator.add]

    # --- final output ---
    final_report: str | None
