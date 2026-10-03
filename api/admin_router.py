"""
MAPNAI — api/admin_router.py
/v1/admin: engine metrics, the job schedule, and manual job runs (the same run_job the scheduler calls, so a
manual run takes the job_runs lease and shows up in health). No auth — bind the API to 127.0.0.1 (plan R13).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.personalization_router import get_service
from personalization import jobs
from personalization.service import PersonalizationService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/metrics")
def metrics(
    days: int = Query(default=7, ge=1, le=365),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.metrics(days)


@router.get("/jobs")
def list_jobs(request: Request, svc: PersonalizationService = Depends(get_service)):
    """Every runnable job, its cron (empty = not scheduled), the live scheduler state and the last run."""
    last = svc.logs.last_runs()
    table = jobs.schedule_table(svc.cfg)
    return {
        "scheduler": jobs.scheduler_status(getattr(request.app.state, "scheduler", None)),
        "jobs": {name: {"cron": table.get(name), "per_user": name in jobs.PER_USER,
                        "last_run": {k: last[name].get(k) for k in ("started_at", "finished_at", "ok", "error",
                                                                    "stats")} if name in last else None}
                 for name in sorted(jobs.JOBS)},
    }


@router.post("/jobs/{name}/run")
def run_job(
    name: str,
    user: Optional[List[str]] = Query(default=None, description="pi_topk / digests / proposals only; repeatable"),
    rescan: bool = Query(default=False, description="alerts only: evaluate the whole window again"),
    svc: PersonalizationService = Depends(get_service),
):
    """Run one job now (synchronously). 404 unknown job, 409 while another run holds the lease, 500 on failure."""
    if name not in jobs.JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job {name!r}; one of {sorted(jobs.JOBS)}")
    kwargs = {}
    if user:
        if name not in jobs.PER_USER:
            raise HTTPException(status_code=422, detail=f"user applies only to {list(jobs.PER_USER)}")
        kwargs["user_ids"] = user
    if rescan:
        if name != "alerts":
            raise HTTPException(status_code=422, detail="rescan applies only to alerts")
        kwargs["rescan"] = True
    result = jobs.run_job(svc, name, **kwargs)
    if result.get("skipped"):
        raise HTTPException(status_code=409, detail=f"{name} is already running (lease held)")
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result)
    return result
