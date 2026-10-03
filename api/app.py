"""
MAPNAI — api/app.py
FastAPI application. Mounts the /v1 personalization, /v1/admin and /v1/auth routers, and runs the personalization jobs
on an in-process APScheduler for the app's lifetime (PERS_SCHEDULER_ENABLED; run uvicorn with one worker).
Run with: python run_api.py
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.admin_router import router as admin_router
from api.auth_router import router as auth_router
from api.personalization_router import get_service
from api.personalization_router import router as personalization_router
from config.personalization import pers_settings
from personalization import jobs
from personalization.service import PersonalizationError
from utils.auth import AuthError
from utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = None
    if pers_settings.scheduler_enabled:
        # the same service the endpoints use (honouring test overrides), so the in-memory FAISS index the
        # cluster job grows is the one served
        svc = app.dependency_overrides.get(get_service, get_service)()
        scheduler = jobs.build_scheduler(svc, pers_settings)
        scheduler.start()
        app.state.scheduler = scheduler
        for name, info in jobs.scheduler_status(scheduler)["jobs"].items():
            logger.info(f"[Scheduler] {name}: {info['trigger']}, next run {info['next_run']}")
        logger.info(f"[Scheduler] Started with {len(scheduler.get_jobs())} jobs ({pers_settings.tz})")
    else:
        logger.info("[Scheduler] Disabled (PERS_SCHEDULER_ENABLED=false)")
    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)
            logger.info("[Scheduler] Stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="MAPNAI API", version="0.1.0", lifespan=lifespan)
    app.state.scheduler = None

    @app.exception_handler(PersonalizationError)
    async def _personalization_error(request: Request, exc: PersonalizationError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(AuthError)
    async def _auth_error(request: Request, exc: AuthError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(personalization_router)
    app.include_router(admin_router)
    app.include_router(auth_router)
    return app


app = create_app()
