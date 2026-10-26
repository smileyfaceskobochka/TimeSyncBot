"""Backwards-compatible shim: shared formatting services live in core.services."""
from core.services import ScheduleService, OccupancyService, clean_lesson_meta, format_week_schedule_expandable  # noqa: F401

__all__ = ["ScheduleService", "OccupancyService", "clean_lesson_meta", "format_week_schedule_expandable"]
