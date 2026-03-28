"""Router: Overview — Dashboard home cards."""

from fastapi import APIRouter
from database import get_overview, get_settings

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
def overview():
    data = get_overview()

    # Token status
    settings = get_settings()
    data["token_status"] = {
        "configured": settings["linkedin_tokens_configured"],
        "expires_at": None,
        "days_remaining": None,
    }

    # Model status
    data["models_active"] = ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile",
                             "gemma2-9b-it", "llama-3.1-8b-instant"]
    data["models_decommissioned"] = ["mixtral-8x7b-32768", "deepseek-r1-distill-llama-70b"]

    return data
