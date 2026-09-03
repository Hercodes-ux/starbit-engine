"""
SPIRIT — the Critic / Evaluation Harness
"The guardian who inspects every craft for glitches or hallucinations
before letting it pass through the portal."

Responsibilities:
1. Check Databit's summary against the actual query result — flag any
   number or claim that doesn't appear in the data (hallucination check).
2. Check that the chart Pixelcraft built actually matches the question.
3. Either approve (portal opens, final report is compiled) or send the
   work back for revision, up to a small number of rounds so the graph
   can't loop forever.
"""
import json
from langchain_core.messages import SystemMessage, HumanMessage

from agents.state import StarbitState
from agents.llm import get_llm

MAX_REVIEW_ROUNDS = 2

REVIEW_PROMPT = """You are Spirit, the evaluation/critic agent inside the Starbit Engine.
Your job is strict fact-checking. You are given:
1. The user's question
2. Databit's plain-language summary of the SQL result
3. The TRUE total row count of the full query result (authoritative)
4. The TRUE min/max of every numeric column across the FULL result, not just
   the preview (authoritative)
5. A raw preview of the actual query result data (may show fewer rows, or a
   narrower value range, than the true totals above, due to truncation for
   length -- this is normal and NOT itself evidence that Databit's summary
   is wrong)

Check two things, both required to approve:
1. Every specific number or claim in the summary is actually supported by the
   raw data, the true row count, or the true min/max values above. If
   Databit invented or misstated a number, that is a hallucination and must
   be rejected. But if a claim matches the authoritative row count or
   authoritative min/max given to you, that is CORRECT even if you can't
   personally verify it from the truncated preview alone -- the preview
   being narrower than the true range is expected, not a red flag. Only
   reject a range/count claim if it actually CONTRADICTS the authoritative
   numbers, not merely because the preview alone can't confirm it.
2. The summary actually contains concrete numbers answering the question, not
   just vague, unfalsifiable language. A summary that avoids stating any
   specific figures is NOT more trustworthy than a wrong one -- it's just
   unhelpful, and it must also be rejected with feedback telling Databit
   exactly which figure(s) from the raw data it needs to state explicitly.

Respond in this exact format:
VERDICT: approved | revise
FEEDBACK: <one sentence — either confirm it checks out, or state exactly what's wrong>
"""


def spirit_node(state: StarbitState) -> dict:
    trace = [{
        "agent": "spirit",
        "kind": "reasoning",
        "message": "Inspecting the craft for glitches or hallucinated numbers before opening the portal...",
        "payload": None,
    }]

    llm = get_llm()
    result_preview = (state.get("query_result_json") or "")[:3000]
    true_row_count = state.get("query_result_row_count")
    true_stats = state.get("query_result_stats")

    review_resp = llm.invoke([
        SystemMessage(content=REVIEW_PROMPT),
        HumanMessage(content=(
            f"Question: {state['question']}\n\n"
            f"Databit's summary: {state.get('query_result_summary')}\n\n"
            f"TRUE total row count (authoritative): {true_row_count}\n\n"
            f"TRUE per-column min/max across the full result (authoritative): {true_stats}\n\n"
            f"Raw data preview (may be truncated/narrower than the true totals above): {result_preview}"
        )),
    ])

    text = review_resp.content.strip()
    verdict = "approved"
    feedback = text
    for line in text.splitlines():
        if line.upper().startswith("VERDICT:"):
            verdict = line.split(":", 1)[1].strip().lower()
        if line.upper().startswith("FEEDBACK:"):
            feedback = line.split(":", 1)[1].strip()

    if verdict not in ("approved", "revise"):
        verdict = "approved"  # fail open rather than looping forever on a parse miss

    round_num = state.get("review_round", 0) + 1

    trace.append({
        "agent": "spirit",
        "kind": "verdict",
        "message": f"Verdict: {verdict.upper()}. {feedback}",
        "payload": {"verdict": verdict, "round": round_num},
    })

    return {
        "review_verdict": verdict,
        "review_feedback": feedback,
        "review_round": round_num,
        "trace": trace,
    }


def spirit_should_revise(state: StarbitState) -> str:
    """Conditional edge: send back to Databit for one more pass, or let the portal open."""
    if state.get("review_verdict") == "revise" and state.get("review_round", 0) <= MAX_REVIEW_ROUNDS:
        return "revise"
    return "approved"
