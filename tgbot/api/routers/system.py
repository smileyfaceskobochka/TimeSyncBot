"""
System health and readiness router.
Single responsibility: Report service, database, and cache health.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from tgbot.api.dependencies import get_schedule_repo
from tgbot.api.schemas import HealthResponse
from tgbot.database.repositories import ScheduleRepository
from tgbot.services.parser.teacher_parser import teacher_mapping_manager

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service & Database Health Status",
    description="Probes SQLite database connectivity, counts tracked groups, and checks teacher mapping state.",
)
async def get_health(repo: ScheduleRepository = Depends(get_schedule_repo)) -> HealthResponse:
    try:
        groups_count = await repo.get_tracked_groups_count()
        db_ok = True
    except Exception as e:
        logging.error(f"Health check DB probe error: {e}")
        db_ok = False
        groups_count = 0

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
