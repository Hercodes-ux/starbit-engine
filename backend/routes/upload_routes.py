from fastapi import APIRouter, Request, UploadFile, File, HTTPException

from config import settings
import database
from models.schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])


def _require_login(request: Request) -> str:
    """Returns the dataset_key for this browser session, or 401s."""
    if not request.session.get("user_email"):
        raise HTTPException(status_code=401, detail="Not logged in.")
    return request.session["dataset_key"]


@router.post("/upload", response_model=UploadResponse)
async def upload_dataset(request: Request, file: UploadFile = File(...)):
    dataset_key = _require_login(request)

    raw = await file.read()
    size_mb = len(raw) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File is {size_mb:.1f}MB; max allowed is {settings.max_upload_size_mb}MB.",
        )

    try:
        schema = database.load_file_for_session(dataset_key, file.filename, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load file: {e}")

    request.session["has_dataset"] = True
    request.session["dataset_name"] = file.filename
    request.session["questions_used"] = 0  # fresh dataset => fresh 5 questions

    return UploadResponse(
        dataset_name=file.filename,
        tables=schema["tables"],
        schema_text=schema["schema_text"],
        questions_remaining=settings.max_questions_per_session,
    )
