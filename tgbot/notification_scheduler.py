"""
Bot-side notification scheduler (replaces tgbot/services/parser_scheduler.py).

Owns only Telegram-facing recurring jobs:
  - personal daily digest (run_user_daily_broadcast)
  - group-chat broadcast (run_group_chat_broadcast)
  - lesson-start alerts (run_lesson_start_alerts)

All are triggered every minute (APScheduler cron). Timezone-aware:
AsyncIOScheduler(timezone=config.tz) and datetime.now(config.tz) — this fixes
the digest-arriving-at-~00:00 bug caused by comparing naive server-local time
with the user's configured notify_daily_time.

Parser control (run_parser_process / run_now / get_status / sync_* / logs)
is proxied over HTTP to the TimeSync server via the same repository gateway
objects — admin handlers keep using these exact names on `parser_scheduler`.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.config import config
from tgbot.database.repositories import ParserSchedulerService  # gateway + parser control proxy
from tgbot.services.services import ScheduleService

logger = logging.getLogger("timesync.bot.notifications")


class NotificationSchedulerService(ParserSchedulerService):
    """Extends the parser-control proxy with the Telegram notification jobs."""

    def __init__(
        self,
        db_manager=None,
        schedule_repo=None,
        analytics_repo=None,
        group_chat_repo=None,
        user_repo=None,
        bot=None,
        run_on_startup: bool = False,
    ):
        super().__init__(
            db_manager=db_manager,
            schedule_repo=schedule_repo,
            analytics_repo=analytics_repo,
            group_chat_repo=group_chat_repo,
            user_repo=user_repo,
            bot=bot,
            run_on_startup=run_on_startup,
        )
        self.scheduler = AsyncIOScheduler(timezone=config.tz)
        self._sent_digests: set = set()  # (date_str, telegram_id) per-day dedupe

    # ---------- group chat broadcast ----------  (same logic as before, tz-aware)
    async def run_group_chat_broadcast(self):
        if not self.bot or not self.group_chat_repo or not self.schedule_repo:
            return

        now = datetime.now(config.tz)
        current_time_str = now.strftime("%H:%M")

        try:
            chats = await self.group_chat_repo.get_chats_for_time(current_time_str)
        except Exception as e:
            logger.error(f"Error fetching group chats for time {current_time_str}: {e}")
            return

        if not chats:
            return

        logger.info(f"📢 Авторассылка: найдено {len(chats)} чат(ов) на {current_time_str}")
        service = ScheduleService()

        for chat in chats:
            try:
                target_date = now.date()
                if chat.post_target == "tomorrow" or (
                    chat.post_time >= "19:00" and chat.post_target != "today"
                ):
                    target_date += timedelta(days=1)

                lessons, is_predicted = await self.schedule_repo.get_lessons_with_status(
                    chat.group_name, target_date
                )
                if target_date.weekday() == 6 and not lessons:
                    logger.info(f"⏩ Пропуск рассылки в {chat.chat_id}: воскресенье, пар нет.")
                    continue

                formatted_day = service.format_day(lessons, target_date, chat.group_name, is_predicted=is_predicted)
                target_word = "завтра" if target_date > now.date() else "сегодня"
                msg_text = f"🔔 <b>Расписание на {target_word}</b>\n\n{formatted_day}"

                sent_msg = await self.bot.send_message(
                    chat_id=chat.chat_id,
                    message_thread_id=chat.topic_id,
                    text=msg_text,
                )
                if chat.pin_message:
                    try:
                        await self.bot.pin_chat_message(
                            chat_id=chat.chat_id,
                            message_id=sent_msg.message_id,
                            disable_notification=True,
                        )
                    except Exception as pin_err:
                        logger.debug(f"Не удалось закрепить сообщение в {chat.chat_id}: {pin_err}")
            except Exception as e:
                err_str = str(e).lower()
                if any(s in err_str for s in ("forbidden", "chat not found", "kicked", "deactivated")):
                    logger.warning(f"🚫 Бот недоступен в чате {chat.chat_id}. Отключаем авторассылку.")
                    chat.auto_post = False
                    await self.group_chat_repo.upsert_chat(chat)
                else:
                    logger.error(f"❌ Ошибка отправки расписания в чат {chat.chat_id}: {e}")

    # ---------- personal daily digest ----------  (tz-aware + catch-up + dedupe)
    async def run_user_daily_broadcast(self):
        if not self.bot or not self.user_repo or not self.schedule_repo:
            return

        now = datetime.now(config.tz)
        current_time_str = now.strftime("%H:%M")
        today_str = now.date().isoformat()

        try:
            users = await self.user_repo.get_all_users_with_group()
        except Exception as e:
            logger.error(f"Error fetching users for daily broadcast: {e}")
            return

        # Clean old-day digests keys (keep today's ones)
        self._sent_digests = {(d, uid) for d, uid in self._sent_digests if d == today_str}

        matching_users = []
        for u in users:
            if not u.settings.notify_daily:
                continue
            target = getattr(u.settings, "notify_daily_time", "07:30")
            # exact match OR within one minute after target (catch-up for a skipped tick)
            if target == current_time_str:
                matching_users.append(u)
            else:
                try:
                    th, tm = map(int, target.split(":"))
                    target_dt = now.replace(hour=th, minute=tm, second=0, microsecond=0)
                    if timedelta(0) <= now - target_dt <= timedelta(minutes=1) and (today_str, u.telegram_id) not in self._sent_digests:
                        matching_users.append(u)
                except ValueError:
                    continue

        if not matching_users:
            return

        logger.info(f"📬 Личная рассылка: найдено {len(matching_users)} пользователей на {current_time_str}")
        service = ScheduleService()

        for user in matching_users:
            try:
                key = (today_str, user.telegram_id)
                if key in self._sent_digests:
                    continue
                self._sent_digests.add(key)

                lessons, is_predicted = await self.schedule_repo.get_lessons_with_status(
                    user.group_name, now.date()
                )
                if now.date().weekday() == 6 and not lessons:
                    continue

                formatted_day = service.format_day(
                    lessons, now.date(), user.group_name, settings=user.settings, is_predicted=is_predicted
                )
                msg_text = f"🔔 <b>Ваше расписание на сегодня</b>\n\n{formatted_day}"
                await self.bot.send_message(chat_id=user.telegram_id, text=msg_text)
            except Exception as e:
                err_str = str(e).lower()
                if any(s in err_str for s in ("forbidden", "blocked", "deactivated")):
                    logger.warning(f"🚫 Пользователь {user.telegram_id} заблокировал бота.")
                    user.settings.notify_daily = False
                    user.settings.notify_before_lesson = False
                    await self.user_repo.upsert_user(user)
                else:
                    logger.error(f"❌ Ошибка отправки расписания пользователю {user.telegram_id}: {e}")

    # ---------- lesson start alerts ----------  (tz-aware)
    async def run_lesson_start_alerts(self):
        if not self.bot or not self.user_repo or not self.schedule_repo:
            return

        now = datetime.now(config.tz)
        today = now.date()
        today_str = today.isoformat()

        self._sent_lesson_alerts = {item for item in self._sent_lesson_alerts if item[0] == today_str}

        try:
            users = await self.user_repo.get_all_users_with_group()
        except Exception as e:
            logger.error(f"Error fetching users for lesson start alerts: {e}")
            return

        alert_users = [u for u in users if u.settings.notify_before_lesson]
        if not alert_users:
            return

        service = ScheduleService()
        group_to_users = defaultdict(list)
        for u in alert_users:
            group_to_users[u.group_name].append(u)

        from tgbot.config import config as bot_config

        for grp_name, u_list in group_to_users.items():
            try:
                lessons, _ = await self.schedule_repo.get_lessons_with_status(grp_name, today)
                if not lessons:
                    continue
                for lesson in lessons:
                    p_num = lesson.pair_number
                    start_str = lesson.start_time
                    if not start_str and p_num in bot_config.STANDARD_PAIR_STARTS:
                        start_str = bot_config.STANDARD_PAIR_STARTS[p_num]
                    if not start_str or ":" not in start_str:
                        continue
                    try:
                        sh, sm = map(int, start_str.split(":")[:2])
                        lesson_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                    except ValueError:
                        continue

                    diff_minutes = int((lesson_dt - now).total_seconds() / 60)

                    for user in u_list:
                        target_lead = getattr(user.settings, "notify_before_minutes", 15)
                        if 0 <= diff_minutes <= target_lead:
                            alert_key = (today_str, user.telegram_id, p_num or lesson.subject)
                            if alert_key in self._sent_lesson_alerts:
                                continue
                            alert_text = service.format_lesson_notification(lesson, minutes_left=diff_minutes)
                            try:
                                await self.bot.send_message(chat_id=user.telegram_id, text=alert_text)
                                self._sent_lesson_alerts.add(alert_key)
                            except Exception as e:
                                err_str = str(e).lower()
                                if any(s in err_str for s in ("forbidden", "blocked")):
                                    user.settings.notify_before_lesson = False
                                    await self.user_repo.upsert_user(user)
                                else:
                                    logger.error(f"❌ Ошибка отправки алерта о паре {user.telegram_id}: {e}")
            except Exception as e:
                logger.error(f"Error checking lesson alerts for group {grp_name}: {e}")

    def start(self, interval_hours: int = 12):
        if self.group_chat_repo and self.bot:
            self.scheduler.add_job(self.run_group_chat_broadcast, "cron", minute="*", id="group_chat_broadcast_job")
        if self.user_repo and self.bot:
            self.scheduler.add_job(self.run_user_daily_broadcast, "cron", minute="*", id="user_daily_broadcast_job")
            self.scheduler.add_job(self.run_lesson_start_alerts, "cron", minute="*", id="user_lesson_alerts_job")
        self.scheduler.start()
        logger.info("⚙️ Уведомительный планировщик бота запущен (TZ=%s)", config.TIMEZONE)

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("⏹️ Уведомительный планировщик бота остановлен.")
