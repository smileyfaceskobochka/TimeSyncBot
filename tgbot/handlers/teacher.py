import asyncio
import hashlib
import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple

import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from tgbot.config import config
from tgbot.database.models import Lesson, User
from tgbot.database.repositories import UserRepository
from tgbot.states.states import ScheduleState
from tgbot.keyboards.callback_data import TeacherNav
from tgbot.keyboards.inline import (
    get_teachers_selection_kb,
    get_teacher_schedule_kb,
    get_teacher_schedule_hub_kb,
    get_teacher_calendar_kb,
    get_main_menu,
)
from tgbot.services.parser.teacher_parser import (
    get_teacher_navigation_data,
    find_active_teacher_reports,
    parse_teacher_html_report,
)
from tgbot.services.parser.progress import ProgressReporter

teacher_router = Router()

# Cache for navigation data (6 hours TTL)
_nav_cache = None
_nav_cache_timestamp = 0.0
NAV_CACHE_TTL = 6 * 3600

# Cache for teacher lessons by full name: teacher_name -> (timestamp, List[dict])
_teacher_lessons_cache: Dict[str, Tuple[float, List[dict]]] = {}
TEACHER_CACHE_TTL = 3600  # 1 hour

# Registry for short IDs to avoid Telegram 64-byte callback_data overflow
_teacher_id_registry: Dict[str, str] = {}  # id -> name
_teacher_name_to_id: Dict[str, str] = {}   # name -> id


def get_teacher_id(name: str) -> str:
    """Returns a short 10-char hash ID for a teacher to fit within 64-byte callback_data."""
    if name not in _teacher_name_to_id:
        t_id = hashlib.md5(name.encode("utf-8")).hexdigest()[:10]
        _teacher_id_registry[t_id] = name
        _teacher_name_to_id[name] = t_id
    return _teacher_name_to_id[name]


def get_teacher_by_id(t_id: str) -> Optional[str]:
    """Returns teacher full name by short ID."""
    return _teacher_id_registry.get(t_id)


def resolve_teacher(t_id: str, user: Optional[User] = None) -> Optional[str]:
    """Resolves teacher name from short ID, falling back to user's favorite teachers."""
    name = _teacher_id_registry.get(t_id)
    if name:
        return name
    if user and user.favorite_teachers:
        for t in user.favorite_teachers:
            if get_teacher_id(t) == t_id:
                return t
    return None


async def get_cached_nav():
    global _nav_cache, _nav_cache_timestamp
    now = time.time()
    if _nav_cache is None or (now - _nav_cache_timestamp) > NAV_CACHE_TTL:
        fresh_data = await get_teacher_navigation_data()
        if fresh_data:
            _nav_cache = fresh_data
            _nav_cache_timestamp = now
    return _nav_cache


async def fetch_teacher_lessons(teacher_name: str) -> List[dict]:
    """Fetches and deduplicates all lessons for a teacher from VyatSU active reports."""
    now = time.time()
    if teacher_name in _teacher_lessons_cache:
        timestamp, cached = _teacher_lessons_cache[teacher_name]
        if (now - timestamp) < TEACHER_CACHE_TTL:
            return cached

    nav_data = await get_cached_nav()
    if not nav_data:
        return []

    active_reports = find_active_teacher_reports(nav_data)
    if not active_reports:
        return []

    sem = asyncio.Semaphore(25)
    async with aiohttp.ClientSession(
        headers=config.HTTP_HEADERS,
        connector=aiohttp.TCPConnector(limit=30)
    ) as session:
        async def fetch_dept(dept_name: str, url: str) -> List[Lesson]:
            async with sem:
                try:
                    async with session.get(url, timeout=12) as resp:
                        if resp.status == 200:
                            html_data = await resp.read()
                            lessons = parse_teacher_html_report(html_data, dept_name)
                            return [l for l in lessons if (l.teacher and teacher_name.lower() in l.teacher.lower())]
                except Exception as e:
                    logging.debug(f"Error fetching teacher report for {dept_name}: {e}")
                return []

        tasks = [fetch_dept(dept_name, url) for dept_name, url in active_reports]
        batch_results = await asyncio.gather(*tasks)

    all_lessons = [lesson for sublist in batch_results for lesson in sublist]
    seen_keys = set()
    formatted = []
    for l in all_lessons:
        key = (l.date, l.pair_number, l.start_time, l.subject, l.class_type, l.room, l.group_name)
        if key not in seen_keys:
            seen_keys.add(key)
            formatted.append({
                "date": l.date,
                "pair_number": l.pair_number,
                "start_time": l.start_time,
                "end_time": l.end_time,
                "subject": l.subject,
                "class_type": l.class_type,
                "building": l.building,
                "room": l.room,
                "groups": l.group_name,
                "raw_info": l.raw_info,
                "teacher": l.teacher,
            })

    _teacher_lessons_cache[teacher_name] = (now, formatted)
    get_teacher_id(teacher_name)
    return formatted


# ================= СТАРТ ПОИСКА ПРЕПОДАВАТЕЛЯ =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "start"))
async def teacher_search_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ScheduleState.waiting_for_teacher)
    await state.update_data(teacher_results=None)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    
    text = (
        "🎓 <b>Поиск преподавателя</b>\n\n"
        "Введите фамилию преподавателя (или её часть):\n"
        "<i>Например: Долженкова, Тарасов или Бызов</i>"
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await callback.message.answer(text, reply_markup=builder.as_markup())
    await callback.answer()


@teacher_router.message(Command("teacher"))
async def teacher_search_cmd(message: Message, state: FSMContext):
    await state.set_state(ScheduleState.waiting_for_teacher)
    await state.update_data(teacher_results=None)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    text = (
        "🎓 <b>Поиск преподавателя</b>\n\n"
        "Введите фамилию преподавателя (или её часть):\n"
        "<i>Например: Долженкова, Тарасов или Бызов</i>"
    )
    await message.answer(text, reply_markup=builder.as_markup())


# ================= ОБРАБОТКА ВВОДА ФАМИЛИИ =================
@teacher_router.message(ScheduleState.waiting_for_teacher)
async def teacher_search_surname(message: Message, state: FSMContext, user_repo: UserRepository):
    query = message.text.strip()
    surname = query.lower()
    if len(surname) < 3:
        return await message.answer("⚠️ Введите хотя бы 3 буквы фамилии для поиска.")

    progress = ProgressReporter(message)
    await progress.report(f"🔎 Ищу преподавателя <b>{query}</b> по всем кафедрам университета...", 0.1)

    try:
        nav_data = await get_cached_nav()
        if not nav_data:
            return await message.answer("❌ Не удалось получить данные о кафедрах. Попробуйте позже.")

        active_reports = find_active_teacher_reports(nav_data)
        if not active_reports:
            return await message.answer("⚠️ Не удалось найти расписание преподавателей на текущую неделю.")

        await progress.report(f"⏳ Сканирую {len(active_reports)} кафедр ВятГУ...", 0.3)

        sem = asyncio.Semaphore(25)
        async with aiohttp.ClientSession(
            headers=config.HTTP_HEADERS,
            connector=aiohttp.TCPConnector(limit=30)
        ) as session:
            async def fetch_dept(dept_name: str, url: str) -> List[Lesson]:
                async with sem:
                    try:
                        async with session.get(url, timeout=12) as resp:
                            if resp.status == 200:
                                html_data = await resp.read()
                                lessons = parse_teacher_html_report(html_data, dept_name)
                                return [l for l in lessons if surname in (l.teacher or "").lower()]
                    except Exception as e:
                        logging.debug(f"Error fetching teacher report for {dept_name}: {e}")
                    return []

            tasks = [fetch_dept(dept_name, url) for dept_name, url in active_reports]
            batch_results = await asyncio.gather(*tasks)

        all_teacher_lessons = [lesson for sublist in batch_results for lesson in sublist]

        if not all_teacher_lessons:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔍 Искать снова", callback_data=TeacherNav(action="start").pack())
            builder.button(text="« Главное меню", callback_data="cmd_start")
            builder.adjust(1)
            return await message.answer(
                f"❌ Преподаватель с фамилией '<b>{query}</b>' не найден в расписании текущей недели.\n\n"
                "Попробуйте ввести фамилию точнее.",
                reply_markup=builder.as_markup()
            )

        # Группируем найденные уроки по полному имени преподавателя с дедупликацией
        teachers_found: Dict[str, List[dict]] = {}
        seen_keys = set()
        for l in all_teacher_lessons:
            if not l.teacher:
                continue
            if l.teacher not in teachers_found:
                teachers_found[l.teacher] = []

            key = (l.teacher, l.date, l.pair_number, l.start_time, l.subject, l.class_type, l.room, l.group_name)
            if key not in seen_keys:
                seen_keys.add(key)
                teachers_found[l.teacher].append({
                    "date": l.date,
                    "pair_number": l.pair_number,
                    "start_time": l.start_time,
                    "end_time": l.end_time,
                    "subject": l.subject,
                    "class_type": l.class_type,
                    "building": l.building,
                    "room": l.room,
                    "groups": l.group_name,
                    "raw_info": l.raw_info,
                })

        teacher_names = sorted(list(teachers_found.keys()))

        # Регистрируем в ID-реестре и кэше
        for name in teacher_names:
            get_teacher_id(name)
            _teacher_lessons_cache[name] = (time.time(), teachers_found[name])

        # Если найдено несколько преподавателей — даём выбор
        if len(teacher_names) > 1:
            await state.update_data(teacher_results=teachers_found, teacher_names=teacher_names)
            return await message.answer(
                f"🔎 Найдено несколько преподавателей по запросу '<b>{query}</b>':\n"
                "Выберите нужного из списка:",
                reply_markup=get_teachers_selection_kb(teacher_names)
            )

        # Если найден ровно один — открываем расписание на СЕГОДНЯ в интерактивном хабе
        single_name = teacher_names[0]
        teacher_id = get_teacher_id(single_name)
        today = date.today()

        user = await user_repo.get_user(message.from_user.id)
        is_fav = bool(user and single_name in user.favorite_teachers)

        text = _format_teacher_day(single_name, teachers_found[single_name], today)
        await message.answer(
            text, 
            reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav)
        )
        await state.update_data(current_teacher_id=teacher_id, current_teacher_name=single_name)

    except Exception as e:
        logging.error(f"Error in teacher search: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при поиске: {e}")


# ================= ВЫБОР ИЗ СПИСКА НАЙДЕННЫХ ПРЕПОДАВАТЕЛЕЙ =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "view"))
async def teacher_view_selected(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    state: FSMContext, 
    user_repo: UserRepository
):
    data = await state.get_data()
    teachers_found = data.get("teacher_results") or {}
    teacher_names = data.get("teacher_names") or []
    
    idx_str = callback_data.target
    if not idx_str.isdigit() or int(idx_str) >= len(teacher_names):
        return await callback.answer("Ошибка выбора. Повторите поиск.", show_alert=True)
        
    teacher_name = teacher_names[int(idx_str)]
    teacher_id = get_teacher_id(teacher_name)
    lessons = teachers_found.get(teacher_name, [])
    
    _teacher_lessons_cache[teacher_name] = (time.time(), lessons)
    today = date.today()

    user = await user_repo.get_user(callback.from_user.id)
    is_fav = bool(user and teacher_name in user.favorite_teachers)

    text = _format_teacher_day(teacher_name, lessons, today)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav)
    )
    await state.update_data(current_teacher_id=teacher_id, current_teacher_name=teacher_name)
    await callback.answer()


# ================= ПЕРЕКЛЮЧЕНИЕ ДНЯ (СЕГОДНЯ, ЗАВТРА, ДАТА ИЗ КАЛЕНДАРЯ) =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "day"))
async def teacher_nav_day(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    state: FSMContext, 
    user_repo: UserRepository
):
    teacher_id = callback_data.target
    user = await user_repo.get_user(callback.from_user.id)
    teacher_name = resolve_teacher(teacher_id, user)
    if not teacher_name:
        data = await state.get_data()
        teacher_name = data.get("current_teacher_name")
        if teacher_name:
            teacher_id = get_teacher_id(teacher_name)

    if not teacher_name:
        return await callback.answer("Преподаватель не найден. Повторите поиск.", show_alert=True)

    try:
        target_date = datetime.strptime(callback_data.date_val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target_date = date.today()

    lessons = await fetch_teacher_lessons(teacher_name)
    is_fav = bool(user and teacher_name in user.favorite_teachers)

    text = _format_teacher_day(teacher_name, lessons, target_date)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, target_date, is_favorite=is_fav)
    )
    await callback.answer()


# ================= КАЛЕНДАРЬ НА НЕДЕЛЮ =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "cal"))
async def teacher_nav_calendar(callback: CallbackQuery, callback_data: TeacherNav):
    teacher_id = callback_data.target
    try:
        current_date = datetime.strptime(callback_data.date_val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        current_date = date.today()

    await callback.message.edit_reply_markup(
        reply_markup=get_teacher_calendar_kb(teacher_id, current_date)
    )
    await callback.answer()


# ================= ПРОСМОТР ВСЕЙ НЕДЕЛИ =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "week"))
async def teacher_nav_week(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    state: FSMContext,
    user_repo: UserRepository
):
    teacher_id = callback_data.target
    user = await user_repo.get_user(callback.from_user.id)
    teacher_name = resolve_teacher(teacher_id, user)
    if not teacher_name:
        data = await state.get_data()
        teacher_name = data.get("current_teacher_name")
        if teacher_name:
            teacher_id = get_teacher_id(teacher_name)

    if not teacher_name:
        return await callback.answer("Преподаватель не найден. Повторите поиск.", show_alert=True)

    lessons = await fetch_teacher_lessons(teacher_name)
    chunks = _format_teacher_schedule_chunks(teacher_name, lessons)

    if len(chunks) == 1:
        try:
            await callback.message.edit_text(chunks[0], reply_markup=get_teacher_schedule_kb(teacher_id))
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                await callback.message.answer(chunks[0], reply_markup=get_teacher_schedule_kb(teacher_id))
    else:
        try:
            await callback.message.edit_text(chunks[0])
        except TelegramBadRequest:
            await callback.message.answer(chunks[0])

        for chunk in chunks[1:-1]:
            await callback.message.answer(chunk)

        await callback.message.answer(chunks[-1], reply_markup=get_teacher_schedule_kb(teacher_id))

    await callback.answer()


# ================= ДОБАВЛЕНИЕ / УДАЛЕНИЕ ИЗ ИЗБРАННОГО =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "fav_toggle"))
async def teacher_fav_toggle(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    state: FSMContext, 
    user_repo: UserRepository
):
    teacher_id = callback_data.target
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        user = User(telegram_id=callback.from_user.id)

    teacher_name = resolve_teacher(teacher_id, user)
    if not teacher_name:
        data = await state.get_data()
        teacher_name = data.get("current_teacher_name")
        if teacher_name:
            teacher_id = get_teacher_id(teacher_name)

    if not teacher_name:
        return await callback.answer("Преподаватель не найден.", show_alert=True)

    favs = user.favorite_teachers
    if teacher_name in favs:
        favs.remove(teacher_name)
        user.favorite_teachers = favs
        await user_repo.upsert_user(user)
        is_fav = False
        await callback.answer(f"❌ {teacher_name} удален из избранного")
    else:
        favs.append(teacher_name)
        user.favorite_teachers = favs
        await user_repo.upsert_user(user)
        is_fav = True
        await callback.answer(f"⭐ {teacher_name} добавлен в избранное!")

    try:
        current_date = datetime.strptime(callback_data.date_val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        current_date = date.today()

    await callback.message.edit_reply_markup(
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, current_date, is_favorite=is_fav)
    )


# ================= ОТКРЫТИЕ ИЗ ИЗБРАННОГО =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "fav_open"))
async def teacher_fav_open(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    state: FSMContext, 
    user_repo: UserRepository
):
    teacher_id = callback_data.target
    user = await user_repo.get_user(callback.from_user.id)
    teacher_name = resolve_teacher(teacher_id, user)
    if not teacher_name:
        return await callback.answer("Преподаватель не найден.", show_alert=True)

    await callback.answer("Загружаю расписание...")
    lessons = await fetch_teacher_lessons(teacher_name)
    today = date.today()

    is_fav = bool(user and teacher_name in user.favorite_teachers)

    text = _format_teacher_day(teacher_name, lessons, today)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav)
    )
    await state.update_data(current_teacher_id=teacher_id, current_teacher_name=teacher_name)


# ================= ФОРМАТИРОВАНИЕ ОДНОЙ ПАРЫ ПРЕПОДАВАТЕЛЯ =================
def _format_teacher_pair(l: dict) -> str:
    """Форматирует одну пару преподавателя в едином стиле бота."""
    p_num = l.get("pair_number") or "?"
    start = l.get("start_time") or ""
    end = l.get("end_time") or ""
    if (not start or not end) and isinstance(p_num, int) and p_num in config.STANDARD_PAIRS:
        parts = config.STANDARD_PAIRS[p_num].split(" - ")
        start = start or parts[0]
        end = end or parts[1]

    time_str = f"{start} - {end}".strip(" -")
    time_part = f" {time_str}" if time_str else ""

    c_type = l.get("class_type") or ""
    ctype_lower = c_type.lower()
    if "лек" in ctype_lower:
        icon = "🔴"
    elif "прак" in ctype_lower or "пр." in ctype_lower or "сем" in ctype_lower:
        icon = "🟢"
    elif "лаб" in ctype_lower:
        icon = "🔵"
    elif "зачет" in ctype_lower or "экзамен" in ctype_lower or "консульт" in ctype_lower:
        icon = "⚠️"
    else:
        icon = "⚪️"

    lines = [f"\n<b>{p_num} {icon}{time_part}</b>"]
    
    subject = l.get("subject") or "Занятие"
    lines.append(f"<b>{subject}</b>")
    if c_type:
        lines.append(f"{c_type}")

    meta = []
    bld = l.get("building")
    rm = l.get("room")
    if bld and rm:
        meta.append(f"📍 {bld}-{rm}")
    elif rm:
        meta.append(f"📍 ауд. {rm}")
    elif bld:
        meta.append(f"📍 {bld} к.")

    groups = l.get("groups")
    if groups:
        meta.append(f"👥 {groups}")

    if meta:
        lines.append(" | ".join(meta))

    return "\n".join(lines)


# ================= ФОРМАТИРОВАНИЕ ОДНОГО ДНЯ ПРЕПОДАВАТЕЛЯ =================
def _format_teacher_day(teacher_name: str, lessons: List[dict], target_date: date) -> str:
    """Форматирует расписание преподавателя на конкретный день."""
    target_str = target_date.isoformat()
    day_lessons = [l for l in lessons if l.get("date") == target_str]

    weekdays = {
        0: "Понедельник", 1: "Вторник", 2: "Среда", 
        3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
    }
    weekday_name = weekdays.get(target_date.weekday(), "")
    date_display = target_date.strftime("%d.%m.%Y")

    today = date.today()
    if target_date == today:
        header_date = f"Сегодня ({weekday_name}, {date_display})"
    elif target_date == today + timedelta(days=1):
        header_date = f"Завтра ({weekday_name}, {date_display})"
    elif target_date == today + timedelta(days=2):
        header_date = f"Послезавтра ({weekday_name}, {date_display})"
    else:
        header_date = f"{weekday_name} ({date_display})"

    lines = [
        f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>",
        f"📅 <b>{header_date}</b>"
    ]

    if not day_lessons:
        lines.append("\n🎉 <i>В этот день занятий у преподавателя нет!</i>")
        return "\n".join(lines)

    sorted_pairs = sorted(day_lessons, key=lambda x: x.get("pair_number") or 0)
    for l in sorted_pairs:
        lines.append(_format_teacher_pair(l))

    return "\n".join(lines).strip()


# ================= ФОРМАТИРОВАНИЕ РАСПИСАНИЯ ПРЕПОДАВАТЕЛЯ С РАЗБИВКОЙ =================
def _format_teacher_schedule_chunks(
    teacher_name: str, 
    lessons: List[dict], 
    max_chars: int = 3500
) -> List[str]:
    """Форматирует всю неделю с безопасной разбивкой на сообщения до 3500 символов."""
    if not lessons:
        return [f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>\n\nЗанятий на текущий период не найдено."]

    weekdays = {
        0: "Понедельник", 1: "Вторник", 2: "Среда", 
        3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"
    }

    by_date: Dict[str, List[dict]] = {}
    for l in lessons:
        d = l["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(l)

    today = date.today()
    today_iso = today.isoformat()

    day_blocks: List[str] = []
    for d_str in sorted(by_date.keys()):
        day_lessons = by_date[d_str]
        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            weekday_name = weekdays.get(d_obj.weekday(), "")
            date_display = d_obj.strftime("%d.%m")
            if d_str == today_iso:
                header = f"📅 <b>Сегодня ({weekday_name}, {date_display}):</b>"
            else:
                header = f"📅 <b>{weekday_name} ({date_display}):</b>"
        except ValueError:
            header = f"📅 <b>{d_str}:</b>"

        day_lines = [header]
        sorted_pairs = sorted(day_lessons, key=lambda x: x.get("pair_number") or 0)
        for l in sorted_pairs:
            day_lines.append(_format_teacher_pair(l))

        day_blocks.append("\n".join(day_lines))

    chunks: List[str] = []
    curr = f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>\n\n"

    for block in day_blocks:
        if len(curr) + len(block) + 2 > max_chars:
            if curr.strip():
                chunks.append(curr.strip())
            curr = f"👨‍🏫 <b>{teacher_name}</b> (продолжение):\n\n{block}\n\n"
        else:
            curr += block + "\n\n"

    if curr.strip():
        chunks.append(curr.strip())

    return chunks

