"""Router: Posts — CRUD for posted topics."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from database import get_posts, get_post_by_id, retry_post

router = APIRouter(prefix="/api", tags=["posts"])


@router.get("/posts")
def list_posts(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return get_posts(platform=platform, status=status, limit=limit, offset=offset)


@router.get("/posts/{post_id}")
def get_post(post_id: int):
    post = get_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/posts/{post_id}/retry")
def retry_failed_post(post_id: int):
    retry_post(post_id)
    return {"success": True}
