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
            lines.append(f"▫️ <b>{p} пара</b>: <code>{config.STANDARD_PAIRS.get(p, '??:?? - ??:??')}</code>")

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
            header += "\n🔮 <i>Предполагаемое расписание (не официальное!)</i>"

        if not lessons:
            return f"{header}\n\n🎉 Пар нет!"

        # 1. Дедупликация уроков в памяти
        unique_lessons = []
        seen = set()
        for l in lessons:
            key = (
                l.pair_number,
                l.start_time,
                l.end_time,
                (l.subject or "").strip().lower(),
                (l.class_type or "").strip().lower(),
                (l.teacher or "").strip().lower(),
                (l.building or "").strip().lower(),
                (l.room or "").strip().lower(),
                (l.subgroup or "").strip()
            )
            if key not in seen:
                seen.add(key)
                unique_lessons.append(l)

        # 2. Группировка уроков по номеру пары
        pairs_dict: Dict[int, List[Lesson]] = {}
        no_pair_lessons: List[Lesson] = []
        for l in unique_lessons:
            p_num = l.pair_number
            if not p_num and l.start_time in config.TIME_SLOTS:
                p_num = config.TIME_SLOTS[l.start_time]
            if p_num:
                pairs_dict.setdefault(p_num, []).append(l)
            else:
                no_pair_lessons.append(l)

        lines = [header]
        prev_pair = None

        for p_num in sorted(pairs_dict.keys()):
            pair_lessons = pairs_dict[p_num]
            pair_lessons.sort(key=lambda x: (x.subgroup or "", x.teacher or ""))

            if settings.show_windows and prev_pair is not None:
                if p_num > prev_pair + 1:
                    window_pairs = p_num - prev_pair - 1
                    lines.append(
                        f"\n⏸️ <i>Окно ({window_pairs} {'пара' if window_pairs == 1 else 'пары'})</i>"
                    )
            prev_pair = p_num

            first_l = pair_lessons[0]
            start = first_l.start_time
            end = first_l.end_time
            if (not start or not end) and p_num in config.STANDARD_PAIRS:
                std_parts = config.STANDARD_PAIRS[p_num].split(" - ")
                start = start or std_parts[0]
                end = end or std_parts[1]
            start = start or "??"
            end = end or "??"

            icon = "⚪️"
            all_types = " ".join((l.class_type or "").lower() for l in pair_lessons)
            if "лек" in all_types:
                icon = "🔴"
            elif "прак" in all_types or "пр." in all_types:
                icon = "🟢"
            elif "лаб" in all_types:
                icon = "🔵"
            elif "зачет" in all_types or "экзамен" in all_types:
                icon = "⚠️"

            lines.append(f"\n<b>{p_num} {icon} {start} - {end}</b>")

            first_sub = (first_l.subject or "").strip().lower()
            first_tch = (first_l.teacher or "").strip().lower()
            first_bld = (first_l.building or "").strip().lower()
            first_rm = (first_l.room or "").strip().lower()
            all_identical = all(
                (l.subject or "").strip().lower() == first_sub and
                (l.teacher or "").strip().lower() == first_tch and
                (l.building or "").strip().lower() == first_bld and
                (l.room or "").strip().lower() == first_rm
                for l in pair_lessons
            )

            if all_identical:
                # Все подгруппы занимаются вместе у одного преподавателя в одной аудитории
                subject = first_l.subject if first_l.subject else "Предмет не указан"
                class_type_str = f"{first_l.class_type}" if first_l.class_type else ""
                lines.append(f"<b>{subject}</b>\n{class_type_str}")

                meta = []
                if settings.show_teachers and first_l.teacher:
                    meta.append(f"👤 {first_l.teacher}")
                if settings.show_building and (first_l.building or first_l.room):
                    b_str = first_l.building if first_l.building else ""
                    r_str = first_l.room if first_l.room else ""
                    meta.append(f"📍 {b_str}-{r_str}")
                if meta:
                    lines.append(" | ".join(meta))
            else:
                # Разделение на подгруппы (разные преподаватели/аудитории/предметы)
                same_subject = all(
                    (l.subject or "").strip().lower() == first_sub
                    for l in pair_lessons
                )
                if same_subject and first_l.subject:
                    c_type_str = f"\n{first_l.class_type}" if first_l.class_type else ""
                    lines.append(f"<b>{first_l.subject}</b>{c_type_str}")

                for l in pair_lessons:
                    sg_raw = l.subgroup.lstrip("0") if l.subgroup else ""
                    sg_prefix = f"👥 {sg_raw} п/г: " if sg_raw else ""

                    item_parts = []
                    if not same_subject and l.subject:
                        c_str = f" ({l.class_type})" if l.class_type else ""
                        item_parts.append(f"<b>{l.subject}</b>{c_str}")

                    if settings.show_teachers and l.teacher:
                        item_parts.append(f"👤 {l.teacher}")
                    if settings.show_building and (l.building or l.room):
                        b_str = l.building if l.building else ""
                        r_str = l.room if l.room else ""
                        item_parts.append(f"📍 {b_str}-{r_str}")

                    if item_parts:
                        lines.append(f"{sg_prefix}{' | '.join(item_parts)}")
                    elif l.raw_info:
                        lines.append(f"{sg_prefix}❓ <i>{l.raw_info.strip()}</i>")

        for l in no_pair_lessons:
            if l.raw_info:
                lines.append(f"\n❓ <i>{l.raw_info.strip()}</i>")

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

    async def get_available_pairs(self, target_date: date, building: str) -> List[int]:
        return await self.occupancy_repo.get_available_pairs(target_date, building)
