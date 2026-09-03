"""
PIXELCRAFT — the Visualization Agent
"The artist who weaves data into colorful Plotly neural flow maps."

Responsibilities:
1. Look at Databit's query result and decide the clearest chart type.
2. Pick the ONE numeric column most relevant to the user's question --
   deliberately, not "all of them." Query results routinely mix columns
   on wildly different scales (a row count, a dollar total, a percentage),
   and charting all of them together on one axis produces a stacked bar
   where the small-scale metrics vanish and the shape is meaningless.
   Picking the single most decision-relevant metric is the correct
   information-design choice, not a limitation -- Databit's own summary
   already covers the other computed columns in prose.
3. Build a Plotly figure (JSON-serializable) that highlights the anomaly
   or trend the user asked about.
4. Explain, in one line, why this chart type and metric were chosen.
"""
import io
import json
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from langchain_core.messages import SystemMessage, HumanMessage

from agents.state import StarbitState
from agents.llm import get_llm

CHART_CHOICE_PROMPT = """You are Pixelcraft, the visualization agent inside the Starbit Engine.
Given a user's question and a preview of query result columns, decide how to chart it.

You are given a list of candidate numeric columns. Query results often contain several
numeric columns on very different scales (e.g. a row count, a dollar total, and a
percentage) -- charting all of them together on one axis is misleading, since the
small-scale ones get visually crushed by the large-scale ones. Pick ONLY the single
column most relevant to answering the user's actual question.

STRONG SIGNAL: if a word or clear synonym for one of the candidate columns appears
directly in the user's question (e.g. the question says "fare" and "Fare" is a
candidate column, or says "age" and "Age" is a candidate), that column is almost
always the right pick -- prefer it over columns that merely happen to be present in
the result set as byproducts of the query (e.g. an id column, or a flag column like
a survived/success/status indicator that wasn't what the question was actually
asking about). Do not default to whichever numeric column looks most familiar or
common in this kind of dataset -- ground the choice in the specific question asked.

Respond in EXACTLY this format, two lines, nothing else:
CHART_TYPE: line | bar | scatter | area | none
Y_COLUMN: <exact column name from the candidates list, or NONE if CHART_TYPE is none>

Use "none" for CHART_TYPE only if the data genuinely cannot be charted (e.g. a single
scalar value or zero rows).
"""


def _keyword_match_column(question: str, numeric_cols: list[str]) -> str | None:
    """
    Deterministic override, checked BEFORE trusting the LLM's judgment call.

    In testing, the chart-choice LLM call reliably defaulted to a familiar
    Titanic column (Survived) even after being explicitly instructed to
    prefer columns named in the question -- prompt engineering alone wasn't
    reliable enough for this. A plain keyword match is: if exactly one
    candidate column's name appears as a whole word in the question text
    (case-insensitive), that's an unambiguous, free, zero-latency signal
    that beats an LLM guess.

    One refinement, added after a real failure: for a composite/ranking
    question ("most privileged", "top N by ..."), Databit sometimes builds
    a combined score column (e.g. privilege_score) out of several raw
    inputs (fare_score, class_score, cabin_score). If the question happens
    to also mention one of those raw ingredients by name (e.g. "fare
    paid"), a plain keyword match wrongly grabs the ingredient instead of
    the composite result -- the composite is almost always the more
    relevant thing to chart. So: any column whose name contains "score"
    (or "rank"/"index"/"rating") takes priority over a plain keyword hit,
    since its presence signals Databit already did the hard work of
    combining multiple factors into the metric that actually answers the
    question.
    """
    score_like = [c for c in numeric_cols if re.search(r"score|rank|rating|index", c.lower())]
    if len(score_like) == 1:
        return score_like[0]
    if len(score_like) > 1:
        # Multiple score-like columns usually means one composite built from
        # several named sub-scores (e.g. privilege_score from class_score,
        # cabin_score, fare_score). The sub-scores' name prefixes tend to
        # also be literally named in the question (since the question spells
        # out the ingredients: "based on class, fare paid, and cabin
        # presence"), while the composite's own name usually isn't repeated
        # verbatim. Exclude any score column whose prefix is explicitly named
        # in the question -- what's left is the composite.
        q_lower_check = question.lower()
        unclaimed = [
            c for c in score_like
            if not re.search(r"\b" + re.escape(c.lower().split("_")[0]) + r"\b", q_lower_check)
        ]
        if len(unclaimed) == 1:
            return unclaimed[0]

    q_lower = question.lower()
    matches = [
        col for col in numeric_cols
        if re.search(r"\b" + re.escape(col.lower()) + r"\b", q_lower)
    ]
    return matches[0] if len(matches) == 1 else None


def _choose_x_column(df: pd.DataFrame, y_col: str) -> str:
    """
    Picks the x-axis column. Previously this was always just the query's
    first column -- fine when that happened to be a meaningful category,
    but a real bug when it's an arbitrary primary key like PassengerId:
    Plotly treats a numeric-looking ID as a continuous axis, spacing bars
    by their numeric VALUE (leaving huge empty gaps between e.g. ID 258
    and ID 679) instead of just listing them evenly. Prefer an actual
    label/name/category column over a raw ID column when one exists.
    """
    cols = [c for c in df.columns if c != y_col]
    if not cols:
        return df.columns[0]

    id_like = re.compile(r"(^id$|_id$|^id_|passengerid)", re.IGNORECASE)
    label_like = re.compile(r"\b(name|group|category|label|type|class)\b", re.IGNORECASE)

    label_candidates = [c for c in cols if label_like.search(c) and not id_like.search(c)]
    if label_candidates:
        return label_candidates[0]

    non_id_candidates = [c for c in cols if not id_like.search(c)]
    if non_id_candidates:
        return non_id_candidates[0]

    return cols[0]  # every column looked ID-like -- fall back rather than crash


def _build_figure(df: pd.DataFrame, chart_type: str, y_col: str, question: str) -> go.Figure:
    x_col = _choose_x_column(df, y_col)

    theme = dict(
        template="plotly_dark",
        paper_bgcolor="#151833",
        plot_bgcolor="#151833",
        font=dict(family="VT323, monospace", size=16, color="#F5F3E7"),
        title=dict(text=question[:80], font=dict(color="#FFD447")),
        colorway=["#4CE0D2", "#FF4FA3", "#FFD447", "#8C7CFF"],
    )

    if chart_type == "line":
        fig = px.line(df, x=x_col, y=y_col, markers=True)
    elif chart_type == "bar":
        fig = px.bar(df, x=x_col, y=y_col)
        fig.update_layout(barmode="group")  # never stack, even defensively
        # Bar charts represent discrete categories, never a continuous
        # numeric scale -- without this, a numeric x column (even a
        # sensible one) gets spaced by VALUE, not listed evenly, which
        # stretches/hides bars whenever the values aren't evenly spaced.
        fig.update_xaxes(type="category")
    elif chart_type == "scatter":
        fig = px.scatter(df, x=x_col, y=y_col)
    elif chart_type == "area":
        fig = px.area(df, x=x_col, y=y_col)
    else:
        fig = px.bar(df, x=x_col, y=y_col)
        fig.update_layout(barmode="group")
        fig.update_xaxes(type="category")

    fig.update_layout(yaxis_title=y_col, **theme)
    return fig


def pixelcraft_node(state: StarbitState) -> dict:
    trace = [{
        "agent": "pixelcraft",
        "kind": "reasoning",
        "message": "Weaving Databit's numbers into a neural flow map...",
        "payload": None,
    }]

    result_json = state.get("query_result_json")
    if not result_json:
        trace.append({
            "agent": "pixelcraft",
            "kind": "tool_result",
            "message": "No queryable rows to chart — skipping visualization.",
            "payload": None,
        })
        return {"figure_json": None, "chart_rationale": None, "trace": trace}

    df = pd.read_json(io.StringIO(result_json), orient="records")
    if df.empty or len(df.columns) < 2:
        trace.append({
            "agent": "pixelcraft",
            "kind": "tool_result",
            "message": "Result set too thin to visualize meaningfully — skipping chart.",
            "payload": None,
        })
        return {"figure_json": None, "chart_rationale": None, "trace": trace}

    numeric_cols = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]

    # A column that's identical across every row conveys zero visual
    # information no matter what it's named -- e.g. "passenger_count" is
    # always 3-and-3 when the question itself specified "top 3 vs bottom
    # 3", so charting it just draws two equal-height bars. Filter these
    # out at the data level (checkable directly, no guessing from names)
    # so neither the LLM nor the keyword override can ever pick one,
    # unless doing so would leave no candidates at all.
    varying_cols = [c for c in numeric_cols if df[c].nunique(dropna=False) > 1]
    if varying_cols:
        numeric_cols = varying_cols
    if not numeric_cols:
        trace.append({
            "agent": "pixelcraft",
            "kind": "tool_result",
            "message": "No numeric columns to plot — skipping chart.",
            "payload": None,
        })
        return {"figure_json": None, "chart_rationale": None, "trace": trace}

    llm = get_llm(fast=True, max_tokens=60)  # cheap classification call: small model, short output
    choice_resp = llm.invoke([
        SystemMessage(content=CHART_CHOICE_PROMPT),
        HumanMessage(content=(
            f"Question: {state['question']}\n"
            f"Candidate numeric columns: {numeric_cols}\n"
            f"Sample rows:\n{df.head(5).to_string()}"
        )),
    ])

    chart_type = "bar"
    y_col = numeric_cols[0]
    for line in choice_resp.content.strip().splitlines():
        if line.upper().startswith("CHART_TYPE:"):
            candidate = line.split(":", 1)[1].strip().lower()
            if candidate in {"line", "bar", "scatter", "area", "none"}:
                chart_type = candidate
        if line.upper().startswith("Y_COLUMN:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate in numeric_cols:
                y_col = candidate

    # Deterministic override: a column literally named in the question beats
    # whatever the LLM picked, if it picked something else.
    keyword_col = _keyword_match_column(state["question"], numeric_cols)
    if keyword_col and keyword_col != y_col:
        trace.append({
            "agent": "pixelcraft",
            "kind": "self_correction",
            "message": f"The question explicitly names '{keyword_col}' -- overriding the initial "
                       f"pick of '{y_col}' with the column the user actually asked about.",
            "payload": None,
        })
        y_col = keyword_col

    trace.append({
        "agent": "pixelcraft",
        "kind": "tool_call",
        "message": f"Rendering a {chart_type} chart of '{y_col}' with Plotly...",
        "payload": {"chart_type": chart_type, "y_column": y_col},
    })

    if chart_type == "none":
        trace.append({
            "agent": "pixelcraft",
            "kind": "tool_result",
            "message": "Determined this result is best shown as a number, not a chart.",
            "payload": None,
        })
        return {"figure_json": None, "chart_rationale": "Scalar result — no chart needed.", "trace": trace}

    fig = _build_figure(df, chart_type, y_col, state["question"])
    figure_json = fig.to_json()

    other_cols = [c for c in numeric_cols if c != y_col]
    other_note = f" (other computed columns — {', '.join(other_cols)} — are covered in Databit's summary above)" if other_cols else ""

    trace.append({
        "agent": "pixelcraft",
        "kind": "tool_result",
        "message": f"Chart complete: {y_col} by {df.columns[0]}.{other_note}",
        "payload": None,
    })

    return {
        "figure_json": figure_json,
        "chart_rationale": f"Chose a {chart_type} chart of '{y_col}' vs '{df.columns[0]}' as the metric most relevant to the question.{other_note}",
        "trace": trace,
    }
