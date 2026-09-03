"""
Starbit Engine — backend entrypoint.

Run with:
    uvicorn main:app --reload --port 8000
"""
import hashlib
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from routes import auth_routes, upload_routes, chat_routes


def _agents_fingerprint() -> str:
    """
    A short hash of every file in agents/, computed fresh each time this
    module loads. This exists specifically to answer, with certainty and
    without ever running `findstr` again: "is the backend process I'm
    talking to right now actually running the code I just saved, or is it
    a stale process from before my last edit?" Two different processes
    running different code will show two different hashes here -- no
    ambiguity, no guessing, no "did the file actually land" uncertainty.
    """
    agents_dir = pathlib.Path(__file__).parent / "agents"
    hasher = hashlib.sha256()
    for path in sorted(agents_dir.glob("*.py")):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:10]


AGENTS_FINGERPRINT = _agents_fingerprint()

app = FastAPI(
    title="Starbit Engine",
    description="An autonomous multi-agent data analyst: Databit, Pixelcraft & Spirit.",
    version="1.0.0",
)

# Required for request.session (stores the Starbit session id in a signed cookie)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(upload_routes.router)
app.include_router(chat_routes.router)

print(f"[Starbit Engine] agents/ fingerprint: {AGENTS_FINGERPRINT}  "
      f"(compare this after any file save + restart to confirm the running "
      f"process actually picked up your change)")


@app.get("/")
async def root():
    return {
        "service": "Starbit Engine",
        "status": "online",
        "agents": ["Databit", "Pixelcraft", "Spirit"],
        "agents_fingerprint": AGENTS_FINGERPRINT,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "agents_fingerprint": AGENTS_FINGERPRINT}
