from datetime import date
from typing import List, Optional, Set, Union
from aiogram import Bot
from tgbot.database.models import Lesson, UserSettings
from tgbot.database.repositories import UserRepository, OccupancyRepository
from tgbot.services.utils import safe_broadcast
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from aiogram.types import Message, CallbackQuery, TelegramObject
from tgbot.config import config
from tgbot.database.repositories import ScheduleRepository
class ScheduleService:
    async def find_common_free_slots(
        self,
        schedule_repo: ScheduleRepository,
        group_names: List[str],
        target_date: date
    ) -> str:
        """
        Определяет общие свободные промежутки (пары) для переданного списка групп.
        """
        # Эталонное время пар ВятГУ
        STANDARD_PAIRS = {
            1: "08:20 - 09:50",
            2: "10:00 - 11:30",
            3: "11:45 - 13:15",
            4: "14:00 - 15:30",
            5: "15:45 - 17:15",
            6: "17:20 - 18:50",
            7: "18:55 - 20:25"
        }

        # 1. Получаем все пары для выбранных групп на эту дату
        lessons = await schedule_repo.get_lessons_for_groups(group_names, target_date)

        # 2. Собираем множество (set) ВСЕХ занятых пар для этих групп
        # Если хотя бы у одной группы есть пара N, эта пара попадает в множество
        occupied_pairs = {lesson.pair_number for lesson in lessons if lesson.pair_number}

        # 3. Вычисляем свободные пары (Все возможные пары (1-7) минус занятые)
        all_pairs = set(range(1, 8))
        free_pairs = all_pairs - occupied_pairs

        # 4. Формируем красивый текстовый ответ
        groups_str = ", ".join(group_names)
        date_str = target_date.strftime('%d.%m.%Y')

        if not free_pairs:
            return (
                f"📅 <b>{date_str}</b>\n"
                f"👥 Группы: <b>{groups_str}</b>\n\n"
                f"❌ <b>Общих свободных пар нет.</b> В любое время у кого-то есть занятия."
            )

        lines = [
            f"📅 <b>{date_str}</b>", 
            f"👥 Группы: <b>{groups_str}</b>\n", 
            "✅ <b>Общие свободные окна:</b>\n"
        ]

        # Сортируем пары по порядку (1, 2, 3...)
        for p in sorted(free_pairs):
            lines.append(f"▫️ <b>{p} пара</b>: <code>{STANDARD_PAIRS[p]}</code>")

        return "\n".join(lines)
    def format_day(
        self,
        lessons: List[Lesson],
        date_obj: date,
        group_name: str,
        settings: Optional[UserSettings] = None,
        is_predicted: bool = False
    ) -> str:
        if settings is None:
            settings = UserSettings()

        header = f"📅 <b>{date_obj.strftime('%d.%m.%Y')}</b> ({group_name})"
        if is_predicted:
            header += "\n🔮 <i>Предполагаемое расписание (на основе прошлых недель)</i>"

        if not lessons:
            return f"{header}\n\n🎉 Пар нет!"

        lines = [header]
        prev_pair = None

        for l in lessons:
            if settings.show_windows and prev_pair is not None and l.pair_number:
                if l.pair_number > prev_pair + 1:
                    window_pairs = l.pair_number - prev_pair - 1
                    lines.append(
                        f"\n⏸️ <i>Окно ({window_pairs} {'пара' if window_pairs == 1 else 'пары'})</i>"
                    )

            if l.pair_number:
                prev_pair = l.pair_number

            icon = "⚪️"
            if l.class_type:
                ctype_lower = l.class_type.lower()
                if "лек" in ctype_lower:
                    icon = "🔴"
                elif "прак" in ctype_lower or "пр." in ctype_lower:
                    icon = "🟢"
                elif "лаб" in ctype_lower:
                    icon = "🔵"
                elif "зачет" in ctype_lower or "экзамен" in ctype_lower:
                    icon = "⚠️"

            start = l.start_time or "??"
            end = l.end_time or "??"
            pair_num = l.pair_number if l.pair_number else "?"

            # --- ИЗМЕНЕН ФОРМАТ ВРЕМЕНИ И ПАРЫ ---
            lines.append(f"\n<b>{pair_num} {icon} {start} - {end}</b>")

            if not l.subject and not l.teacher and not l.room and l.raw_info:
                lines.append(f"❓ <i>{l.raw_info.strip()}</i>")
                continue

            subject = l.subject if l.subject else "Предмет не указан"
            class_type_str = f"{l.class_type}" if l.class_type else ""
            lines.append(f"<b>{subject}</b>\n{class_type_str}")

            meta = []
            if settings.show_teachers and l.teacher:
                meta.append(f"👤 {l.teacher}")
            if settings.show_building and (l.building or l.room):
                building_str = l.building if l.building else ""
                room_str = l.room if l.room else ""
                meta.append(f"📍 {building_str}-{room_str}")
            if meta:
                lines.append(" | ".join(meta))
        return "\n".join(lines)


class CuratorService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def try_activate_code(self, user_id: int, code: str) -> Union[str, bool]:
        group_name = await self.user_repo.activate_curator_code(code)
        if not group_name:
            return False
        user = await self.user_repo.get_user(user_id)
        if user:
            user.role = "curator"
            user.curator_group = group_name
            await self.user_repo.upsert_user(user)
            return group_name
        return False

    async def broadcast_to_group(
        self, bot: Bot, group_name: str, message_text: str
    ) -> int:
        students = await self.user_repo.get_users_by_group(group_name)
        student_ids = [s.telegram_id for s in students]
        if not student_ids:
            return 0
        formatted_text = f"📢 <b>Сообщение от куратора:</b>\n\n{message_text}"
        return await safe_broadcast(bot, student_ids, formatted_text)


class OccupancyService:
    def __init__(self, occupancy_repo: OccupancyRepository):
        self.occupancy_repo = occupancy_repo

    async def find_free_rooms(
        self, target_date: date, pair_number: int, building: Optional[str] = None
    ) -> Set[str]:
        all_rooms = await self.occupancy_repo.get_all_rooms(building)
        occupied = await self.occupancy_repo.get_occupied_rooms(
            target_date, pair_number, building
        )
        return all_rooms - occupied
