"""
Group schedule router.
Single responsibility: Querying academic schedules for student groups.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from tgbot.api.dependencies import get_schedule_repo
from tgbot.api.schemas import DayScheduleDTO, LessonDTO, ScheduleResponse
from tgbot.database.repositories import ScheduleRepository

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.get(
    "/{group_name}",
    response_model=ScheduleResponse,
    summary="Get Group Schedule",
    description="Returns schedule for the specified group starting from date for N days (1 to 14 days).",
)
async def get_group_schedule(
    group_name: str = Path(..., description="Academic group name (e.g. 'ИНБ-2201-01-00')"),
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Start date in YYYY-MM-DD format (defaults to current day)",
    ),
    days: int = Query(
        default=7,
        ge=1,
        le=14,
        description="Number of days to return (1 = single day, 7 = week, up to 14)",
    ),
    repo: ScheduleRepository = Depends(get_schedule_repo),
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

    schedule_days = []

    for offset in range(days):
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
