"""
Group meetings and mutual free windows router.
Single responsibility: Computing intersection of free time across multiple groups.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from tgbot.api.dependencies import get_schedule_repo
from tgbot.api.schemas import CommonFreeSlotsResponse, FreeSlotDTO
from tgbot.config import config
from tgbot.database.repositories import ScheduleRepository

router = APIRouter(prefix="/meetings", tags=["Meetings"])


@router.get(
    "/free-slots",
    response_model=CommonFreeSlotsResponse,
    summary="Find Common Free Time Windows Between Groups",
    description="Finds mutual free lesson pairs (windows) where NONE of the specified academic groups have classes.",
)
async def find_common_free_slots(
    groups: str = Query(
        ...,
        description="Comma-separated group names to compare (e.g. 'ИНБб-1301-02-00,ИНБб-1302-02-00')",
    ),
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Target date in YYYY-MM-DD format (defaults to current day)",
    ),
    repo: ScheduleRepository = Depends(get_schedule_repo),
) -> CommonFreeSlotsResponse:
    group_list = [g.strip() for g in groups.split(",") if g.strip()]
    if len(group_list) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 group names must be provided (comma-separated).",
        )

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

    lessons = await repo.get_lessons_for_groups(group_list, target_date)
    occupied_pairs = sorted({l.pair_number for l in lessons if l.pair_number})

    all_pairs = set(range(1, 8))
    free_pair_numbers = sorted(all_pairs - set(occupied_pairs))

    free_slots = [
        FreeSlotDTO(
            pair_number=p,
            time=config.STANDARD_PAIRS.get(p, "??:?? - ??:??"),
        )
        for p in free_pair_numbers
    ]

    return CommonFreeSlotsResponse(
        date=target_date.isoformat(),
        groups=group_list,
        occupied_pairs=occupied_pairs,
        free_pairs=free_slots,
        has_common_slots=len(free_slots) > 0,
    )
