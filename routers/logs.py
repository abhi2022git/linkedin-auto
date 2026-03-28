"""Router: Logs — System logs and log file reading."""

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from typing import Optional
from database import get_system_logs, get_log_file_content

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def list_logs(
    level: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    return get_system_logs(level=level, module=module, limit=limit)


@router.get("/logs/file", response_class=PlainTextResponse)
def log_file():
    return get_log_file_content(lines=200)
