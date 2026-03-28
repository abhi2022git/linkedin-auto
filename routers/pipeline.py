"""Router: Pipeline — Run history and triggering."""

import threading
import time
from fastapi import APIRouter, Query
from typing import Optional
from models import PipelineRunRequest
from database import get_pipeline_runs, get_pipeline_run_by_id, log_pipeline_run_start, log_pipeline_run_complete
from routers.auth_user import get_current_user
from fastapi import APIRouter, Query, Depends

router = APIRouter(prefix="/api", tags=["pipeline"])

@router.get("/pipeline/runs")
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    platform: Optional[str] = Query(None),
):
    return get_pipeline_runs(limit=limit, platform=platform)


@router.get("/pipeline/runs/{run_id}")
def get_run(run_id: int):
    run = get_pipeline_run_by_id(run_id)
    if not run:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/pipeline/run")
def trigger_run(body: PipelineRunRequest, current_user: dict = Depends(get_current_user)):
    """Trigger a pipeline run in a background thread."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    user_id = current_user["id"]
    run_id = log_pipeline_run_start(platform=body.platform, user_id=user_id)

    def _execute(run_id: int, dry_run: bool, override_model: str, user_id: int):
        start_time = time.time()
        try:
            from src.scheduler import run_pipeline, run_dry
            if dry_run:
                run_dry(override_model=override_model, user_id=user_id)
                log_pipeline_run_complete(run_id, status="dry_run",
                                         duration_seconds=round(time.time() - start_time, 2))
            else:
                run_pipeline(override_model=override_model, user_id=user_id)
                log_pipeline_run_complete(run_id, status="success",
                                         duration_seconds=round(time.time() - start_time, 2))
        except Exception as e:
            log_pipeline_run_complete(run_id, status="failed",
                                     error_message=str(e),
                                     duration_seconds=round(time.time() - start_time, 2))

    thread = threading.Thread(target=_execute, args=(run_id, body.dry_run, body.model_override, user_id), daemon=True)
    thread.start()

    return {"run_id": run_id, "status": "started"}
