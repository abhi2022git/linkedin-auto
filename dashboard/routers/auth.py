import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from dashboard.routers.auth_user import get_current_user
from src.linkedin_poster import LinkedInPoster

router = APIRouter(prefix="/api/auth", tags=["linkedin_auth"])

@router.get("/linkedin_url")
def get_linkedin_auth_url(current_user: dict = Depends(get_current_user)):
    """Return the LinkedIn OAuth URL with the user ID in the state parameter."""
    poster = LinkedInPoster(user_id=current_user["id"])
    poster.redirect_uri = poster.dashboard_redirect_uri
    auth_url = poster.get_auth_url()
    
    # Inject user_id into the state so we know who logged in during callback
    auth_url = auth_url.replace("state=linkedin_auto_poster", f"state=linkedin_auto_poster_{current_user['id']}")
    return {"url": auth_url}

@router.get("/callback")
def linkedin_callback(request: Request, code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Handle LinkedIn OAuth callback and exchange code for token using the user_id from state."""
    # This route is public because LinkedIn redirects here without bearer tokens.
    if error:
        return {"success": False, "error": error, "description": error_description}
    
    if not code or not state or not state.startswith("linkedin_auto_poster_"):
        return {"success": False, "error": "Invalid auth callback parameters"}
        
    try:
        user_id = int(state.replace("linkedin_auto_poster_", ""))
        poster = LinkedInPoster(user_id=user_id)
        poster.redirect_uri = poster.dashboard_redirect_uri
        poster.exchange_code(code)
        
        # Redirect back to the dashboard settings page
        return RedirectResponse(url="/#settings")
    except Exception as e:
        return {"success": False, "error": str(e)}
