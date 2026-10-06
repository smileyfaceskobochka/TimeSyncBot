"""
REST API server for TimeSyncBot Android widget and external integrations.
Built with FastAPI, OpenAPI 3.1 documentation, Pydantic v2 schemas,
CORS, sliding-window rate limiting, and optional API-Key authentication.

API Documentation:
    Interactive Swagger UI: /api/v1/docs
    ReDoc Documentation:   /api/v1/redoc
    OpenAPI JSON schema:    /api/v1/openapi.json

Versioned Endpoints:
    GET /api/v1/health                        — Deep health check (DB connectivity & status)
    GET /api/v1/groups/search?q=             — Search university groups
    GET /api/v1/schedule/{group_name}?date=   — Get 7-day schedule
    GET /api/v1/teachers/search?q=           — Search university teachers
    GET /api/v1/teachers/{teacher_name}/curriculum — Get teacher curriculum files
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tgbot.api.middleware import (
    SecurityAndRateLimitMiddleware,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from tgbot.api.schemas import (
    CurriculumRecordDTO,
    DayScheduleDTO,
    ErrorResponse,
    GroupSearchResponse,
    HealthResponse,
    LessonDTO,
    ScheduleResponse,
    TeacherCurriculumResponse,
    TeacherSearchResponse,
)
from tgbot.database.repositories import DatabaseManager, ScheduleRepository


def get_db(request: Request) -> DatabaseManager:
    """Dependency provider for DatabaseManager from FastAPI application state."""
    db: DatabaseManager | None = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DatabaseManager is not initialized.",
        )
    return db


def create_app(db: Optional[DatabaseManager] = None) -> FastAPI:
    """
    Application factory for the TimeSyncBot REST API.
    """
    app = FastAPI(
        title="TimeSyncBot Schedule API",
        version="1.0.0",
        description=(
            "REST API providing real-time VyatSU student schedule sync, group search, "
            "and teacher curriculum mappings for Android widgets and client applications."
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

    # Store DB reference in app state
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

    # ===== API v1 Routes =====

    @app.get("/api/health", response_model=HealthResponse, include_in_schema=False)
    @app.get("/health", response_model=HealthResponse, include_in_schema=False)
    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["System"],
        summary="Service & Database Health Status",
        description="Verifies database connectivity, counts tracked groups, and checks teacher mapping state.",
    )
    async def get_health(db_manager: DatabaseManager = Depends(get_db)) -> HealthResponse:
        repo = ScheduleRepository(db_manager)
        try:
            groups_count = await repo.get_tracked_groups_count()
            db_ok = True
        except Exception as e:
            logging.error(f"Health check DB probe error: {e}")
            db_ok = False
            groups_count = 0

        from tgbot.services.parser.teacher_parser import teacher_mapping_manager

        is_mapped = teacher_mapping_manager.is_mapped()
        teachers_count = len(teacher_mapping_manager.get_all_teacher_names()) if is_mapped else 0

        return HealthResponse(
            status="ok" if db_ok else "degraded",
            timestamp=datetime.now().isoformat(),
            database_connected=db_ok,
            tracked_groups_count=groups_count,
            teachers_mapped=is_mapped,
            teachers_count=teachers_count,
        )

    @app.get(
        "/api/v1/groups/search",
        response_model=GroupSearchResponse,
        tags=["Groups"],
        summary="Search Tracked University Groups",
        description="Searches currently tracked VyatSU student groups by partial name match.",
    )
    async def search_groups(
        q: str = Query(..., min_length=1, description="Search query string (e.g. 'ИНБ')"),
        db_manager: DatabaseManager = Depends(get_db),
    ) -> GroupSearchResponse:
        query = q.strip()
        repo = ScheduleRepository(db_manager)
        results = await repo.search_tracked_groups(query)
        return GroupSearchResponse(query=query, results=results, count=len(results))

    @app.get(
        "/api/v1/schedule/{group_name}",
        response_model=ScheduleResponse,
        tags=["Schedule"],
        summary="Get 7-Day Group Schedule",
        description="Returns upcoming 7 days of schedule for the specified group starting from date.",
    )
    async def get_group_schedule(
        group_name: str = Path(..., description="Target academic group name (e.g. 'ИНБ-2201-01-00')"),
        date_str: Optional[str] = Query(
            None,
            alias="date",
            description="Start date in YYYY-MM-DD format (defaults to current day)",
        ),
        db_manager: DatabaseManager = Depends(get_db),
    ) -> ScheduleResponse:
        clean_group = group_name.strip()
        if not clean_group:
            raise HTTPException(status_code=400, detail="Group name must not be empty.")

        if date_str:
            try:
                target_date = date.fromisoformat(date_str.strip())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.",
                )
        else:
            target_date = date.today()

        repo = ScheduleRepository(db_manager)
        schedule_days = []

        for offset in range(7):
            current_day = target_date + timedelta(days=offset)
            lessons, predicted = await repo.get_lessons_with_status(clean_group, current_day)

            schedule_days.append(
                DayScheduleDTO(
                    date=current_day.isoformat(),
                    predicted=predicted,
                    lessons=[
                        LessonDTO(
                            pair_number=l.pair_number,
                            start_time=l.start_time,
                            end_time=l.end_time,
                            subject=l.subject,
                            class_type=l.class_type,
                            teacher=l.teacher,
                            building=l.building,
                            room=l.room,
                            subgroup=l.subgroup,
                        )
                        for l in lessons
                    ],
                )
            )

        return ScheduleResponse(
            group=clean_group,
            start_date=target_date.isoformat(),
            days=len(schedule_days),
            schedule=schedule_days,
        )

    @app.get(
        "/api/v1/teachers/search",
        response_model=TeacherSearchResponse,
        tags=["Teachers"],
        summary="Search Teachers",
        description="Searches mapped teachers by surname or full name.",
    )
    async def search_teachers(
        q: str = Query(..., min_length=1, description="Teacher surname or name substring"),
    ) -> TeacherSearchResponse:
        query = q.strip()
        from tgbot.services.parser.teacher_parser import teacher_mapping_manager

        if not teacher_mapping_manager.is_mapped():
            await teacher_mapping_manager.ensure_mapping()

        results = teacher_mapping_manager.search_teachers(query)
        return TeacherSearchResponse(query=query, results=results, count=len(results))

    @app.get(
        "/api/v1/teachers/{teacher_name}/curriculum",
        response_model=TeacherCurriculumResponse,
        tags=["Teachers"],
        summary="Get Teacher Curriculum Files",
        description="Retrieves department information and direct HTML/XML curriculum links for a teacher.",
    )
    async def get_teacher_curriculum(
        teacher_name: str = Path(..., description="Exact teacher full name (e.g. 'Ливанова А.К.')"),
    ) -> TeacherCurriculumResponse:
        clean_teacher = teacher_name.strip()
        from tgbot.services.parser.teacher_parser import teacher_mapping_manager

        if not teacher_mapping_manager.is_mapped():
            await teacher_mapping_manager.ensure_mapping()

        dept = teacher_mapping_manager.get_teacher_department(clean_teacher)
        raw_curriculum = teacher_mapping_manager.get_teacher_curriculum(clean_teacher)

        curriculum_items = [
            CurriculumRecordDTO(
                html_url=item.get("html_url", ""),
                xml_url=item.get("xml_url"),
                department=item.get("department", dept or ""),
            )
            for item in raw_curriculum
        ]

        return TeacherCurriculumResponse(
            teacher=clean_teacher,
            department=dept,
            curriculum=curriculum_items,
            count=len(curriculum_items),
        )

    logging.info("✅ FastAPI v1 routes registered: /api/v1/health, /api/v1/groups/search, /api/v1/schedule/{group_name}, /api/v1/teachers/search, /api/v1/teachers/{teacher_name}/curriculum")
    logging.info("📚 Interactive Swagger documentation available at /api/v1/docs")
    return app


# Legacy alias for backward compatibility with existing callers
def setup_app(db: DatabaseManager) -> FastAPI:
    """Setup and return the FastAPI application instance."""
    return create_app(db)
