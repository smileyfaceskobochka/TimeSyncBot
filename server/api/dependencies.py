"""
FastAPI dependencies provider for TimeSyncBot API.
Encapsulates resource lifecycles and dependency provision.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from server.database.repositories import DatabaseManager, OccupancyRepository, ScheduleRepository
from core.services import OccupancyService, ScheduleService


def get_db(request: Request) -> DatabaseManager:
    """Provides DatabaseManager from application state."""
    db: Optional[DatabaseManager] = getattr(request.app.state, "db", None)
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


def verify_internal_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Internal API (bot client <-> server) authentication via shared BOT_API_KEY."""
    from core.config import config
    if not config.BOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API is disabled: BOT_API_KEY is not configured.",
        )
    if x_api_key != config.BOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API key. Provide the 'X-API-Key' header.",
        )
