import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding='utf-8', 
        extra='ignore'  # Ignore extra env vars like ADMIN_IDS, TZ
    )
    
    BOT_TOKEN: str
    # Note: ADMIN_IDS is NOT a pydantic field to avoid env variable parsing issues
    # It's handled separately - see properties below
    
    @property
    def ADMIN_IDS(self) -> List[int]:
        """Parse ADMIN_IDS from environment variable - comma-separated integers"""
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        if not admin_ids_str:
            return []
        try:
            return [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid ADMIN_IDS format. Expected comma-separated integers, got: {admin_ids_str}") from e
    
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

config = Settings()