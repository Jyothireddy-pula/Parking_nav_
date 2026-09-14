import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.logging_config import configure_logging
from app.routes.campus import router as campus_router
from app.routes.cv_calibration import router as cv_calibration_router
from app.routes.experiment import router as experiment_router
from app.routes.health import router as health_router
from app.routes.ingestion import router as ingestion_router
from app.routes.navigation import router as navigation_router
from app.routes.prediction import router as prediction_router
from app.routes.risk import router as risk_router
from app.routes.twin import router as twin_router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_request_error", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "An unexpected error occurred.", "status_code": 500},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors(), "status_code": 422},
    )


app.include_router(health_router)
app.include_router(health_router, prefix="/api/v1")
app.include_router(campus_router, prefix="/api/v1")
app.include_router(twin_router, prefix="/api/v1")
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(cv_calibration_router, prefix="/api/v1")
app.include_router(navigation_router, prefix="/api/v1")
app.include_router(experiment_router, prefix="/api/v1")
app.include_router(prediction_router, prefix="/api/v1")
app.include_router(risk_router, prefix="/api/v1")
