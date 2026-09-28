"""
MAPNAI — api/app.py
FastAPI application. Mounts the /v1 personalization router.
Run with: python run_api.py
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.personalization_router import router as personalization_router
from personalization.service import PersonalizationError


def create_app() -> FastAPI:
    app = FastAPI(title="MAPNAI API", version="0.1.0")

    @app.exception_handler(PersonalizationError)
    async def _personalization_error(request: Request, exc: PersonalizationError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(personalization_router)
    return app


app = create_app()
