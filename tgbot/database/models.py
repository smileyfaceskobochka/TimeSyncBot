from __future__ import annotations
from datetime import date
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from pydantic import BaseModel
import json

class UserSettings(BaseModel):
    show_teachers: bool = True
    show_building: bool = True
    show_windows: bool = True

class User(SQLModel, table=True):
    telegram_id: int = Field(primary_key=True)
    username: Optional[str] = None
    full_name: Optional[str] = None
    group_name: Optional[str] = None
    role: str = Field(default="user")
    curator_group: Optional[str] = None
    settings_json: str = Field(default="{}")
    favorites_json: str = Field(default="[]")

    @property
    def settings(self) -> UserSettings:
        try:
            data = json.loads(self.settings_json)
            return UserSettings(**data)
        except:
            return UserSettings()

    @settings.setter
    def settings(self, value: UserSettings):
        self.settings_json = value.model_dump_json()

    @property
    def favorites(self) -> List[str]:
        try:
            return json.loads(self.favorites_json)
        except:
            return []

    @favorites.setter
    def favorites(self, value: List[str]):
        self.favorites_json = json.dumps(value)

class Lesson(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_name: str = Field(index=True)
    date: str = Field(index=True)
    pair_number: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    subject: Optional[str] = None
    class_type: Optional[str] = None
    teacher: Optional[str] = Field(default=None, index=True)
    building: Optional[str] = None
    room: Optional[str] = None
    subgroup: Optional[str] = None
    raw_info: Optional[str] = None

class TrackedGroup(SQLModel, table=True):
    __tablename__ = "tracked_groups"
    group_name: str = Field(primary_key=True)
    is_tracked: bool = Field(default=False)

class ProcessedFile(SQLModel, table=True):
    __tablename__ = "processed_files"
    filename: str = Field(primary_key=True)
    file_hash: str = Field()
    last_updated: str = Field(default_factory=lambda: date.today().isoformat())
    file_type: Optional[str] = None

class BotSetting(SQLModel, table=True):
    __tablename__ = "bot_settings"
    key: str = Field(primary_key=True)
    value: str = Field()

class Occupancy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    building: str = Field(index=True)
    room: str = Field(index=True)
    date: str = Field(index=True)
    pair_number: int = Field()
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class ActionLog(SQLModel, table=True):
    __tablename__ = "action_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    action: str = Field()
    details: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: date.today().isoformat())
