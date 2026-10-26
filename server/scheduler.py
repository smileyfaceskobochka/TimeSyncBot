"""
TimeSyncBot server-side scheduler (core service).
Runs ONLY data jobs — parser, daily sync, maintenance, occupancy sync.
Timezone-aware: every trigger uses core.config config.tz (default Europe/Moscow),
which fixes the digest-at-~00:00 class of bugs in the notification side.
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from server.services.parser.runner import run_pipeline, cleanup_filesystem
from server.services.parser.occupancy_parser import update_occupancy
from core.config import config
from server.database.repositories import ScheduleRepository, AnalyticsRepository

logger = logging.getLogger("timesync.server.scheduler")


class ParserSchedulerService:
    def __init__(self, db_manager=None, schedule_repo=None, analytics_repo=None):
        self.scheduler = AsyncIOScheduler(timezone=config.tz)
        self.db_manager = db_manager
        self.schedule_repo = schedule_repo
        self.analytics_repo = analytics_repo
        self.last_run = None
        self.last_status = None
        self.stats = {"total_runs": 0, "successful_runs": 0, "failed_runs": 0}

    async def run_parser_process(self):
        start_time = datetime.now(config.tz)
        self.stats["total_runs"] += 1
        logger.info("⏳ Запуск встроенного парсинга расписания...")
        try:
            await run_pipeline(db_manager=self.db_manager)
            self.stats["successful_runs"] += 1
            self.last_status = "success"
            self.last_run = datetime.now(config.tz)
            logger.info(f"✅ Парсинг завершен успешно за {(self.last_run - start_time).total_seconds():.1f}с")
        except Exception as e:
            self.stats["failed_runs"] += 1
            self.last_status = "failed"
            self.last_run = datetime.now(config.tz)
            logger.error(f"❌ Ошибка планировщика парсера: {e}", exc_info=True)

    async def run_daily_sync(self):
        logger.info("📡 Запуск ежедневной синхронизации с веб-сайтом (5:00 AM)...")
        try:
            await run_pipeline(db_manager=self.db_manager)
            logger.info("✅ Ежедневная синхронизация завершена успешно.")
        except Exception as e:
            logger.error(f"❌ Ошибка при ежедневной синхронизации: {e}", exc_info=True)

    async def run_maintenance(self):
        logger.info("🧹 Запуск планового обслуживания...")
        try:
            await cleanup_filesystem(weeks=5)
            if self.schedule_repo:
                await self.schedule_repo.cleanup_old_lessons(weeks=26)
            if self.analytics_repo:
                await self.analytics_repo.cleanup_old_logs(days=90)
            logger.info("✅ Обслуживание завершено успешно.")
        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении обслуживания: {e}", exc_info=True)

    async def run_occupancy_sync(self):
        logger.info("🏢 Запуск плановой синхронизации занятости аудиторий...")
        try:
            await update_occupancy(self.db_manager.engine)
            logger.info("✅ Синхронизация занятости завершена успешно.")
        except Exception as e:
            logger.error(f"❌ Ошибка при синхронизации занятости: {e}", exc_info=True)

    def start(self):
        self.scheduler.add_job(self.run_daily_sync, "cron", hour="5", minute="0", id="daily_sync_job")
        self.scheduler.add_job(self.run_parser_process, "cron", hour="6", minute="50", id="parser_job")
        self.scheduler.add_job(self.run_maintenance, "cron", day_of_week="sun", hour="4", minute="0", id="maintenance_job")
        self.scheduler.add_job(self.run_occupancy_sync, "interval", hours=4, id="occupancy_sync_job")
        self.scheduler.start()
        logger.info("⚙️ Серверный планировщик запущен (TZ=%s)", config.TIMEZONE)
        logger.info("   Job daily_sync - каждый день в 5:00 AM")
        logger.info("   Job parser - каждый день в 6:50 AM")
        logger.info("   Job maintenance - каждое воскресенье в 4:00 AM")
        logger.info("   Job occupancy_sync - каждые 4 часа")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("⏹️ Серверный планировщик остановлен.")

    def get_status(self):
        return {
            "running": self.scheduler.running,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "stats": self.stats.copy(),
        }

    async def run_now(self):
        await self.run_parser_process()


parser_scheduler = ParserSchedulerService()
