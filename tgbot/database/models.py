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
    favorite_teachers_json: str = Field(default="[]")

    def __init__(self, **data):
        if "favorites" in data:
            favs = data.pop("favorites")
            if isinstance(favs, list):
                data["favorites_json"] = json.dumps(favs, ensure_ascii=False)
        if "favorite_teachers" in data:
            ft = data.pop("favorite_teachers")
            if isinstance(ft, list):
                data["favorite_teachers_json"] = json.dumps(ft, ensure_ascii=False)
        if "settings" in data:
            st = data.pop("settings")
            if isinstance(st, UserSettings):
                data["settings_json"] = st.model_dump_json()
            elif isinstance(st, dict):
                data["settings_json"] = json.dumps(st, ensure_ascii=False)
        super().__init__(**data)

    @property
    def settings(self) -> UserSettings:
        try:
            data = json.loads(self.settings_json)
            return UserSettings(**data)
        except (json.JSONDecodeError, ValueError, TypeError):
            return UserSettings()

    @settings.setter
    def settings(self, value: UserSettings):
        self.settings_json = value.model_dump_json()

    @property
    def favorites(self) -> List[str]:
        try:
            return json.loads(self.favorites_json)
        except (json.JSONDecodeError, ValueError, TypeError):
            return []

    @favorites.setter
    def favorites(self, value: List[str]):
        self.favorites_json = json.dumps(value)

    @property
    def favorite_teachers(self) -> List[str]:
        try:
            return json.loads(self.favorite_teachers_json)
        except (json.JSONDecodeError, ValueError, TypeError):
            return []

    @favorite_teachers.setter
    def favorite_teachers(self, value: List[str]):
        self.favorite_teachers_json = json.dumps(value)

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
    is_free: bool = Field(default=True)
    group_name: Optional[str] = None

class ActionLog(SQLModel, table=True):
    __tablename__ = "action_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    action: str = Field()
    details: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: date.today().isoformat())

class GroupChat(SQLModel, table=True):
    __tablename__ = "group_chats"
    chat_id: int = Field(primary_key=True)
    title: Optional[str] = None
    group_name: str = Field(index=True)
    auto_post: bool = Field(default=True)
    post_time: str = Field(default="07:00")
    post_target: str = Field(default="today")  # "today" or "tomorrow"
    pin_message: bool = Field(default=False)
    topic_id: Optional[int] = Field(default=None)
    pin_replies: bool = Field(default=False)
    created_at: str = Field(default_factory=lambda: date.today().isoformat())
    updated_at: str = Field(default_factory=lambda: date.today().isoformat())
