from fastapi import APIRouter, Request, HTTPException

from config import settings
import database
from agents.graph import run_starbit
from models.schemas import AskRequest, AskResponse, AgentStep

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/ask", response_model=AskResponse)
async def ask(request: Request, body: AskRequest):
    if not request.session.get("user_email"):
        raise HTTPException(status_code=401, detail="Not logged in.")

    if not request.session.get("has_dataset"):
        raise HTTPException(status_code=400, detail="Upload a dataset before asking questions.")

    questions_used = request.session.get("questions_used", 0)
    if questions_used >= settings.max_questions_per_session:
        raise HTTPException(
            status_code=429,
            detail=f"You've used all {settings.max_questions_per_session} questions for this dataset. "
                   f"Upload a new dataset to get 5 more.",
        )

    if not body.question or not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    dataset_key = request.session["dataset_key"]

    try:
        schema = database.get_schema(dataset_key)
    except KeyError:
        # The in-memory DuckDB connection for this dataset is gone.
        # This happens when the backend process restarted (e.g. --reload
        # picked up a file save) after the file was uploaded -- login
        # and question count survived (they live in the signed cookie),
        # but the loaded data itself only ever lived in process memory.
        request.session["has_dataset"] = False
        raise HTTPException(
            status_code=409,
            detail="Your dataset session expired (the server restarted). "
                   "Please re-upload your file — your question count is unaffected.",
        )

    try:
        final_state = run_starbit(dataset_key, body.question.strip(), schema["schema_text"])
    except Exception as e:
        # Almost always a Groq API problem: missing/invalid GROQ_API_KEY,
        # the free-tier rate limit, or no network access. This is a much
        # more likely failure mode with a free key than a paid one, so it
        # gets a specific, actionable message instead of a bare 500 --
        # and, importantly, this question does NOT count against the
        # user's 5-question quota, since they never got an answer.
        error_text = str(e).lower()
        if "api_key" in error_text or "authentication" in error_text or "401" in error_text:
            hint = "Check that GROQ_API_KEY in backend/.env is set correctly, then restart the backend."
        elif "not_found" in error_text or "notfounderror" in error_text or "decommissioned" in error_text or "404" in error_text:
            hint = ("The model name in .env (MODEL_NAME) may be outdated or deprecated by Groq. "
                    "Check https://console.groq.com/docs/models for the current free-tier list, "
                    "update MODEL_NAME in backend/.env, then restart the backend.")
        elif "rate" in error_text or "429" in error_text:
            hint = "You've hit Groq's free-tier rate limit. Wait a minute and try again."
        elif "allowlist" in error_text or "network" in error_text or "connect" in error_text:
            hint = "The backend couldn't reach the Groq API — check your network/firewall settings."
        else:
            hint = "Check the backend terminal for the full error."
        raise HTTPException(
            status_code=502,
            detail=f"The AI service call failed: {type(e).__name__}. {hint}",
        )

    request.session["questions_used"] = questions_used + 1

    steps = [AgentStep(**t) for t in final_state["trace"]]
    passed_review = final_state.get("review_verdict") == "approved"

    return AskResponse(
        steps=steps,
        final_report=final_state.get("final_report") or "No report generated.",
        figure_json=final_state.get("figure_json"),
        questions_remaining=max(0, settings.max_questions_per_session - request.session["questions_used"]),
        passed_review=passed_review,
    )
