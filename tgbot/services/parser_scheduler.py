import asyncio
import logging
import re
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tgbot.services.parser.runner import run_pipeline, cleanup_filesystem

class ParserSchedulerService:
    
    def __init__(self, db_manager=None, schedule_repo=None, analytics_repo=None, run_on_startup: bool = False):
        """
        Args:
            db_manager: Database manager instance
            schedule_repo: Schedule repository instance
            analytics_repo: Analytics repository instance
            run_on_startup: Запускать ли парсер сразу при старте бота
        """
        self.scheduler = AsyncIOScheduler()
        self.db_manager = db_manager
        self.schedule_repo = schedule_repo
        self.analytics_repo = analytics_repo
        self.run_on_startup = run_on_startup
        self.last_run = None
        self.last_status = None
        self.stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0
        }

    def _parse_output(self, output: str) -> dict:
        """
        Парсит вывод скрипта для извлечения статистики.
        Ищет паттерны типа:
        - "📊 Results: 5 to parse, 15 skipped"
        - "Processed: 3"
        - "Total files: 18"
        """
        stats = {}
        
        # Паттерны для поиска
        patterns = {
            'to_parse': r'(\d+)\s+to\s+parse',
            'skipped': r'(\d+)\s+skipped',
            'processed': r'[Pp]rocessed:\s*(\d+)',
            'total_files': r'[Tt]otal\s+files:\s*(\d+)',
            'errors': r'[Ee]rrors:\s*(\d+)'
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                stats[key] = int(match.group(1))
        
        return stats

    async def run_parser_process(self):
        """Запускает процесс парсинга средствами бота"""
        start_time = datetime.now()
        self.stats["total_runs"] += 1
        
        logging.info("⏳ Запуск встроенного парсинга расписания...")
        
        try:
            # Вместо запуска внешнего процесса вызываем run_pipeline напрямую
            await run_pipeline(db_manager=self.db_manager)
            
            duration = (datetime.now() - start_time).total_seconds()
            self.stats["successful_runs"] += 1
            self.last_status = "success"
            self.last_run = datetime.now()
            
            logging.info(f"✅ Парсинг завершен успешно за {duration:.1f}с")
                    
        except Exception as e:
            self.stats["failed_runs"] += 1
            self.last_status = "failed"
            self.last_run = datetime.now()
            logging.error(f"❌ Ошибка в планировщике парсера: {e}", exc_info=True)

    async def run_maintenance(self):
        """Запускает очистку данных и логов"""
        logging.info("🧹 Запуск планового обслуживания...")
        try:
            # 1. Очистка файлов (удаляет PDF старше 5 недель)
            await cleanup_filesystem(weeks=5)
            
            # 2. Очистка БД - удаляет старые записи
            if self.schedule_repo:
                # Удаляет занятия старше 6 месяцев (26 недель)
                await self.schedule_repo.cleanup_old_lessons(weeks=26)
            if self.analytics_repo:
                # Удаляет логи старше 90 дней
                await self.analytics_repo.cleanup_old_logs(days=90)
                
            logging.info("✅ Обслуживание завершено успешно.")
        except Exception as e:
            logging.error(f"❌ Ошибка при выполнении обслуживания: {e}")

    async def run_daily_sync(self):
        """Запускает ежедневную синхронизацию с веб-сайтом университета в 5:00 AM"""
        logging.info("📡 Запуск ежедневной синхронизации с веб-сайтом (5:00 AM)...")
        try:
            await run_pipeline(db_manager=self.db_manager)
            logging.info("✅ Ежедневная синхронизация завершена успешно.")
        except Exception as e:
            logging.error(f"❌ Ошибка при ежедневной синхронизации: {e}", exc_info=True)

    def start(self, interval_hours: int = 12):
        """
        Запускает планировщик парсера.
        
        Args:
            interval_hours: Интервал между запусками в часах (по умолчанию 3)
        """
        # Настраиваем расписание
        # self.scheduler.add_job(
            # self.run_parser_process, 
            # "interval", 
            # hours=interval_hours,
            # id="parser_job"
        # )
        
        # Альтернативный вариант - запуск в конкретное время:
        self.scheduler.add_job(
            self.run_parser_process, 
            "cron", 
            hour="6",
            minute="50",
            id="parser_job"
        )
        
        # Ежедневная синхронизация в 5:00 AM с веб-сайтом университета
        self.scheduler.add_job(
            self.run_daily_sync,
            "cron",
            hour="5",
            minute="0",
            id="daily_sync_job"
        )
        
        # Добавляем обслуживание каждое воскресенье в 4 утра
        self.scheduler.add_job(
            self.run_maintenance,
            "cron",
            day_of_week="sun",
            hour="4",
            minute="0",
            id="maintenance_job"
        )
        
        self.scheduler.start()
        logging.info(f"⚙️ Планировщик парсера запущен")
        logging.info(f"   📅 Job 1: Парсинг расписания - каждый день в 6:50 AM")
        logging.info(f"   📡 Job 2: Синхронизация с веб-сайтом - каждый день в 5:00 AM")
        logging.info(f"   🧹 Job 3: Плановое обслуживание - каждое воскресенье в 4:00 AM")
        
        # Запуск парсера сразу при старте (если включено)
        if self.run_on_startup:
            logging.info("🚀 Запуск парсера при старте бота...")
            asyncio.create_task(self.run_parser_process())

    def stop(self):
        """Останавливает планировщик"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logging.info("⏹️ Планировщик парсера остановлен.")
            
            # Логируем финальную статистику
            logging.info(
                f"   📊 Итоговая статистика:\n"
                f"      • Всего запусков: {self.stats['total_runs']}\n"
                f"      • Успешных: {self.stats['successful_runs']}\n"
                f"      • Ошибок: {self.stats['failed_runs']}"
            )

    def get_status(self) -> dict:
        """Возвращает текущий статус планировщика"""
        return {
            "running": self.scheduler.running if hasattr(self.scheduler, 'running') else False,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "stats": self.stats.copy()
        }

    async def run_now(self):
        """Принудительный запуск парсера прямо сейчас (для админ-команд)"""
        logging.info("🔧 Ручной запуск парсера...")
        await self.run_parser_process()