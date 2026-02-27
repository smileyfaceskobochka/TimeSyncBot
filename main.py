import asyncio
import logging
import signal
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from tgbot.services.parser_scheduler import ParserSchedulerService
from tgbot.handlers.admin_parser_commands import admin_parser_router
from tgbot.config import config
from tgbot.services.logger import setup_logging
from tgbot.database.repositories import (
    UserRepository,
    ScheduleRepository,
    OccupancyRepository,
    AnalyticsRepository
)
from tgbot.services.services import ScheduleService, OccupancyService
from tgbot.services.utils import check_connection
from tgbot.handlers.meetings import meeting_router
from tgbot.handlers.user import user_router
from tgbot.handlers.schedule import schedule_router
from tgbot.handlers.settings import settings_router
from tgbot.handlers.free_rooms import free_rooms_router
from tgbot.handlers.favorites import favorites_router
from tgbot.handlers.admin import admin_router

# Global reference for signal handler
parser_scheduler = None

def signal_handler(sig, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT"""
    logging.info("⏹️ Received shutdown signal, gracefully shutting down...")
    if parser_scheduler:
        parser_scheduler.stop()
    sys.exit(0)

async def main():
    global parser_scheduler
    
    setup_logging()
    logging.info("Starting bot...")
    
    # Validate required environment variables
    if not config.BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN environment variable is required")
    if not config.ADMIN_IDS:
        raise ValueError("❌ ADMIN_IDS environment variable is required")
    
    # Create required directories
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.DB_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    logging.info(f"✓ Data directories created: {config.DATA_DIR}, {config.DB_DIR}, {config.LOG_DIR}")

    from tgbot.database.repositories import DatabaseManager
    db_manager = DatabaseManager(config.DB_NAME)
    analytics_db_manager = DatabaseManager(config.ANALYTICS_DB_NAME)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    user_repo = UserRepository(db_manager)
    schedule_repo = ScheduleRepository(db_manager)
    occupancy_repo = OccupancyRepository(db_manager)
    analytics_repo = AnalyticsRepository(analytics_db_manager)

    await user_repo.create_tables()
    await analytics_repo.create_tables()
    logging.info("✓ Database tables initialized")
    
    # === STARTUP PROTECTION: ENSURE GROUPS LIST IS POPULATED ===
    tracked_count = await schedule_repo.get_tracked_groups_count()
    if tracked_count == 0:
        logging.info("🚀 First run detected. Syncing university groups list...")
        from tgbot.services.parser.site_to_pdf import sync_groups_list
        await sync_groups_list(db_manager.engine)

    schedule_service = ScheduleService()
    occupancy_service = OccupancyService(occupancy_repo)

    dp.include_routers(
        user_router,
        schedule_router,
        settings_router,
        free_rooms_router,
        favorites_router,
        admin_router,
        admin_parser_router,
        meeting_router
    )

    parser_scheduler = ParserSchedulerService(
        db_manager=db_manager,
        schedule_repo=schedule_repo,
        analytics_repo=analytics_repo
    )
    parser_scheduler.start()
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logging.info("✓ Signal handlers registered")

    try:
        logging.info("Bot is ready and polling started!")
        await dp.start_polling(
            bot,
            user_repo=user_repo,
            schedule_repo=schedule_repo,
            occupancy_repo=occupancy_repo,
            analytics_repo=analytics_repo,
            service=schedule_service,
            parser_scheduler=parser_scheduler,
            occupancy_service=occupancy_service
        )
    except Exception as e:
        logging.error(f"❌ Bot error: {e}", exc_info=True)
        raise
    finally:
        logging.info("Shutting down bot...")
        if parser_scheduler:
            parser_scheduler.stop()
        await bot.session.close()
        logging.info("Bot stopped successfully.")


if __name__ == "__main__":
    asyncio.run(main())
