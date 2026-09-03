"""
Google OAuth login via Authlib.

Two modes, controlled by MOCK_AUTH in .env:
- MOCK_AUTH=true  -> instant fake login, no Google credentials needed.
                      Perfect for local dev / interview demos on a plane.
- MOCK_AUTH=false -> real Google OAuth 2.0 authorization-code flow.
"""
from authlib.integrations.starlette_client import OAuth
from config import settings

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_mock_user() -> dict:
    """A believable fake identity so the app is fully demoable without Google credentials."""
    return {
        "email": "traveler@starbit.dev",
        "name": "Traveler",
        "picture": None,
    }
