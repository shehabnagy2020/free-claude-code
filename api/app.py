"""FastAPI application factory and configuration."""

import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from config.logging_config import configure_logging
from config.settings import get_settings
from providers.exceptions import ProviderError

from .routes import router
from .runtime import AppRuntime
from .ui_db import UIChatDB
from .ui_routes import ui_router
from .validation_log import summarize_request_validation_body

_UI_DIST = Path(__file__).parent.parent / "ui" / "dist"


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for any unmatched path.

    Starlette's built-in ``html=True`` flag only falls back to ``index.html``
    for *directory* roots, not for arbitrary missing paths like ``/ui/chat``.
    This subclass catches every 404 and returns ``index.html`` instead so that
    React's client-side router can take over.
    """

    async def get_response(self, path: str, scope: Scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    runtime = AppRuntime.for_app(app, settings=get_settings())
    await runtime.startup()

    # Initialize UI chat database
    db = UIChatDB()
    await db.initialize()
    app.state.ui_db = db

    yield

    await runtime.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(
        settings.log_file, verbose_third_party=settings.log_raw_api_payloads
    )

    app = FastAPI(
        title="Claude Code Proxy",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Register API routes first – these take priority over the static-file mount
    # because Starlette checks Route objects before Mount objects in insertion order.
    #
    # Route namespace summary (no overlaps):
    #   /v1/*        – Claude proxy API  (router)
    #   /ui/api/*    – Web UI REST API   (ui_router, prefix="/ui/api")
    #   /ui/*        – React SPA         (_SPAStaticFiles mount below)
    app.include_router(router)
    app.include_router(ui_router)

    # Convenience redirect: visiting the server root goes straight to the UI.
    @app.get("/", include_in_schema=False)
    async def _root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/", status_code=302)

    # Serve the built React SPA at /ui.
    # The _SPAStaticFiles subclass falls back to index.html for any 404 so that
    # React's client-side router handles deep links (e.g. /ui/chat/123).
    # API routes registered above always win because they match first.
    if _UI_DIST.is_dir():
        app.mount(
            "/ui",
            _SPAStaticFiles(directory=str(_UI_DIST), html=True),
            name="ui_static",
        )
    else:
        logger.info(
            "UI static files not found at {}. "
            "Run 'cd ui && npm install && npm run build' to enable the web chat UI.",
            _UI_DIST,
        )

    # Exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Log request shape for 422 debugging without content values."""
        body: Any
        try:
            body = await request.json()
        except Exception as e:
            body = {"_json_error": type(e).__name__}

        message_summary, tool_names = summarize_request_validation_body(body)

        logger.debug(
            "Request validation failed: path={} query={} error_locs={} error_types={} message_summary={} tool_names={}",
            request.url.path,
            str(request.url.query),
            [list(error.get("loc", ())) for error in exc.errors()],
            [str(error.get("type", "")) for error in exc.errors()],
            message_summary,
            tool_names,
        )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        """Handle provider-specific errors and return Anthropic format."""
        err_settings = get_settings()
        if err_settings.log_api_error_tracebacks:
            logger.error(
                "Provider Error: error_type={} status_code={} message={}",
                exc.error_type,
                exc.status_code,
                exc.message,
            )
        else:
            logger.error(
                "Provider Error: error_type={} status_code={}",
                exc.error_type,
                exc.status_code,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_anthropic_format(),
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        """Handle general errors and return Anthropic format."""
        settings = get_settings()
        if settings.log_api_error_tracebacks:
            logger.error("General Error: {}", exc)
            logger.error(traceback.format_exc())
        else:
            logger.error(
                "General Error: path={} method={} exc_type={}",
                request.url.path,
                request.method,
                type(exc).__name__,
            )
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "An unexpected error occurred.",
                },
            },
        )

    return app
