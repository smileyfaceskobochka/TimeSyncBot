import asyncio
import logging
import re
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tgbot.services.parser.runner import run_pipeline, cleanup_filesystem

class ParserSchedulerService:
    
    def __init__(
        self, 
        db_manager=None, 
        schedule_repo=None, 
        analytics_repo=None, 
        group_chat_repo=None,
        user_repo=None,
        bot=None,
        run_on_startup: bool = False
    ):
        """
        Args:
            db_manager: Database manager instance
            schedule_repo: Schedule repository instance
            analytics_repo: Analytics repository instance
            group_chat_repo: Group chat repository instance
            user_repo: User repository instance
            bot: Bot instance for sending scheduled messages
            run_on_startup: Запускать ли парсер сразу при старте бота
        """
        self.scheduler = AsyncIOScheduler()
        self.db_manager = db_manager
        self.schedule_repo = schedule_repo
        self.analytics_repo = analytics_repo
        self.group_chat_repo = group_chat_repo
        self.user_repo = user_repo
        self.bot = bot
        self.run_on_startup = run_on_startup
        self.last_run = None
        self.last_status = None
        self._sent_lesson_alerts = set()  # (date_str, user_id, pair_number)
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

    async def run_occupancy_sync(self):
        """Запускает синхронизацию занятости аудиторий"""
        logging.info("🏢 Запуск плановой синхронизации занятости аудиторий...")
        try:
            from tgbot.services.parser.occupancy_parser import update_occupancy
            await update_occupancy(self.db_manager.engine)
            logging.info("✅ Синхронизация занятости завершена успешно.")
        except Exception as e:
            logging.error(f"❌ Ошибка при синхронизации занятости: {e}", exc_info=True)

    async def run_group_chat_broadcast(self):
        """Проверяет группы, у которых время рассылки совпадает с текущим, и отправляет расписание"""
        if not self.bot or not self.group_chat_repo or not self.schedule_repo:
            return
            
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        
        try:
            chats = await self.group_chat_repo.get_chats_for_time(current_time_str)
        except Exception as e:
            logging.error(f"Error fetching group chats for time {current_time_str}: {e}")
            return
            
        if not chats:
            return
            
        logging.info(f"📢 Авторассылка: найдено {len(chats)} чат(ов) на {current_time_str}")
        from tgbot.services.services import ScheduleService
        service = ScheduleService()
        
        for chat in chats:
            try:
                target_date = now.date()
                if chat.post_target == "tomorrow" or (chat.post_time >= "19:00" and chat.post_target != "today"):
                    from datetime import timedelta
                    target_date += timedelta(days=1)
                
                lessons, is_predicted = await self.schedule_repo.get_lessons_with_status(chat.group_name, target_date)
                
                # Если воскресенье и занятий нет — пропускаем, чтобы не спамить в чат
                if target_date.weekday() == 6 and not lessons:
                    logging.info(f"⏩ Пропуск рассылки в {chat.chat_id}: воскресенье, пар нет.")
                    continue
                    
                formatted_day = service.format_day(
                    lessons, 
                    target_date, 
                    chat.group_name, 
                    is_predicted=is_predicted
                )
                
                target_word = "завтра" if target_date > now.date() else "сегодня"
                msg_text = (
                    f"🔔 <b>Расписание на {target_word}</b>\n\n"
                    f"{formatted_day}"
                )
                
                sent_msg = await self.bot.send_message(
                    chat_id=chat.chat_id,
                    message_thread_id=chat.topic_id,
                    text=msg_text
                )
                
                if chat.pin_message:
                    try:
                        await self.bot.pin_chat_message(
                            chat_id=chat.chat_id,
                            message_id=sent_msg.message_id,
                            disable_notification=True
                        )
                    except Exception as pin_err:
                        logging.debug(f"Не удалось закрепить сообщение в {chat.chat_id}: {pin_err}")
                        
            except Exception as e:
                err_str = str(e).lower()
                if "forbidden" in err_str or "chat not found" in err_str or "kicked" in err_str or "deactivated" in err_str:
                    logging.warning(f"🚫 Бот недоступен в чате {chat.chat_id}. Отключаем авторассылку.")
                    chat.auto_post = False
                    await self.group_chat_repo.upsert_chat(chat)
                else:
                    logging.error(f"❌ Ошибка отправки расписания в чат {chat.chat_id}: {e}")

    async def run_user_daily_broadcast(self):
        """Ежеминутная проверка личной ежедневной рассылки расписания в ЛС бота"""
        if not self.bot or not self.user_repo or not self.schedule_repo:
            return

        now = datetime.now()
        current_time_str = now.strftime("%H:%M")

        try:
            users = await self.user_repo.get_all_users_with_group()
        except Exception as e:
            logging.error(f"Error fetching users for daily broadcast: {e}")
            return

        matching_users = [
            u for u in users 
            if u.settings.notify_daily and getattr(u.settings, 'notify_daily_time', '07:30') == current_time_str
        ]

        if not matching_users:
            return

        logging.info(f"📬 Личная рассылка: найдено {len(matching_users)} пользователей на {current_time_str}")
        from tgbot.services.services import ScheduleService
        service = ScheduleService()
        target_date = now.date()

        for user in matching_users:
            try:
                lessons, is_predicted = await self.schedule_repo.get_lessons_with_status(user.group_name, target_date)
                
                # Если воскресенье и занятий нет — не беспокоим
                if target_date.weekday() == 6 and not lessons:
                    continue

                formatted_day = service.format_day(
                    lessons, 
                    target_date, 
                    user.group_name, 
                    settings=user.settings,
                    is_predicted=is_predicted
                )

                msg_text = (
                    f"🔔 <b>Ваше расписание на сегодня</b>\n\n"
                    f"{formatted_day}"
                )

                await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=msg_text
                )
            except Exception as e:
                err_str = str(e).lower()
                if "forbidden" in err_str or "blocked" in err_str or "deactivated" in err_str:
                    logging.warning(f"🚫 Пользователь {user.telegram_id} заблокировал бота. Отключаем личные уведомления.")
                    user.settings.notify_daily = False
                    user.settings.notify_before_lesson = False
                    await self.user_repo.upsert_user(user)
                else:
                    logging.error(f"❌ Ошибка отправки расписания пользователю {user.telegram_id}: {e}")

    async def run_lesson_start_alerts(self):
        """Ежеминутная проверка скорого начала пар для отправки напоминаний в ЛС"""
        if not self.bot or not self.user_repo or not self.schedule_repo:
            return

        from tgbot.config import config
        from tgbot.services.services import ScheduleService
        from datetime import timedelta

        now = datetime.now()
        today = now.date()
        today_str = today.isoformat()

        # Очищаем устаревший кэш за прошлые дни
        self._sent_lesson_alerts = {item for item in self._sent_lesson_alerts if item[0] == today_str}

        try:
            users = await self.user_repo.get_all_users_with_group()
        except Exception as e:
            logging.error(f"Error fetching users for lesson start alerts: {e}")
            return

        alert_users = [u for u in users if u.settings.notify_before_lesson]
        if not alert_users:
            return

        service = ScheduleService()

        # Группируем пользователей по группам, чтобы минимизировать запросы к БД расписания
        from collections import defaultdict
        group_to_users = defaultdict(list)
        for u in alert_users:
            group_to_users[u.group_name].append(u)

        for grp_name, u_list in group_to_users.items():
            try:
                lessons, _ = await self.schedule_repo.get_lessons_with_status(grp_name, today)
                if not lessons:
                    continue

                for lesson in lessons:
                    p_num = lesson.pair_number
                    start_str = lesson.start_time
                    if not start_str and p_num in config.STANDARD_PAIR_STARTS:
                        start_str = config.STANDARD_PAIR_STARTS[p_num]

                    if not start_str or ":" not in start_str:
                        continue

                    try:
                        sh, sm = map(int, start_str.split(":")[:2])
                        lesson_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                    except ValueError:
                        continue

                    diff_minutes = int((lesson_dt - now).total_seconds() / 60)

                    for user in u_list:
                        target_lead = getattr(user.settings, 'notify_before_minutes', 15)
                        # Проверяем попадание в окно оповещения (например ровно за 15 минут)
                        if 0 <= diff_minutes <= target_lead:
                            alert_key = (today_str, user.telegram_id, p_num or lesson.subject)
                            if alert_key in self._sent_lesson_alerts:
                                continue

                            # Формируем и шлем алерт
                            alert_text = service.format_lesson_notification(lesson, minutes_left=diff_minutes)
                            try:
                                await self.bot.send_message(
                                    chat_id=user.telegram_id,
                                    text=alert_text
                                )
                                self._sent_lesson_alerts.add(alert_key)
                            except Exception as e:
                                err_str = str(e).lower()
                                if "forbidden" in err_str or "blocked" in err_str:
                                    user.settings.notify_before_lesson = False
                                    await self.user_repo.upsert_user(user)
                                else:
                                    logging.error(f"❌ Ошибка отправки алерта о паре {user.telegram_id}: {e}")
            except Exception as e:
                logging.error(f"Error checking lesson alerts for group {grp_name}: {e}")

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
        
        # Синхронизация занятости аудиторий (каждые 4 часа)
        self.scheduler.add_job(
            self.run_occupancy_sync,
            "interval",
            hours=4,
            id="occupancy_sync_job"
        )

        # Авторассылка расписания в Telegram-группы (каждую минуту)
        if self.group_chat_repo and self.bot:
            self.scheduler.add_job(
                self.run_group_chat_broadcast,
                "cron",
                minute="*",
                id="group_chat_broadcast_job"
            )

        # Личная рассылка и напоминания о парах в ЛС (каждую минуту)
        if self.user_repo and self.bot:
            self.scheduler.add_job(
                self.run_user_daily_broadcast,
                "cron",
                minute="*",
                id="user_daily_broadcast_job"
            )
            self.scheduler.add_job(
                self.run_lesson_start_alerts,
                "cron",
                minute="*",
                id="user_lesson_alerts_job"
            )
        
        self.scheduler.start()
        logging.info(f"⚙️ Планировщик парсера запущен")
        logging.info(f"   📅 Job 1: Парсинг расписания - каждый день в 6:50 AM")
        logging.info(f"   📡 Job 2: Синхронизация с веб-сайтом - каждый день в 5:00 AM")
        logging.info(f"   🏢 Job 3: Синхронизация занятости - каждые 4 часа")
        logging.info(f"   🧹 Job 4: Плановое обслуживание - каждое воскресенье в 4:00 AM")
        if self.group_chat_repo and self.bot:
            logging.info(f"   📢 Job 5: Авторассылка в группы - каждую минуту")
        if self.user_repo and self.bot:
            logging.info(f"   🔔 Job 6: Личные уведомления и алерты в ЛС - каждую минуту")
        
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