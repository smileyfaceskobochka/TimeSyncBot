import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from tgbot.client.gateway import (
    UserRepository,
    ScheduleRepository,
    OccupancyRepository,
    AnalyticsRepository,
    GroupChatRepository,
    ParserSchedulerService,
    TeacherGateway,
)
from tgbot.notification_scheduler import NotificationSchedulerService
from tgbot.handlers.admin_parser_commands import admin_parser_router
from tgbot.config import config
from tgbot.services.logger import setup_logging
from tgbot.services.services import ScheduleService, OccupancyService
from tgbot.handlers.meetings import meeting_router
from tgbot.handlers.group_chat import group_chat_router
from tgbot.handlers.user import user_router
from tgbot.handlers.schedule import schedule_router
from tgbot.handlers.settings import settings_router
from tgbot.handlers.free_rooms import free_rooms_router
from tgbot.handlers.favorites import favorites_router
from tgbot.handlers.admin import admin_router
from tgbot.handlers.teacher import teacher_router
from tgbot.handlers.feedback import feedback_router
from tgbot.handlers.inline_mode import inline_router

# Global reference for signal handler
parser_scheduler = None


def signal_handler(sig, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT"""
    logging.info("⏹️ Received shutdown signal, gracefully shutting down...")
    if parser_scheduler:
        asyncio.create_task(parser_scheduler.close())
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

    # HTTP gateway to the TimeSync server (core service)
    user_repo = UserRepository(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)
    schedule_repo = ScheduleRepository(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)
    occupancy_repo = OccupancyRepository(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)
    analytics_repo = AnalyticsRepository(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)
    group_chat_repo = GroupChatRepository(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)
    teacher = TeacherGateway(base_url=config.SERVER_URL, api_key=config.BOT_API_KEY)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    parser_scheduler = NotificationSchedulerService(
        schedule_repo=schedule_repo,
        analytics_repo=analytics_repo,
        group_chat_repo=group_chat_repo,
        user_repo=user_repo,
        bot=bot,
    )

    dp.include_routers(
        group_chat_router,
        user_router,
        schedule_router,
        settings_router,
        free_rooms_router,
        favorites_router,
        admin_router,
        admin_parser_router,
        meeting_router,
        teacher_router,
        feedback_router,
        inline_router
    )

    parser_scheduler.start()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logging.info("✓ Signal handlers registered")

    # Setup contextual command menus and bot descriptions
    from tgbot.services.bot_commands import setup_bot_metadata
    await setup_bot_metadata(bot)

    try:
        logging.info("Bot is ready and polling started!")
        await dp.start_polling(
            bot,
            user_repo=user_repo,
            schedule_repo=schedule_repo,
            occupancy_repo=occupancy_repo,
            analytics_repo=analytics_repo,
            group_chat_repo=group_chat_repo,
            service=ScheduleService(),
            parser_scheduler=parser_scheduler,
            occupancy_service=OccupancyService(occupancy_repo),
            teacher=teacher,
        )
    except Exception as e:
        logging.error(f"❌ Bot error: {e}", exc_info=True)
        raise
    finally:
        logging.info("Shutting down bot...")
        await user_repo.close()
        await schedule_repo.close()
        await occupancy_repo.close()
        await analytics_repo.close()
        await group_chat_repo.close()
        await teacher.close()
        if parser_scheduler:
            parser_scheduler.stop()
        await bot.session.close()
        logging.info("Bot stopped successfully.")


if __name__ == "__main__":
    asyncio.run(main())
