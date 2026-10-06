"""
Pydantic DTO schemas for TimeSyncBot REST API v1.
"""
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="ok", description="Overall service status")
    timestamp: str = Field(..., description="Current ISO timestamp")
    database_connected: bool = Field(..., description="SQLite database connectivity check")
    tracked_groups_count: int = Field(..., description="Number of tracked student groups in DB")
    teachers_mapped: bool = Field(..., description="True if teacher curriculum is mapped into memory/DB")
    teachers_count: int = Field(..., description="Total mapped teachers available")


class LessonDTO(BaseModel):
    pair_number: int = Field(..., ge=1, le=7, description="Lesson pair index (1-7)")
    start_time: str = Field(..., description="Lesson start time (HH:MM)")
    end_time: str = Field(..., description="Lesson end time (HH:MM)")
    subject: str = Field(..., description="Discipline title")
    class_type: Optional[str] = Field(None, description="Type: Лекция, Практика, Лаб. работа")
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
    days: int = Field(default=7, description="Count of days in response")
    schedule: List[DayScheduleDTO] = Field(..., description="Days schedule list")


class GroupSearchResponse(BaseModel):
    query: str = Field(..., description="Search query string")
    results: List[str] = Field(..., description="Matching group names")
    count: int = Field(..., description="Number of matches")


class TeacherSearchResponse(BaseModel):
    query: str = Field(..., description="Search query string")
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


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Standard machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Any] = Field(None, description="Additional context or validation errors")


class ErrorResponse(BaseModel):
    error: ErrorDetail = Field(..., description="Error details payload")
