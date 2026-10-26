import os
from typing import List, Dict, Optional
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore'  # Ignore extra env vars
    )

    # ===== Bot client (TimeSyncBot) =====
    BOT_TOKEN: str = Field(default="")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    @property
    def ADMIN_IDS(self) -> List[int]:
        """Parse ADMIN_IDS from environment variable - comma-separated integers"""
        if not self.admin_ids_raw:
            return []
        try:
            return [int(x.strip()) for x in self.admin_ids_raw.split(',') if x.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid ADMIN_IDS format. Expected comma-separated integers, got: {self.admin_ids_raw}") from e

    # Client -> server
    SERVER_URL: str = Field(default="http://localhost:8000")

    # Shared secret for the internal REST API (/api/v1/internal/*) used by the bot client
    BOT_API_KEY: str = Field(default="")

    # Path configurations (environment-driven via pydantic-settings)
    DATA_DIR: str = Field(default="./data")
    DB_DIR: str = Field(default="./data")
    LOG_DIR: str = Field(default="./logs")

    # ===== Server (TimeSyncBot server / API) =====
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
    api_keys_raw: str = Field(default="", alias="API_KEYS")
    API_RATE_LIMIT_PUBLIC: int = Field(default=60)   # req / min for anonymous clients
    API_RATE_LIMIT_AUTH: int = Field(default=300)    # req / min for authenticated clients

    @property
    def API_KEYS(self) -> List[str]:
        """Parse allowed API keys from environment variable (comma-separated)."""
        if not self.api_keys_raw:
            return []
        return [k.strip() for k in self.api_keys_raw.split(",") if k.strip()]

    # Database paths
    @property
    def DB_NAME(self) -> str:
        return os.path.join(self.DB_DIR, "piculi.db")

    @property
    def ANALYTICS_DB_NAME(self) -> str:
        return os.path.join(self.DB_DIR, "analytics.db")

    # Timezone used by the server & bot notification scheduler (default MSK)
    TIMEZONE: str = Field(default="Europe/Moscow", validation_alias=AliasChoices("TIMEZONE", "TZ"))

    @property
    def tz(self):
        """IANA timezone object (Europe/Moscow default) — never naive, fixes digest-at-00:00 bug."""
        from zoneinfo import ZoneInfo
        try:
            return ZoneInfo(self.TIMEZONE)
        except Exception as e:
            import logging
            logging.getLogger("timesync.config").warning(f"Unknown timezone '{self.TIMEZONE}', falling back to UTC: {e}")
            return ZoneInfo("UTC")

    # Словарь времени пар для конвертации в pair_number
    TIME_SLOTS: Dict[str, int] = {
        "08:20": 1, "08:20-09:50": 1,
        "10:00": 2, "10:00-11:30": 2,
        "11:45": 3, "11:45-13:15": 3,
        "14:00": 4, "14:00-15:30": 4,
        "15:45": 5, "15:45-17:15": 5,
        "17:20": 6, "17:20-18:50": 6,
        "18:55": 7, "18:55-20:25": 7
    }

    # Эталонные интервалы пар ВятГУ
    STANDARD_PAIRS: Dict[int, str] = {
        1: "08:20 - 09:50",
        2: "10:00 - 11:30",
        3: "11:45 - 13:15",
        4: "14:00 - 15:30",
        5: "15:45 - 17:15",
        6: "17:20 - 18:50",
        7: "18:55 - 20:25"
    }

    # Время начала пар
    STANDARD_PAIR_STARTS: Dict[int, str] = {
        1: "08:20",
        2: "10:00",
        3: "11:45",
        4: "14:00",
        5: "15:45",
        6: "17:20",
        7: "18:55"
    }

    # ===== VyatSU website constants (centralized) =====
    VYATSU_BASE_URL: str = "https://www.vyatsu.ru/"
    SCHEDULE_URL: str = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/raspisanie-zanyatiy-dlya-studentov.html"
    OCCUPANCY_URL: str = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/zanyatost-auditoriy.html"
    TEACHER_URL: str = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/teacher.html"
    # NOTE: vyatsu.ru tarpits browser-like User-Agents (request hangs until
    # timeout) but answers tool UAs. Verified 2026-09-23: curl/8.14.1 -> 200
    # in ~1.5s, while Chrome/Firefox/Wget/custom UAs all timed out.
    HTTP_HEADERS: Dict[str, str] = {
        "User-Agent": "curl/8.14.1"
    }

    @property
    def now_local(self):
        """Current datetime in server/client timezone (tz-aware)."""
        from datetime import datetime
        return datetime.now(self.tz)


config = Settings()
