"""Backwards-compatible shim: repository access now goes through the HTTP client gateway."""
from tgbot.client.gateway import (  # noqa: F401
    ServerGateway,
    ServerUnavailable,
    UserRepository,
    TeacherGateway,
    ScheduleRepository,
    OccupancyRepository,
    AnalyticsRepository,
    GroupChatRepository,
    ParserSchedulerService,
)

__all__ = [
    "ServerGateway",
    "ServerUnavailable",
    "UserRepository",
    "TeacherGateway",
    "ScheduleRepository",
    "OccupancyRepository",
    "AnalyticsRepository",
    "GroupChatRepository",
    "ParserSchedulerService",
]
