"""FastAPI application entrypint for the Geospatial File Measurement API."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import APP_DESCRIPTION, APP_TITLE, APP_VERSION
from .errors import AppError
from .routers.files import router as files_router

app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
)

app.include_router(files_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/", tags=["meta"], include_in_schema=False)
def root():
    return {
        "service": APP_TITLE,
        "docs": "/docs",
        "endpoints": [
            "POST /api/files/",
            "GET  /api/files/",
            "GET  /api/files/{id}/",
            "GET  /api/files/{id}/features",
            "GET  /api/files/{id}/measurements/",
        ],
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
