"""TimeSyncBot core service entrypoint: `python -m server.main`.

Runs the FastAPI REST API (public /api/v1 + internal /api/v1/internal) and the
server-side scheduler (parser, daily sync, occupancy sync, maintenance).
No aiogram import here — Telegram logic lives in the bot client (root main.py).
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from core.config import config
from tgbot.services.logger import setup_logging
from server.api.server import create_app
from server.database.repositories import DatabaseManager, UserRepository, ScheduleRepository, OccupancyRepository, AnalyticsRepository, GroupChatRepository
from server.scheduler import parser_scheduler
from server.services.parser.site_to_pdf import sync_groups_list

parser_scheduler_instance = None


def signal_handler(sig, frame):
    logging.info("⏹️ Received shutdown signal, gracefully shutting down server...")
    if parser_scheduler_instance:
        parser_scheduler_instance.stop()
    sys.exit(0)


async def main():
    global parser_scheduler_instance
    setup_logging()
    logging.info("Starting TimeSyncBot server...")

    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.DB_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    logging.info(f"✓ Data directories created: {config.DATA_DIR}, {config.DB_DIR}, {config.LOG_DIR}")

    db_manager = DatabaseManager(config.DB_NAME)
    analytics_db_manager = DatabaseManager(config.ANALYTICS_DB_NAME)

    await UserRepository(db_manager).create_tables()
    await AnalyticsRepository(analytics_db_manager).create_tables()
    await GroupChatRepository(db_manager).create_tables()
    logging.info("✓ Database tables initialized")

    tracked_count = await ScheduleRepository(db_manager).get_tracked_groups_count()
    if tracked_count == 0:
        logging.info("🚀 First run detected. Syncing university groups list...")
        sync_ok = await sync_groups_list(db_manager.engine)
        if not sync_ok:
            logging.warning("⚠️ VyatSU website is currently unreachable. Server will start with cached data.")

    api_app = create_app(db_manager)
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(api_app, host=config.API_HOST, port=config.API_PORT, log_level="info", access_log=False)
    )
    uvicorn_server.install_signal_handlers = lambda: None
    asyncio.create_task(uvicorn_server.serve())
    logging.info(f"🌐 FastAPI server started on http://{config.API_HOST}:{config.API_PORT}")

    parser_scheduler_instance = parser_scheduler
    parser_scheduler.db_manager = db_manager
    parser_scheduler.schedule_repo = ScheduleRepository(db_manager)
    parser_scheduler.analytics_repo = AnalyticsRepository(analytics_db_manager)
    parser_scheduler.start()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logging.info("✓ Signal handlers registered; server is ready")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        logging.info("Shutting down server...")
        uvicorn_server.should_exit = True
        if parser_scheduler_instance:
            parser_scheduler_instance.stop()
        logging.info("Server stopped successfully.")


if __name__ == "__main__":
    asyncio.run(main())
