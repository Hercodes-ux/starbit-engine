"""
Centralized configuration for the Starbit Engine backend.
All environment variables are loaded and validated here, once,
so the rest of the app never touches os.environ directly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    # LLM (Groq — free tier, get a key at https://console.groq.com/keys)
    groq_api_key: str = ""
    model_name: str = "openai/gpt-oss-120b"
    fast_model_name: str = "openai/gpt-oss-20b"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    mock_auth: bool = True

    # Session
    session_secret_key: str = "insecure-dev-key-replace-me"

    # App limits
    max_questions_per_session: int = 5
    max_upload_size_mb: int = 25
    max_self_correction_retries: int = 3

    # CORS
    frontend_origin: str = "http://localhost:5500"


settings = Settings()
