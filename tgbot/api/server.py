"""
TimeSyncBot REST API Server.
Modular orchestration adhering to the Unix philosophy:
composable routers, single-responsibility components, and strict schemas.

Documentation:
    Swagger UI: /api/v1/docs
    ReDoc:      /api/v1/redoc
    OpenAPI:    /api/v1/openapi.json

Routers mounted under /api/v1:
    /health                       — System health & DB probes
    /groups                       — Group catalog & search
    /schedule/{group_name}        — Academic group schedules
    /teachers                     — Teacher search, schedules, and curriculum
    /occupancy                    — Campus buildings and free classrooms
    /meetings                     — Inter-group mutual free windows
"""
import logging
from typing import Optional

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tgbot.api.middleware import (
    SecurityAndRateLimitMiddleware,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from tgbot.api.routers import (
    groups,
    meetings,
    occupancy,
    schedule,
    system,
    teachers,
)
from tgbot.api.schemas import ErrorResponse, HealthResponse
from tgbot.database.repositories import DatabaseManager


def create_app(db: Optional[DatabaseManager] = None) -> FastAPI:
    """Application factory for the TimeSyncBot REST API."""
    app = FastAPI(
        title="TimeSyncBot API",
        version="1.1.0",
        description=(
            "Clean, composable REST API for VyatSU schedules, teacher assignments, "
            "classroom occupancy, and group meeting planner."
        ),
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        responses={
            400: {"model": ErrorResponse, "description": "Bad Request"},
            401: {"model": ErrorResponse, "description": "Unauthorized (Invalid API Key)"},
            422: {"model": ErrorResponse, "description": "Validation Error"},
            429: {"model": ErrorResponse, "description": "Too Many Requests (Rate limit exceeded)"},
            500: {"model": ErrorResponse, "description": "Internal Server Error"},
        },
    )

    # Store DB reference in app state for dependency injection
    app.state.db = db

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # 2. Rate Limiting and Security Middleware
    app.add_middleware(SecurityAndRateLimitMiddleware)

    # 3. Standardized Exception Handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    # 4. Mount Modular API v1 Routers
    v1_prefix = "/api/v1"
    app.include_router(system.router, prefix=v1_prefix)
    app.include_router(groups.router, prefix=v1_prefix)
    app.include_router(schedule.router, prefix=v1_prefix)
    app.include_router(teachers.router, prefix=v1_prefix)
    app.include_router(occupancy.router, prefix=v1_prefix)
    app.include_router(meetings.router, prefix=v1_prefix)

    # 5. Legacy aliases for external probes
    @app.get("/api/health", response_model=HealthResponse, include_in_schema=False)
    @app.get("/health", response_model=HealthResponse, include_in_schema=False)
    async def legacy_health():
        return await system.get_health(system.get_schedule_repo(db))

    logging.info("✅ API v1 routers mounted: system, groups, schedule, teachers, occupancy, meetings")
    logging.info("📚 Interactive Swagger documentation: /api/v1/docs")
    return app


def setup_app(db: DatabaseManager) -> FastAPI:
    """Setup and return the FastAPI application instance."""
    return create_app(db)
