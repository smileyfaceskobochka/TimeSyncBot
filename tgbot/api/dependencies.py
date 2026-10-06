"""
FastAPI dependencies provider for TimeSyncBot API.
Encapsulates resource lifecycles and dependency provision.
"""
from fastapi import Depends, HTTPException, Request, status
from tgbot.database.repositories import DatabaseManager, OccupancyRepository, ScheduleRepository
from tgbot.services.services import OccupancyService, ScheduleService


def get_db(request: Request) -> DatabaseManager:
    """Provides DatabaseManager from application state."""
    db: DatabaseManager | None = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DatabaseManager is not initialized.",
        )
    return db


def get_schedule_repo(db: DatabaseManager = Depends(get_db)) -> ScheduleRepository:
    """Provides ScheduleRepository instance."""
    return ScheduleRepository(db)


def get_occupancy_repo(db: DatabaseManager = Depends(get_db)) -> OccupancyRepository:
    """Provides OccupancyRepository instance."""
    return OccupancyRepository(db)


def get_occupancy_service(repo: OccupancyRepository = Depends(get_occupancy_repo)) -> OccupancyService:
    """Provides OccupancyService instance."""
    return OccupancyService(repo)


def get_schedule_service() -> ScheduleService:
    """Provides ScheduleService instance."""
    return ScheduleService()
