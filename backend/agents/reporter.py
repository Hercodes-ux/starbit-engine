"""
Compiles the final report shown to the user once Spirit approves
(or once retries/review rounds are exhausted). This is a plain
Python node -- no LLM call needed, it just assembles what the
other agents already produced.
"""
from agents.state import StarbitState


def reporter_node(state: StarbitState) -> dict:
    if state.get("sql_error") and state.get("sql_retry_count", 0) > 0 and not state.get("query_result_summary"):
        report = (
            "⚠️ Databit couldn't get a working query after several attempts.\n\n"
            f"Last error: {state.get('sql_error')}\n\n"
            "Try rephrasing the question or checking that the referenced columns exist."
        )
        trace = [{
            "agent": "spirit",
            "kind": "verdict",
            "message": "The portal stayed closed — no reliable answer could be produced.",
            "payload": None,
        }]
        return {"final_report": report, "trace": trace}

    summary = state.get("query_result_summary") or (
        "Databit's writeup came back empty after repeated correction attempts. "
        "The underlying data was retrieved successfully — try rephrasing the "
        "question, or ask a narrower follow-up about the same dataset."
    )
    chart_note = state.get("chart_rationale")
    feedback = state.get("review_feedback", "")

    parts = [summary]
    if chart_note:
        parts.append(chart_note)
    report = "\n\n".join(parts)

    trace = [{
        "agent": "spirit",
        "kind": "verdict",
        "message": "The portal opens. Report compiled and delivered.",
        "payload": None,
    }]

    return {"final_report": report, "trace": trace}
