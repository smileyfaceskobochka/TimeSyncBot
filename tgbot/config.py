import os
from pathlib import Path
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding='utf-8', 
        extra='ignore'  # Ignore extra env vars TZ
    )
    
    BOT_TOKEN: str
    
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
    
    # Path configurations (environment-driven)
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    DB_DIR: str = os.getenv("DB_DIR", "./data")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")
    
    # Database paths
    @property
    def DB_NAME(self) -> str:
        return os.path.join(self.DB_DIR, "piculi.db")
    
    @property
    def ANALYTICS_DB_NAME(self) -> str:
        return os.path.join(self.DB_DIR, "analytics.db")
    
    # Словарь времени пар для конвертации в pair_number
    TIME_SLOTS: dict = {
        "08:20": 1, "08:20-09:50": 1,
        "10:00": 2, "10:00-11:30": 2,
        "11:45": 3, "11:45-13:15": 3,
        "14:00": 4, "14:00-15:30": 4,
        "15:45": 5, "15:45-17:15": 5,
        "17:20": 6, "17:20-18:50": 6,
        "18:55": 7, "18:55-20:25": 7
    }

    # ===== VyatSU website constants (centralized) =====
    VYATSU_BASE_URL: str = "https://www.vyatsu.ru/"
    SCHEDULE_URL: str = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/raspisanie-zanyatiy-dlya-studentov.html"
    OCCUPANCY_URL: str = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/zanyatost-auditoriy.html"
    HTTP_HEADERS: dict = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

config = Settings()