import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict

from dashboard.database import get_db, get_settings
from dashboard.routers.auth_user import get_current_user
from src.utils import get_project_root

router = APIRouter(prefix="/api", tags=["settings"])

class SettingsUpdate(BaseModel):
    GROQ_API_KEY: str = None
    OPENROUTER_API_KEY: str = None
    HUGGINGFACE_API_KEY: str = None
    LINKEDIN_CLIENT_ID: str = None
    LINKEDIN_CLIENT_SECRET: str = None
    POST_AS_ORGANIZATION: bool = None
    ORGANIZATION_ID: str = None
    PREFERRED_MODEL: str = None

def get_user_settings_db(user_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)

@router.get("/settings")
def get_settings_api(current_user: Dict = Depends(get_current_user)):
    user_settings = get_user_settings_db(current_user["id"])
    
    groq = user_settings.get("groq_api_key", "")
    or_key = user_settings.get("openrouter_api_key", "")
    hf_key = user_settings.get("huggingface_api_key", "")
    
    hf_configured = bool(hf_key and len(hf_key) > 10)
    
    # Check LinkedIn Token
    from src.linkedin_poster import TokenManager
    tm = TokenManager(user_id=current_user["id"])
    linkedin_connected = tm.has_tokens()
    
    return {
        "pipeline": {
            "post_schedule_hour": user_settings.get("post_schedule_hour", 9),
            "post_schedule_minute": user_settings.get("post_schedule_minute", 0),
            "enable_image_generation": bool(user_settings.get("enable_image_generation", 1)),
            "preferred_model": user_settings.get("preferred_model", "auto"),
            "post_as_organization": False,
            "linkedin_tokens_configured": linkedin_connected
        },
        "keys": {
            "groq_configured": bool(groq and len(groq) > 10),
            "or_configured": bool(or_key and len(or_key) > 5),
            "hf_configured": hf_configured,
            "linkedin_client_id": user_settings.get("linkedin_client_id", ""),
            "post_as_organization": False,
            "organization_id": "",
            "preferred_model": user_settings.get("preferred_model", "auto")
        },
        "status": {
            "linkedin_connected": linkedin_connected
        }
    }

@router.post("/settings")
def update_settings(updates: SettingsUpdate, current_user: Dict = Depends(get_current_user)):
    updates_dict = updates.dict(exclude_none=True)
    if not updates_dict:
        return {"success": True}
        
    set_clauses = []
    values = []
    
    for key, value in updates_dict.items():
        db_col = key.lower()
        if isinstance(value, bool):
            value = 1 if value else 0
        # Only allow setting columns that exist in the DB model
        if db_col in ("groq_api_key", "openrouter_api_key", "huggingface_api_key", 
                      "linkedin_client_id", "linkedin_client_secret"):
            set_clauses.append(f"{db_col} = ?")
            values.append(value)
            
    if not set_clauses:
        return {"success": True}
        
    values.append(current_user["id"])
    sql = f"UPDATE user_settings SET {', '.join(set_clauses)} WHERE user_id = ?"
    
    try:
        with get_db() as conn:
            conn.execute(sql, values)
            conn.commit()
        return {"success": True, "message": "Settings updated in database"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
