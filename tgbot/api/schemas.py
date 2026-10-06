"""
Pydantic DTO schemas for TimeSyncBot REST API v1.
Unix Philosophy: Clean, minimal, composable data transfer objects.
"""
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ================= System Schemas =================

class HealthResponse(BaseModel):
    status: str = Field(default="ok", description="Overall service status (ok | degraded)")
    timestamp: str = Field(..., description="Current ISO timestamp")
    database_connected: bool = Field(..., description="SQLite database connectivity check")
    tracked_groups_count: int = Field(..., description="Number of tracked student groups in DB")
    teachers_mapped: bool = Field(..., description="True if teacher curriculum is mapped into memory/DB")
    teachers_count: int = Field(..., description="Total mapped teachers available")


# ================= Group & Schedule Schemas =================

class LessonDTO(BaseModel):
    pair_number: int = Field(..., ge=1, le=7, description="Lesson pair index (1-7)")
    start_time: str = Field(..., description="Lesson start time (HH:MM)")
    end_time: str = Field(..., description="Lesson end time (HH:MM)")
    subject: str = Field(..., description="Discipline title")
    class_type: Optional[str] = Field(None, description="Class type: Лекция, Практика, Лаб. работа")
    teacher: Optional[str] = Field(None, description="Teacher full name")
    building: Optional[str] = Field(None, description="University building number")
    room: Optional[str] = Field(None, description="Classroom number")
    subgroup: Optional[int] = Field(None, description="Subgroup index (e.g. 1 or 2)")


class DayScheduleDTO(BaseModel):
    date: str = Field(..., description="Date formatted as YYYY-MM-DD")
    predicted: bool = Field(default=False, description="Whether schedule was predicted from previous cycle")
    lessons: List[LessonDTO] = Field(default_factory=list, description="Lessons scheduled for this day")


class ScheduleResponse(BaseModel):
    group: str = Field(..., description="University group name")
    start_date: str = Field(..., description="Start date of the schedule window (YYYY-MM-DD)")
    days: int = Field(..., description="Count of days in response")
    schedule: List[DayScheduleDTO] = Field(..., description="Days schedule list")


class GroupSearchResponse(BaseModel):
    query: Optional[str] = Field(None, description="Search query string or null if all returned")
    results: List[str] = Field(..., description="Matching group names")
    count: int = Field(..., description="Number of matches")


# ================= Teacher Schemas =================

class TeacherSearchResponse(BaseModel):
    query: Optional[str] = Field(None, description="Search query string or null if all returned")
    results: List[str] = Field(..., description="Matching teacher names")
    count: int = Field(..., description="Number of matches")


class CurriculumRecordDTO(BaseModel):
    html_url: str = Field(..., description="Direct link to HTML schedule/curriculum view")
    xml_url: Optional[str] = Field(None, description="Direct link to XML/XLS schedule download")
    department: str = Field(..., description="Department or faculty name")


class TeacherCurriculumResponse(BaseModel):
    teacher: str = Field(..., description="Teacher full name")
    department: Optional[str] = Field(None, description="Primary department name")
    curriculum: List[CurriculumRecordDTO] = Field(..., description="Curriculum/study plan document links")
    count: int = Field(..., description="Total documents count")


class TeacherLessonDTO(BaseModel):
    date: str = Field(..., description="Lesson date (YYYY-MM-DD)")
    pair_number: Optional[int] = Field(None, description="Lesson pair index (1-7)")
    start_time: Optional[str] = Field(None, description="Start time (HH:MM)")
    end_time: Optional[str] = Field(None, description="End time (HH:MM)")
    subject: str = Field(..., description="Discipline title")
    class_type: Optional[str] = Field(None, description="Lesson type")
    building: Optional[str] = Field(None, description="Building number")
    room: Optional[str] = Field(None, description="Classroom number")
    group_name: Optional[str] = Field(None, description="Student academic group")


class TeacherDayScheduleDTO(BaseModel):
    date: str = Field(..., description="Date formatted as YYYY-MM-DD")
    lessons: List[TeacherLessonDTO] = Field(default_factory=list, description="Lessons for this day")


class TeacherScheduleResponse(BaseModel):
    teacher: str = Field(..., description="Teacher full name")
    department: Optional[str] = Field(None, description="Department name")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    days: int = Field(..., description="Number of days returned")
    schedule: List[TeacherDayScheduleDTO] = Field(..., description="Schedule per day")


# ================= Occupancy & Free Rooms Schemas =================

class BuildingsResponse(BaseModel):
    buildings: List[str] = Field(..., description="Available university campus buildings")
    count: int = Field(..., description="Total buildings count")


class AvailablePairsResponse(BaseModel):
    building: str = Field(..., description="Campus building number")
    date: str = Field(..., description="Target date (YYYY-MM-DD)")
    available_pairs: List[int] = Field(..., description="Pair numbers (1-7) with occupancy data")


class FreeRoomsResponse(BaseModel):
    building: str = Field(..., description="Campus building number")
    date: str = Field(..., description="Target date (YYYY-MM-DD)")
    pair_number: int = Field(..., description="Pair index (1-7)")
    time: Optional[str] = Field(None, description="Time interval (e.g. '08:20 - 09:50')")
    free_rooms: List[str] = Field(..., description="Available empty classrooms")
    count: int = Field(..., description="Number of free rooms")


# ================= Meeting Schemas =================

class FreeSlotDTO(BaseModel):
    pair_number: int = Field(..., description="Pair index (1-7)")
    time: str = Field(..., description="Standard interval (e.g. '10:00 - 11:30')")


class CommonFreeSlotsResponse(BaseModel):
    date: str = Field(..., description="Target date (YYYY-MM-DD)")
    groups: List[str] = Field(..., description="Groups compared")
    occupied_pairs: List[int] = Field(..., description="Pair numbers where at least one group has a lesson")
    free_pairs: List[FreeSlotDTO] = Field(..., description="Mutually free pairs where NO group has lessons")
    has_common_slots: bool = Field(..., description="True if at least one mutually free pair exists")


# ================= Error Schemas =================

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Standard machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Any] = Field(None, description="Additional context or validation details")


class ErrorResponse(BaseModel):
    error: ErrorDetail = Field(..., description="Error details payload")
