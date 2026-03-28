"""Router: Sources — Manage RSS sources."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from models import SourceToggle, SourceCreate
from database import get_sources, toggle_source, add_source

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources")
def list_sources(platform: Optional[str] = Query(None)):
    return get_sources(platform=platform)


@router.put("/sources/{source_id}")
def update_source(source_id: int, body: SourceToggle):
    toggle_source(source_id, body.enabled)
    return {"success": True}


@router.post("/sources")
def create_source(body: SourceCreate):
    source_id = add_source(
        name=body.name, url=body.url,
        source_type=body.source_type,
        category=body.category,
        platform=body.platform,
    )
    return {"success": True, "id": source_id}
