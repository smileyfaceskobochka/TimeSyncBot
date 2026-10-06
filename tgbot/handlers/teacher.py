import asyncio
import hashlib
import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple

import aiohttp
from aiogram import Router, F
from aiogram.enums import ChatAction
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    LinkPreviewOptions
)
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
    get_teacher_curriculum_kb,
    get_main_menu,
)
from tgbot.services.parser.teacher_parser import (
    get_teacher_navigation_data,
    find_active_teacher_reports,
    parse_teacher_html_report,
    teacher_mapping_manager,
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


async def fetch_teacher_lessons(teacher_name: str, target_date: Optional[date] = None) -> List[dict]:
    """Fetches and deduplicates all lessons for a teacher using dynamic curriculum mapping."""
    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, target_date)
    get_teacher_id(teacher_name)
    _teacher_lessons_cache[teacher_name] = (time.time(), lessons)
    return lessons


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
@teacher_router.message(ScheduleState.waiting_for_teacher, ~F.text.startswith("/"), ~F.text.in_({"📅 Сегодня", "📆 Завтра", "🗓 Неделя", "🏢 Аудитории", "👨‍🏫 Преподаватели", "⭐ Избранное", "🔎 Поиск группы", "⚙️ Настройки", "💬 Главное меню"}))
async def teacher_search_surname(message: Message, state: FSMContext, user_repo: UserRepository):
    query = message.text.strip()
    surname = query.lower()
    if len(surname) < 3:
        return await message.answer("⚠️ Введите хотя бы 3 буквы фамилии для поиска.")

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    progress = ProgressReporter(message)

    try:
        # 1. Если карта еще не построена — выполняем динамическую инициализацию (после первого поиска)
        if not teacher_mapping_manager.is_mapped():
            await progress.report(f"⏳ Первая инициализация карты преподавателей и учебных планов...", 0.15)
            ok = await teacher_mapping_manager.ensure_mapping(progress=progress)
            if not ok:
                return await message.answer("❌ Не удалось получить данные о кафедрах. Попробуйте позже.")
        else:
            await progress.report(f"🔎 Ищу преподавателя <b>{query}</b>...", 0.2)

        # 2. Ищем преподавателя в динамической карте
        matched_teachers = teacher_mapping_manager.search_teachers(query)

        if not matched_teachers:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔍 Искать снова", callback_data=TeacherNav(action="start").pack())
            builder.button(text="« Главное меню", callback_data="cmd_start")
            builder.adjust(1)
            return await message.answer(
                f"❌ Преподаватель с фамилией '<b>{query}</b>' не найден в базе университета.\n\n"
                "Попробуйте ввести фамилию точнее.",
                reply_markup=builder.as_markup()
            )

        for name in matched_teachers:
            get_teacher_id(name)

        # 3. Если найдено несколько — даём выбор
        if len(matched_teachers) > 1:
            await state.update_data(teacher_names=matched_teachers)
            return await message.answer(
                f"🔎 Найдено несколько преподавателей по запросу '<b>{query}</b>':\n"
                "Выберите нужного из списка:",
                reply_markup=get_teachers_selection_kb(matched_teachers)
            )

        # 4. Если ровно один — открываем расписание на СЕГОДНЯ
        single_name = matched_teachers[0]
        teacher_id = get_teacher_id(single_name)
        today = date.today()

        lessons = await teacher_mapping_manager.fetch_teacher_lessons(single_name, today)
        user = await user_repo.get_user(message.from_user.id)
        is_fav = bool(user and single_name in user.favorite_teachers)

        dept_names = teacher_mapping_manager.get_teacher_departments(single_name) or [teacher_mapping_manager.get_teacher_department(single_name)]
        rep = teacher_mapping_manager.get_teacher_report_for_date(single_name, today)
        html_url = rep.get("html_url") if rep else None
        xml_url = rep.get("xml_url") if rep else None

        text = _format_teacher_day(single_name, lessons, today, dept_name=dept_names)
        await message.answer(
            text, 
            reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav, html_url=html_url, xml_url=xml_url),
            link_preview_options=LinkPreviewOptions(is_disabled=True)
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
    teacher_names = data.get("teacher_names") or []
    
    idx_str = callback_data.target
    if not idx_str.isdigit() or int(idx_str) >= len(teacher_names):
        return await callback.answer("Ошибка выбора. Повторите поиск.", show_alert=True)
        
    teacher_name = teacher_names[int(idx_str)]
    teacher_id = get_teacher_id(teacher_name)
    today = date.today()

    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, today)
    user = await user_repo.get_user(callback.from_user.id)
    is_fav = bool(user and teacher_name in user.favorite_teachers)

    dept_names = teacher_mapping_manager.get_teacher_departments(teacher_name) or [teacher_mapping_manager.get_teacher_department(teacher_name)]
    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, today)
    html_url = rep.get("html_url") if rep else None
    xml_url = rep.get("xml_url") if rep else None

    text = _format_teacher_day(teacher_name, lessons, today, dept_name=dept_names)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav, html_url=html_url, xml_url=xml_url),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
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

    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, target_date)
    is_fav = bool(user and teacher_name in user.favorite_teachers)

    dept_names = teacher_mapping_manager.get_teacher_departments(teacher_name) or [teacher_mapping_manager.get_teacher_department(teacher_name)]
    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, target_date)
    html_url = rep.get("html_url") if rep else None
    xml_url = rep.get("xml_url") if rep else None

    text = _format_teacher_day(teacher_name, lessons, target_date, dept_name=dept_names)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, target_date, is_favorite=is_fav, html_url=html_url, xml_url=xml_url),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
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

    try:
        target_date = datetime.strptime(callback_data.date_val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target_date = date.today()

    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, target_date)
    dept_names = teacher_mapping_manager.get_teacher_departments(teacher_name) or [teacher_mapping_manager.get_teacher_department(teacher_name)]
    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, target_date)
    html_url = rep.get("html_url") if rep else None
    xml_url = rep.get("xml_url") if rep else None

    chunks = _format_teacher_schedule_chunks(teacher_name, lessons, dept_name=dept_names)

    if len(chunks) == 1:
        try:
            await callback.message.edit_text(chunks[0], reply_markup=get_teacher_schedule_kb(teacher_id, html_url=html_url, xml_url=xml_url), link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                await callback.message.answer(chunks[0], reply_markup=get_teacher_schedule_kb(teacher_id, html_url=html_url, xml_url=xml_url), link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        try:
            await callback.message.edit_text(chunks[0], link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramBadRequest:
            await callback.message.answer(chunks[0], link_preview_options=LinkPreviewOptions(is_disabled=True))

        for chunk in chunks[1:-1]:
            await callback.message.answer(chunk, link_preview_options=LinkPreviewOptions(is_disabled=True))

        await callback.message.answer(chunks[-1], reply_markup=get_teacher_schedule_kb(teacher_id, html_url=html_url, xml_url=xml_url), link_preview_options=LinkPreviewOptions(is_disabled=True))

    await callback.answer()


# ================= ПРОСМОТР УЧЕБНОГО ПЛАНА (ВСЕ ПЕРИОДЫ HTML/XML) =================
@teacher_router.callback_query(TeacherNav.filter(F.action == "curr"))
async def teacher_nav_curriculum(
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
        return await callback.answer("Преподаватель не найден.", show_alert=True)

    try:
        current_date = datetime.strptime(callback_data.date_val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        current_date = date.today()

    curriculum = teacher_mapping_manager.get_teacher_curriculum(teacher_name)
    dept_names = teacher_mapping_manager.get_teacher_departments(teacher_name)
    dept_header = f"🏛 <b>Кафедры:</b> {', '.join(dept_names)}" if len(dept_names) > 1 else (f"🏛 <b>Кафедра:</b> {dept_names[0]}" if dept_names else "")

    lines = [
        f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>",
    ]
    if dept_header:
        lines.append(dept_header)
    lines.extend([
        "",
        "📑 <b>Учебный план (официальные отчеты HTML и XML/XLS):</b>",
        "<i>Нажмите на ссылку для просмотра или скачивания:</i>\n"
    ])

    if not curriculum:
        lines.append("<i>Учебный план не найден.</i>")
    else:
        # Group by department if multiple departments
        # Sort so current active periods are highlighted
        cur_items = []
        for rep in curriculum:
            p_text = rep.get("period") or "Период"
            h_url = rep.get("html_url") or rep.get("url")
            x_url = rep.get("xml_url")
            d_name = rep.get("department") or ""

            is_active = False
            s_str = rep.get("start_date")
            e_str = rep.get("end_date")
            if s_str and e_str:
                try:
                    s_d = date.fromisoformat(s_str)
                    e_d = date.fromisoformat(e_str)
                    if s_d <= current_date <= e_d:
                        is_active = True
                except ValueError:
                    pass

            marker = "👉 <b>" if is_active else "▫️ "
            close_tag = " (текущий)</b>" if is_active else ""

            parts = []
            if h_url:
                parts.append(f'<a href="{h_url}">HTML</a>')
            if x_url:
                parts.append(f'<a href="{x_url}">XML/XLS</a>')
            links_str = " | ".join(parts) if parts else ""

            dept_badge = f" <i>({d_name.split()[1] if len(d_name.split()) > 1 else d_name[:15]})</i>" if len(dept_names) > 1 else ""
            line_str = f"{marker}{p_text}{dept_badge}{close_tag} — [{links_str}]"
            cur_items.append((is_active, s_str or "", line_str))

        # Show active periods first, and ensure total text does not exceed 3800 chars
        cur_items.sort(key=lambda x: (not x[0], x[1]))
        total_len = sum(len(l) for l in lines)
        for _, _, l_str in cur_items:
            if total_len + len(l_str) + 2 > 3800:
                lines.append(f"\n<i>... и еще {len(cur_items) - len(lines) + 4} периодов в базе.</i>")
                break
            lines.append(l_str)
            total_len += len(l_str) + 1

    text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        reply_markup=get_teacher_curriculum_kb(teacher_id, current_date),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
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

    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, current_date)
    html_url = rep.get("html_url") if rep else None
    xml_url = rep.get("xml_url") if rep else None

    await callback.message.edit_reply_markup(
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, current_date, is_favorite=is_fav, html_url=html_url, xml_url=xml_url)
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
    today = date.today()
    lessons = await teacher_mapping_manager.fetch_teacher_lessons(teacher_name, today)

    is_fav = bool(user and teacher_name in user.favorite_teachers)
    dept_name = teacher_mapping_manager.get_teacher_department(teacher_name)
    rep = teacher_mapping_manager.get_teacher_report_for_date(teacher_name, today)
    html_url = rep.get("html_url") if rep else None
    xml_url = rep.get("xml_url") if rep else None

    text = _format_teacher_day(teacher_name, lessons, today, dept_name=dept_name)
    await callback.message.edit_text(
        text, 
        reply_markup=get_teacher_schedule_hub_kb(teacher_id, today, is_favorite=is_fav, html_url=html_url, xml_url=xml_url),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
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
def _format_teacher_day(teacher_name: str, lessons: List[dict], target_date: date, dept_name: Optional[str] = None) -> str:
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

    lines = [f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>"]
    if dept_name:
        if isinstance(dept_name, (list, set, tuple)):
            clean_depts = [d for d in dept_name if d]
            if len(clean_depts) > 1:
                lines.append(f"🏛 <b>Кафедры:</b> {', '.join(clean_depts)}")
            elif clean_depts:
                lines.append(f"🏛 <b>Кафедра:</b> {clean_depts[0]}")
        else:
            lines.append(f"🏛 <b>Кафедра:</b> {dept_name}")
    lines.append(f"📅 <b>{header_date}</b>")

    if not day_lessons:
        lines.append("\n🎉 <i>В этот день занятий у преподавателя нет!</i>")
        return "\n".join(lines)

    sorted_pairs = sorted(day_lessons, key=lambda x: x.get("pair_number") or 0)
    merged_pairs = {}
    for l in sorted_pairs:
        key = (
            l.get("pair_number"),
            l.get("start_time"),
            (l.get("subject") or "").strip().lower(),
            (l.get("class_type") or "").strip().lower(),
            (l.get("room") or "").strip().lower(),
            (l.get("building") or "").strip().lower()
        )
        if key not in merged_pairs:
            merged_pairs[key] = dict(l)
        else:
            existing_grp = merged_pairs[key].get("groups") or ""
            new_grp = l.get("groups") or ""
            all_grps = [g.strip() for g in f"{existing_grp}, {new_grp}".split(",") if g.strip()]
            merged_pairs[key]["groups"] = ", ".join(sorted(list(set(all_grps))))

    for l in merged_pairs.values():
        lines.append(_format_teacher_pair(l))

    return "\n".join(lines).strip()


# ================= ФОРМАТИРОВАНИЕ РАСПИСАНИЯ ПРЕПОДАВАТЕЛЯ С РАЗБИВКОЙ =================
def _format_teacher_schedule_chunks(
    teacher_name: str, 
    lessons: List[dict], 
    max_chars: int = 3500,
    dept_name: Optional[str] = None
) -> List[str]:
    """Форматирует всю неделю с безопасной разбивкой на сообщения до 3500 символов."""
    if not lessons:
        header = f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>\n"
        if dept_name:
            header += f"🏛 <b>Кафедра:</b> {dept_name}\n"
        return [f"{header}\nЗанятий на текущий период не найдено."]

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
    curr = f"👨‍🏫 Преподаватель: <b>{teacher_name}</b>\n"
    if dept_name:
        if isinstance(dept_name, (list, set, tuple)):
            clean_depts = [d for d in dept_name if d]
            if len(clean_depts) > 1:
                curr += f"🏛 <b>Кафедры:</b> {', '.join(clean_depts)}\n"
            elif clean_depts:
                curr += f"🏛 <b>Кафедра:</b> {clean_depts[0]}\n"
        else:
            curr += f"🏛 <b>Кафедра:</b> {dept_name}\n"
    curr += "\n"

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

