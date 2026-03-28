"""Router: Analytics — Charts and summary data."""

from fastapi import APIRouter, Query
from typing import Optional
from database import get_analytics_summary

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics/summary")
def analytics_summary(
    days: int = Query(30, ge=1, le=365),
    platform: Optional[str] = Query(None),
):
    return get_analytics_summary(days=days, platform=platform)
