from __future__ import annotations
import re
from datetime import date, timedelta
from html import escape
from typing import Any, Callable, Dict, Awaitable, List, Optional, Set, Tuple, Union
from aiogram import Bot
from core.models import Lesson, UserSettings
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from core.config import config
RE_TEACHER_TRAILING = re.compile(
    r'\s+([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.(?:\s?[А-ЯЁ]\.)?)\s*"?$'
)


def clean_lesson_meta(lesson: Lesson) -> Tuple[str, Optional[str]]:
    """Очищает предмет и извлекает преподавателя, если он приклеился к названию предмета."""
    subj = (lesson.subject or "").strip().rstrip('"').rstrip()
    teacher = lesson.teacher
    if not teacher and subj:
        m = RE_TEACHER_TRAILING.search(subj)
        if m:
            teacher = m.group(1).strip()
            subj = subj[:m.start()].strip().rstrip('"').rstrip()
    return subj, teacher


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

    def format_lesson_notification(self, lesson: Lesson, minutes_left: int = 15) -> str:
        """Форматирует компактное уведомление о скором начале пары."""
        pair_num = lesson.pair_number or "?"
        time_str = f"{lesson.start_time}-{lesson.end_time}" if lesson.start_time and lesson.end_time else (lesson.start_time or "??:??")
        clean_subj, clean_t = clean_lesson_meta(lesson)
        subj = clean_subj or "Занятие"
        c_type = f" ({lesson.class_type})" if lesson.class_type else ""
        
        parts = [f"⏰ <b>Через {minutes_left} минут начнётся {pair_num} пара!</b>\n"]
        parts.append(f"📚 <b>{subj}</b>{c_type}")
        parts.append(f"🕒 Время: <code>{time_str}</code>")
        
        if lesson.building or lesson.room:
            b_str = lesson.building or ""
            r_str = lesson.room or ""
            loc = f"{b_str}-{r_str}" if b_str and r_str else (b_str or r_str)
            parts.append(f"📍 Аудитория: <b>{loc}</b>")
            
        if clean_t:
            parts.append(f"👤 Преподаватель: <i>{clean_t}</i>")
            
        if lesson.subgroup:
            parts.append(f"👥 Подгруппа: <i>{lesson.subgroup}</i>")
            
        return "\n".join(parts)

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
            clean_s, clean_t = clean_lesson_meta(l)
            key = (
                l.pair_number,
                l.start_time,
                l.end_time,
                clean_s.lower(),
                (l.class_type or "").strip().lower(),
                (clean_t or "").strip().lower(),
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

            # Группируем уроки внутри пары по нормализованному названию предмета
            lessons_by_subj: Dict[str, List[Tuple[Lesson, str, Optional[str]]]] = {}
            for l in pair_lessons:
                clean_s, clean_t = clean_lesson_meta(l)
                lessons_by_subj.setdefault(clean_s, []).append((l, clean_s, clean_t))

            # Если внутри одной пары несколько РАЗНЫХ предметов -> это элективные дисциплины (траектории)
            if len(lessons_by_subj) > 1:
                lines.append(f"\n<b>{p_num} {icon} {start} - {end}</b> • 🔀 <i>Дисциплины по выбору:</i>")
                for clean_s, sub_list in lessons_by_subj.items():
                    if len(sub_list) == 1:
                        l, _, clean_t = sub_list[0]
                        c_str = f" ({l.class_type})" if l.class_type else ""
                        meta = []
                        if l.subgroup:
                            meta.append(f"👥 {l.subgroup.lstrip('0')} п/г")
                        if settings.show_teachers and clean_t:
                            meta.append(f"👤 {clean_t}")
                        if settings.show_building and (l.building or l.room):
                            b_str = l.building or ""
                            r_str = l.room or ""
                            loc = f"{b_str}-{r_str}" if b_str and r_str else (b_str or r_str)
                            meta.append(f"📍 {loc}")
                        meta_str = (" | " + " | ".join(meta)) if meta else ""
                        lines.append(f"▫️ <b>{clean_s}</b>{c_str}{meta_str}")
                    else:
                        first_track_l, _, _ = sub_list[0]
                        c_str = f" ({first_track_l.class_type})" if first_track_l.class_type else ""
                        lines.append(f"▫️ <b>{clean_s}</b>{c_str}")
                        for l, _, clean_t in sub_list:
                            meta = []
                            if l.subgroup:
                                meta.append(f"👥 {l.subgroup.lstrip('0')} п/г")
                            if settings.show_teachers and clean_t:
                                meta.append(f"👤 {clean_t}")
                            if settings.show_building and (l.building or l.room):
                                b_str = l.building or ""
                                r_str = l.room or ""
                                loc = f"{b_str}-{r_str}" if b_str and r_str else (b_str or r_str)
                                meta.append(f"📍 {loc}")
                            if meta:
                                lines.append(f"   • {' | '.join(meta)}")
            else:
                # Один предмет в паре (стандартное занятие или разделение на подгруппы)
                sub_list = list(lessons_by_subj.values())[0]
                first_l, clean_s, clean_t = sub_list[0]
                lines.append(f"\n<b>{p_num} {icon} {start} - {end}</b>")
                
                # Проверяем, идентичны ли все записи (один преподаватель, одна аудитория)
                first_bld = (first_l.building or "").strip().lower()
                first_rm = (first_l.room or "").strip().lower()
                first_tch_norm = (clean_t or "").strip().lower()
                all_identical = all(
                    (clean_item_t or "").strip().lower() == first_tch_norm and
                    (l.building or "").strip().lower() == first_bld and
                    (l.room or "").strip().lower() == first_rm
                    for l, _, clean_item_t in sub_list
                )

                if all_identical:
                    class_type_str = f"{first_l.class_type}" if first_l.class_type else ""
                    lines.append(f"<b>{clean_s}</b>\n{class_type_str}")

                    meta = []
                    if settings.show_teachers and clean_t:
                        meta.append(f"👤 {clean_t}")
                    if settings.show_building and (first_l.building or first_l.room):
                        b_str = first_l.building or ""
                        r_str = first_l.room or ""
                        loc = f"{b_str}-{r_str}" if b_str and r_str else (b_str or r_str)
                        meta.append(f"📍 {loc}")
                    if meta:
                        lines.append(" | ".join(meta))
                else:
                    # Разделение на подгруппы (разные преподаватели или аудитории)
                    c_type_str = f"\n{first_l.class_type}" if first_l.class_type else ""
                    lines.append(f"<b>{clean_s}</b>{c_type_str}")

                    for l, _, clean_item_t in sub_list:
                        sg_raw = l.subgroup.lstrip("0") if l.subgroup else ""
                        sg_prefix = f"👥 {sg_raw} п/г: " if sg_raw else ""

                        item_parts = []
                        if settings.show_teachers and clean_item_t:
                            item_parts.append(f"👤 {clean_item_t}")
                        if settings.show_building and (l.building or l.room):
                            b_str = l.building or ""
                            r_str = l.room or ""
                            loc = f"{b_str}-{r_str}" if b_str and r_str else (b_str or r_str)
                            item_parts.append(f"📍 {loc}")

                        if item_parts:
                            lines.append(f"{sg_prefix}{' | '.join(item_parts)}")
                        elif l.raw_info:
                            lines.append(f"{sg_prefix}❓ <i>{l.raw_info.strip()}</i>")

        for l in no_pair_lessons:
            if l.raw_info:
                lines.append(f"\n❓ <i>{l.raw_info.strip()}</i>")

        return "\n".join(lines)

    @staticmethod
    def format_locations(lessons: List[Lesson]) -> Optional[str]:
        """Формирует компактный текст со списком корпусов и аудиторий для CopyTextButton."""
        from collections import defaultdict
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for l in lessons:
            bld = (l.building or "").strip()
            rm = (l.room or "").strip()
            if rm:
                b_key = f"Корпус {bld}" if bld else "Корпус ?"
                if rm not in grouped[b_key]:
                    grouped[b_key].append(rm)

        if not grouped:
            return None

        parts = [f"{bld}: ауд. {', '.join(rooms)}" for bld, rooms in grouped.items()]
        return "\n".join(parts)


WEEKDAY_NAMES = (
    "Понедельник", "Вторник", "Среда",
    "Четверг", "Пятница", "Суббота", "Воскресенье",
)

TELEGRAM_TEXT_LIMIT = 4096


def _unpack_week_day(raw: Any, fallback_date: date) -> Tuple[date, List[Lesson], bool]:
    """Приводит элемент week_days к виду (дата, пары, прогноз)."""
    if isinstance(raw, dict):
        day_date = raw.get("date") or raw.get("day_date") or fallback_date
        return day_date, list(raw.get("lessons") or []), bool(raw.get("is_predicted"))

    if isinstance(raw, (tuple, list)) and raw and isinstance(raw[0], date):
        is_predicted = bool(raw[2]) if len(raw) > 2 else False
        return raw[0], list(raw[1] or []), is_predicted

    return fallback_date, list(raw or []), False


def format_week_schedule_expandable(
    week_days: list,
    group_name: str,
    start_date: date,
    end_date: date,
) -> str:
    """Недельное расписание: занятия каждого дня обёрнуты в <blockquote expandable>."""
    title = (
        f"📆 <b>Расписание на неделю "
        f"({start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')})</b>\n"
        f"👥 Группа: <b>{escape(group_name)}</b>"
    )

    service = ScheduleService()
    today = date.today()
    blocks: List[str] = []
    lessons_count = 0

    for offset, raw in enumerate(week_days):
        day_date, lessons, is_predicted = _unpack_week_day(
            raw, start_date + timedelta(days=offset)
        )

        header = f"📅 <b>{WEEKDAY_NAMES[day_date.weekday()]} ({day_date.strftime('%d.%m')})"
        if day_date == today:
            header += " — сегодня"
        header += "</b>"

        if not lessons:
            blocks.append(f"{header}\n<i>Пар нет</i>")
            continue

        lessons_count += len(lessons)
        body = service.format_day(lessons, day_date, group_name, is_predicted=is_predicted)
        body = body.split("\n", 1)[1].strip() if "\n" in body else body

        blocks.append(f"{header}\n<blockquote expandable>\n{body}\n</blockquote>")

    if lessons_count == 0:
        blocks = ["🎉 На эту неделю пар нет!"]

    return _join_blocks(title, blocks)


def _join_blocks(
    title: str, blocks: List[str], limit: int = TELEGRAM_TEXT_LIMIT
) -> str:
    """Склеивает дневные блоки, не превышая лимит Telegram."""
    parts = [title]
    hidden = 0

    for i, block in enumerate(blocks):
        if len(parts) > 1 and len("\n\n".join(parts + [block])) > limit:
            hidden = len(blocks) - i
            break
        parts.append(block)

    if hidden:
        parts.append(f"👉 Остальные {hidden} дн. — в разделе «Расписание».")

    return "\n\n".join(parts)


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
