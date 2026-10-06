"""
Campus occupancy and free classrooms router.
Single responsibility: Querying university buildings and available classrooms.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from tgbot.api.dependencies import get_occupancy_repo, get_occupancy_service
from tgbot.api.schemas import AvailablePairsResponse, BuildingsResponse, FreeRoomsResponse
from tgbot.config import config
from tgbot.database.repositories import OccupancyRepository
from tgbot.services.services import OccupancyService

router = APIRouter(prefix="/occupancy", tags=["Occupancy"])


@router.get(
    "/buildings",
    response_model=BuildingsResponse,
    summary="List University Buildings",
    description="Returns all campus buildings that have classroom occupancy tracking.",
)
async def list_buildings(
    repo: OccupancyRepository = Depends(get_occupancy_repo),
) -> BuildingsResponse:
    buildings = await repo.get_buildings()
    sorted_buildings = sorted(buildings, key=lambda x: int(x) if x.isdigit() else 999)
    return BuildingsResponse(buildings=sorted_buildings, count=len(sorted_buildings))


@router.get(
    "/available-pairs",
    response_model=AvailablePairsResponse,
    summary="Get Available Lesson Pairs for Building",
    description="Returns list of pair numbers (1-7) that have schedule records for the specified building and date.",
)
async def get_available_pairs(
    building: str = Query(..., description="Campus building number (e.g. '1', '14')"),
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Target date in YYYY-MM-DD format (defaults to current day)",
    ),
    service: OccupancyService = Depends(get_occupancy_service),
) -> AvailablePairsResponse:
    clean_building = building.strip()
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

    pairs = await service.get_available_pairs(target_date, clean_building)
    return AvailablePairsResponse(
        building=clean_building,
        date=target_date.isoformat(),
        available_pairs=sorted(pairs),
    )


@router.get(
    "/free-rooms",
    response_model=FreeRoomsResponse,
    summary="Find Empty Classrooms",
    description="Finds unoccupied rooms in the specified building for a given date and lesson pair index.",
)
async def find_free_classrooms(
    building: str = Query(..., description="Campus building number (e.g. '1', '14')"),
    pair: int = Query(..., ge=1, le=7, description="Lesson pair index (1 to 7)"),
    date_str: Optional[str] = Query(
        None,
        alias="date",
        description="Target date in YYYY-MM-DD format (defaults to current day)",
    ),
    service: OccupancyService = Depends(get_occupancy_service),
) -> FreeRoomsResponse:
    clean_building = building.strip()
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

    free_rooms_set = await service.find_free_rooms(target_date, pair, clean_building)
    sorted_rooms = sorted(free_rooms_set)
    time_slot = config.STANDARD_PAIRS.get(pair)

    return FreeRoomsResponse(
        building=clean_building,
        date=target_date.isoformat(),
        pair_number=pair,
        time=time_slot,
        free_rooms=sorted_rooms,
        count=len(sorted_rooms),
    )
