"""FastAPI application entry point."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import addresses, auth, cart, coupons, delivery, orders, reports, restaurants
from app.utils.errors import AppError, error_body
from app.websockets import routes as ws_routes
from app.websockets.manager import manager

logger = logging.getLogger("app")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the scheduler and register the event loop for WebSocket broadcasts."""
    manager.set_loop(asyncio.get_running_loop())
    if get_settings().scheduler_enabled:
        start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        manager.set_loop(None)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Food delivery backend: restaurants, carts, coupons, orders, live delivery tracking.",
        lifespan=lifespan,
    )
    if settings.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.status_code, exc.message, exc.details),
                            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.status_code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
             "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=error_body(422, "Validation failed", details))

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        logger.exception("unhandled error")  # details stay in the log, never in the response
        return JSONResponse(status_code=500, content=error_body(500, "Internal server error"))

    for module in (auth, restaurants, addresses, cart, coupons, orders, delivery, reports):
        app.include_router(module.router)
    app.include_router(ws_routes.router)

    @app.get("/", tags=["Meta"])
    def root():
        return {"name": settings.app_name, "docs": "/docs", "redoc": "/redoc", "tracking_test": "/tracking-test"}

    @app.get("/health", tags=["Meta"])
    def health():
        return {"status": "ok"}

    @app.get("/tracking-test", include_in_schema=False)
    def tracking_test():
        """Serve the WebSocket test page."""
        return FileResponse(STATIC_DIR / "tracking_test.html")

    return app


app = create_app()
