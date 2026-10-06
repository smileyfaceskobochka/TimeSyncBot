"""
Academic groups catalog and search router.
Single responsibility: Querying university student groups.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from tgbot.api.dependencies import get_schedule_repo
from tgbot.api.schemas import GroupSearchResponse
from tgbot.database.repositories import ScheduleRepository

router = APIRouter(prefix="/groups", tags=["Groups"])


@router.get(
    "",
    response_model=GroupSearchResponse,
    summary="List or Search Groups",
    description="Returns all tracked student groups, or filters by query if 'q' is provided.",
)
async def list_or_search_groups(
    q: Optional[str] = Query(None, description="Optional search substring (e.g. 'ИНБ')"),
    repo: ScheduleRepository = Depends(get_schedule_repo),
) -> GroupSearchResponse:
    if q and q.strip():
        clean_q = q.strip()
        results = await repo.search_tracked_groups(clean_q)
        return GroupSearchResponse(query=clean_q, results=results, count=len(results))

    # If no query provided, return all distinct group names
    all_groups = await repo.get_all_group_names()
    return GroupSearchResponse(query=None, results=all_groups, count=len(all_groups))


@router.get(
    "/search",
    response_model=GroupSearchResponse,
    summary="Search Tracked University Groups",
    description="Searches currently tracked VyatSU student groups by partial name match.",
)
async def search_groups(
    q: str = Query(..., min_length=1, description="Search query string (e.g. 'ИНБ')"),
    repo: ScheduleRepository = Depends(get_schedule_repo),
) -> GroupSearchResponse:
    query = q.strip()
    results = await repo.search_tracked_groups(query)
    return GroupSearchResponse(query=query, results=results, count=len(results))
