import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tgbot.config import config

def setup_logging():
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Prevent duplicate handlers
    root_logger.handlers.clear()

    # Console handler (standard stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Persistent rotating file handler (10 MB, 3 backups)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to setup file logger: {e}\n")

    # Specific loggers
    logging.getLogger('aiogram').setLevel(logging.INFO)
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.INFO)
