"""
DATABIT — the SQL Agent
"The miner who digs through the database caverns to collect raw data bits."

Responsibilities:
1. Reason about the user's question against the known schema.
2. Write a SQL query (DuckDB dialect) to answer it / surface anomalies.
3. Execute it. If it fails, read the error, fix the query, and retry
   (this is the "self-correction" behavior shown in the UI).
4. Summarize the result in plain language for Pixelcraft and Spirit.
"""
import json
import re
import pandas as pd
from langchain_core.messages import SystemMessage, HumanMessage

from agents.state import StarbitState
from agents.llm import get_llm
from database import run_readonly_query
from config import settings

SYSTEM_PROMPT = r"""You are Databit, the SQL exploration agent inside the Starbit Engine,
an autonomous data-analyst system. You dig through a database and surface
anomalies (revenue drops, outliers, broken trends) relevant to the user's question.

Rules:
- You write DuckDB-compatible SQL only.
- You only ever write SELECT / WITH statements. Never modify data.
- Use the exact table and column names given in the schema. Do not invent columns.
- Prefer queries that reveal trends over time, comparisons across categories,
  or outlier detection (e.g. z-score style deviation, month-over-month deltas).
- CRITICAL — avoid double-counting on grouped aggregates: when a table has one
  row per individual (e.g. one row per passenger) but a value is shared across
  a group (e.g. every passenger on the same ticket shows the same fare), do NOT
  naively SUM() that shared value across the group -- it will inflate the total
  by the group size. Compute the per-group value first (e.g. with MAX() or a
  DISTINCT subquery keyed on the group), then aggregate. When a question asks
  for a "total" or "combined" value across a group, think explicitly about
  whether the source column is per-individual or already shared/duplicated
  before choosing SUM vs MAX vs AVG.
- CRITICAL — LIMIT must match any explicit count in the question: if the
  question says "top N", "bottom N", "the N most/least ...", or otherwise
  names a specific number of results, your LIMIT clause must be exactly
  that number -- not a rounder default like 5 or 10. If the question asks
  to compare a top group AND a bottom group (e.g. "top 3 vs the 3 least
  ..."), you need TWO ranked result sets (e.g. via UNION ALL of two ranked
  subqueries, one ORDER BY ... DESC LIMIT N and one ORDER BY ... ASC LIMIT
  N with a label column distinguishing them) -- a single one-directional
  ranking with a bigger LIMIT does not answer a two-sided comparison
  question, even if it happens to include some of the right rows.
- CRITICAL — regexp_extract() escaping: DuckDB does NOT process backslash
  escapes in plain single-quoted string literals the way Python/JS do. A
  pattern meant to match a literal dot needs exactly ONE backslash before it
  (\.), not two (\\.). Double-escaping (\\.) is silently wrong -- it matches
  a literal backslash character followed by any character, which usually
  doesn't exist in the data, so the pattern matches nothing and every row
  returns NULL instead of erroring. This is a common, easy-to-miss mistake:
  after writing any regexp_extract() call, re-check that every literal
  metacharacter (., (, ), etc.) has exactly one backslash, not zero and not
  two. Example -- correctly extracting an honorific from a "Last, Title.
  First" formatted name column:
  regexp_extract(Name, ', ([A-Za-z]+)\.', 1)
- Return ONLY the raw SQL query, no markdown fences, no commentary.
"""

FIX_PROMPT = """Your previous SQL query failed with this error:
{error}

Here is the query that failed:
{sql}

Here is the schema again:
{schema}

Write a corrected SQL query that fixes the issue. Return ONLY the raw SQL, no commentary.
"""


def _extract_sql(text: str) -> str:
    text = text.strip()
    fence_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text


def _generate_grounded_summary(
    llm, system_content: str, human_content: str,
    row_count: int | None, numeric_stats: dict | None,
    max_attempts: int = 2,
) -> tuple[str, bool]:
    """
    Calls the LLM to produce a summary, but never blindly trusts it to
    actually include real numbers -- checks the response for at least one
    digit before accepting it. Prompt instructions alone ("always include
    concrete numbers") are not a hard guarantee; this was a real, observed
    failure mode where the model stripped every number while trying to
    satisfy reviewer feedback, producing an empty or vague summary.

    If the first attempt comes back numberless, retry once with an
    escalated instruction. If it's STILL numberless after that, stop
    calling the LLM for this step entirely and fall back to a summary
    built directly from code, using the row count and min/max stats that
    were already computed deterministically from the actual query result.
    That fallback cannot suffer this failure mode, because no LLM call is
    involved in producing it -- it's the same principle as Pixelcraft's
    deterministic column override: a guaranteed, code-level backstop
    underneath an LLM judgment call, not another prompt asking the model
    to try harder.

    Returns (summary_text, used_deterministic_fallback).
    """
    content = ""
    for attempt in range(max_attempts):
        sys_content = system_content
        if attempt > 0:
            sys_content += (
                "\n\nYour previous attempt contained NO numbers at all -- that is not "
                "acceptable under any circumstances. Your response MUST include at "
                "least one concrete number taken directly from the data provided."
            )
        resp = llm.invoke([SystemMessage(content=sys_content), HumanMessage(content=human_content)])
        content = resp.content.strip()
        if re.search(r"\d", content):
            return content, False

    parts = []
    if row_count is not None:
        parts.append(f"The query returned {row_count} matching row(s).")
    if numeric_stats:
        stat_bits = [f"{col} ranged from {s['min']:g} to {s['max']:g}" for col, s in numeric_stats.items()]
        if stat_bits:
            parts.append("Key ranges: " + "; ".join(stat_bits) + ".")
    fallback = " ".join(parts) if parts else "The query executed successfully, but no further summary could be generated."
    return fallback, True


def databit_node(state: StarbitState) -> dict:
    llm = get_llm(max_tokens=1536)  # summaries occasionally need more than the 1024 default
    trace = []

    retry_count = state.get("sql_retry_count", 0)
    previous_error = state.get("sql_error")
    review_round = state.get("review_round", 0)

    # --- Path 1: Spirit flagged the SUMMARY as wrong, but the SQL/data were
    # fine (no sql_error). Re-running the whole query from scratch wastes a
    # call and, since the query is deterministic, tends to just reproduce
    # the same mistake. Instead, reuse the existing result and regenerate
    # ONLY the summary, with Spirit's actual feedback as correction context. ---
    if review_round > 0 and previous_error is None and state.get("query_result_json"):
        trace.append({
            "agent": "databit",
            "kind": "self_correction",
            "message": f"Spirit flagged an issue with my summary: \"{state.get('review_feedback')}\". "
                       f"Correcting the writeup (the underlying query was fine)...",
            "payload": None,
        })
        system_content = (
            "You summarize SQL query results in 2-3 sentences of plain, "
            "specific language for a business report. Mention concrete numbers. "
            "A reviewer found a specific error in your previous summary -- fix "
            "exactly that error using the same underlying data, and be precise "
            "with any arithmetic. IMPORTANT: removing the incorrect claim without "
            "replacing it with a correct, equally specific one is NOT an acceptable "
            "fix -- a vague summary with no concrete numbers is not more accurate, "
            "it just avoids being checkable. Recompute the correct figures from the "
            "raw data shown below and state them explicitly. Being concrete does NOT "
            "mean enumerating every individual row -- if there are more than ~5 "
            "records, cite the correct count, range, and at most 2-3 representative "
            "examples instead of listing all of them. Stay within 2-3 sentences."
        )
        human_content = (
            f"Question: {state['question']}\n\n"
            f"Result (JSON records, may be truncated):\n{state['query_result_json'][:4000]}\n\n"
            f"True min/max per column (authoritative, use these for any range claims): {state.get('query_result_stats')}\n\n"
            f"Your previous summary: {state.get('query_result_summary')}\n\n"
            f"Reviewer feedback to fix: {state.get('review_feedback')}"
        )
        summary_text, used_fallback = _generate_grounded_summary(
            llm, system_content, human_content,
            state.get("query_result_row_count"), state.get("query_result_stats"),
        )
        if used_fallback:
            trace.append({
                "agent": "databit",
                "kind": "self_correction",
                "message": "Every rewrite attempt came back without any concrete numbers -- "
                           "falling back to a deterministic summary built directly from the "
                           "verified row count and value ranges, bypassing the LLM for this step.",
                "payload": None,
            })
        trace.append({
            "agent": "databit",
            "kind": "tool_result",
            "message": "Summary corrected using the existing query result.",
            "payload": None,
        })
        return {
            "query_result_summary": summary_text,
            "trace": trace,
        }

    # --- Reasoning step (fresh question, or a genuine SQL-error retry) ---
    if retry_count == 0:
        reasoning_msg = (
            f"Digging into the question: \"{state['question']}\". "
            f"Scanning the schema for relevant tables and likely anomaly signals..."
        )
        trace.append({"agent": "databit", "kind": "reasoning", "message": reasoning_msg, "payload": None})

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Database schema:\n{state['schema_text']}\n\n"
                f"User question: {state['question']}\n\n"
                f"Write the SQL query."
            )),
        ]
    else:
        trace.append({
            "agent": "databit",
            "kind": "self_correction",
            "message": f"SQL failed: \"{previous_error}\". Fixing syntax and re-running (attempt {retry_count + 1}/{settings.max_self_correction_retries + 1})...",
            "payload": {"failed_sql": state.get("sql_query")},
        })
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=FIX_PROMPT.format(
                error=previous_error,
                sql=state.get("sql_query", ""),
                schema=state["schema_text"],
            )),
        ]

    response = llm.invoke(messages)
    sql = _extract_sql(response.content)

    trace.append({
        "agent": "databit",
        "kind": "tool_call",
        "message": f"Running SQL against the dataset...",
        "payload": {"sql": sql},
    })

    # --- Execute ---
    try:
        df = run_readonly_query(state["session_id"], sql)
        preview = df.head(50)  # cap rows sent back to the LLM / UI
        result_json = preview.to_json(orient="records", date_format="iso")

        # Compute min/max on the FULL result (not just the 50-row preview)
        # for every numeric column. This is what actually lets Spirit verify
        # a claim like "the lowest outlier fare is $56.50" -- without this,
        # any claim about a dataset-wide min/max is unverifiable from a
        # truncated preview alone, which was a real, observed failure mode:
        # Spirit correctly (from its limited view) rejecting a TRUE min/max
        # claim as unsupported, because it genuinely couldn't see enough of
        # the preview to confirm it.
        numeric_stats = {}
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                series = df[col].dropna()
                if len(series) > 0:
                    numeric_stats[col] = {"min": float(series.min()), "max": float(series.max())}

        trace.append({
            "agent": "databit",
            "kind": "tool_result",
            "message": f"Query succeeded: {len(df)} row(s) returned.",
            "payload": {"row_count": len(df), "columns": list(df.columns)},
        })

        # Summarize findings in plain language
        system_content = (
            "You summarize SQL query results in 2-3 sentences of plain, "
            "specific language for a business report. Mention concrete numbers. "
            "If the result has more than ~5 rows, do NOT enumerate every row "
            "individually -- give the count, the range, and at most 2-3 "
            "representative examples. Being concrete means citing real numbers "
            "from the data, not listing every single record."
        )
        human_content = (
            f"Question: {state['question']}\n\nResult (JSON records, may be truncated):\n{result_json[:4000]}\n\n"
            f"True min/max per column (authoritative, use these for any range claims):\n{numeric_stats}"
        )
        summary_text, used_fallback = _generate_grounded_summary(llm, system_content, human_content, len(df), numeric_stats)
        if used_fallback:
            trace.append({
                "agent": "databit",
                "kind": "self_correction",
                "message": "The summary attempt came back without concrete numbers -- using a "
                           "deterministic summary built directly from the query results instead.",
                "payload": None,
            })

        return {
            "sql_query": sql,
            "sql_error": None,
            "sql_retry_count": retry_count,
            "query_result_json": result_json,
            "query_result_row_count": len(df),
            "query_result_stats": numeric_stats,
            "query_result_summary": summary_text,
            "trace": trace,
        }

    except Exception as e:
        error_msg = str(e)
        trace.append({
            "agent": "databit",
            "kind": "tool_result",
            "message": f"Query failed: {error_msg}",
            "payload": {"error": error_msg},
        })
        return {
            "sql_query": sql,
            "sql_error": error_msg,
            "sql_retry_count": retry_count + 1,
            "trace": trace,
        }


def databit_should_retry(state: StarbitState) -> str:
    """Conditional edge: retry SQL, give up gracefully, or move on to Pixelcraft."""
    if state.get("sql_error") is None:
        return "success"
    if state["sql_retry_count"] > settings.max_self_correction_retries:
        return "give_up"
    return "retry"
