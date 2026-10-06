"""
Teachers search, schedule, and curriculum router.
Single responsibility: Querying university professors and their lessons/curriculum.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from tgbot.api.schemas import (
    CurriculumRecordDTO,
    TeacherCurriculumResponse,
    TeacherDayScheduleDTO,
    TeacherLessonDTO,
    TeacherScheduleResponse,
    TeacherSearchResponse,
)
from tgbot.services.parser.teacher_parser import teacher_mapping_manager

router = APIRouter(prefix="/teachers", tags=["Teachers"])


@router.get(
    "",
    response_model=TeacherSearchResponse,
    summary="List or Search Teachers",
    description="Returns all teachers, or filters by surname/name substring if 'q' is provided.",
)
async def list_or_search_teachers(
    q: Optional[str] = Query(None, description="Teacher surname or name substring"),
) -> TeacherSearchResponse:
    if not teacher_mapping_manager.is_mapped():
        await teacher_mapping_manager.ensure_mapping()

    if q and q.strip():
        clean_q = q.strip()
        results = teacher_mapping_manager.search_teachers(clean_q)
        return TeacherSearchResponse(query=clean_q, results=results, count=len(results))

    all_teachers = teacher_mapping_manager.get_all_teacher_names()
    return TeacherSearchResponse(query=None, results=all_teachers, count=len(all_teachers))


@router.get(
    "/search",
    response_model=TeacherSearchResponse,
    summary="Search Teachers",
    description="Searches mapped teachers by surname or full name.",
)
async def search_teachers(
    q: str = Query(..., min_length=1, description="Teacher surname or name substring"),
) -> TeacherSearchResponse:
    query = q.strip()
    if not teacher_mapping_manager.is_mapped():
        await teacher_mapping_manager.ensure_mapping()

    results = teacher_mapping_manager.search_teachers(query)
    return TeacherSearchResponse(query=query, results=results, count=len(results))


@router.get(
    "/{teacher_name}/schedule",
    response_model=TeacherScheduleResponse,
    summary="Get Teacher Lessons Schedule",
    description="Fetches actual scheduled classes for a teacher starting from date for N days (1 to 7).",
)
async def get_teacher_schedule(
    teacher_name: str = Path(..., description="Exact teacher full name (e.g. 'Ливанова А.К.')"),
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Target start date in YYYY-MM-DD format (defaults to current day)",
    ),
    days: int = Query(
        default=1,
        ge=1,
        le=7,
        description="Number of days to fetch schedule for (default: 1 day)",
    ),
) -> TeacherScheduleResponse:
    clean_teacher = teacher_name.strip()
    if not clean_teacher:
        raise HTTPException(status_code=400, detail="Teacher name must not be empty.")

    if not teacher_mapping_manager.is_mapped():
        await teacher_mapping_manager.ensure_mapping()

    dept = teacher_mapping_manager.get_teacher_department(clean_teacher)

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

    day_schedules = []

    for offset in range(days):
        current_day = target_date + timedelta(days=offset)
        raw_lessons = await teacher_mapping_manager.fetch_teacher_lessons(clean_teacher, current_day)

        # Filter lessons matching current_day
        day_raw = [l for l in raw_lessons if l.get("date") == current_day.isoformat()]
        
        lesson_dtos = [
            TeacherLessonDTO(
                date=l.get("date", current_day.isoformat()),
                pair_number=l.get("pair_number"),
                start_time=l.get("start_time"),
                end_time=l.get("end_time"),
                subject=l.get("subject", ""),
                class_type=l.get("class_type"),
                building=l.get("building"),
                room=l.get("room"),
                group_name=l.get("group_name"),
            )
            for l in day_raw
        ]
        # Sort by pair_number
        lesson_dtos.sort(key=lambda x: x.pair_number if x.pair_number is not None else 99)

        day_schedules.append(
            TeacherDayScheduleDTO(
                date=current_day.isoformat(),
                lessons=lesson_dtos,
            )
        )

    return TeacherScheduleResponse(
        teacher=clean_teacher,
        department=dept,
        start_date=target_date.isoformat(),
        days=len(day_schedules),
        schedule=day_schedules,
    )


@router.get(
    "/{teacher_name}/curriculum",
    response_model=TeacherCurriculumResponse,
    summary="Get Teacher Curriculum Files",
    description="Retrieves department information and direct HTML/XML curriculum links for a teacher.",
)
async def get_teacher_curriculum(
    teacher_name: str = Path(..., description="Exact teacher full name (e.g. 'Ливанова А.К.')"),
) -> TeacherCurriculumResponse:
    clean_teacher = teacher_name.strip()
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
