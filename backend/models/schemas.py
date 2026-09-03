from pydantic import BaseModel


class UploadResponse(BaseModel):
    dataset_name: str
    tables: list[str]
    schema_text: str
    questions_remaining: int


class AskRequest(BaseModel):
    question: str


class AgentStep(BaseModel):
    agent: str          # "databit" | "pixelcraft" | "spirit"
    kind: str            # "reasoning" | "tool_call" | "tool_result" | "self_correction" | "verdict"
    message: str
    payload: dict | None = None  # e.g. {"sql": "..."} or {"figure": {...plotly json...}}


class AskResponse(BaseModel):
    steps: list[AgentStep]
    final_report: str
    figure_json: str | None = None
    questions_remaining: int
    passed_review: bool
