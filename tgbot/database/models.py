"""Backwards-compatible shim: DB models live in the shared core package."""
from core.models import (  # noqa: F401
    User,
    UserSettings,
    Lesson,
    TrackedGroup,
    ProcessedFile,
    TeacherCurriculum,
    BotSetting,
    Occupancy,
    ActionLog,
    GroupChat,
)
