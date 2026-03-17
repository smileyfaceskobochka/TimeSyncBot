import asyncio
import logging
import re
from datetime import date
import aiohttp

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgbot.config import config
from tgbot.states.states import ScheduleState
from tgbot.keyboards.callback_data import TeacherNav
from tgbot.keyboards.inline import (
    get_teacher_institutes_kb, 
    get_teacher_faculties_kb, 
    get_teacher_departments_kb,
    get_main_menu
)
from tgbot.services.parser.teacher_parser import get_teacher_navigation_data, parse_teacher_html_report
from tgbot.services.parser.progress import ProgressReporter

teacher_router = Router()

# Cache for navigation data to avoid constant scraping
_nav_cache = None

async def get_cached_nav():
    global _nav_cache
    if _nav_cache is None:
        _nav_cache = await get_teacher_navigation_data()
    return _nav_cache

@teacher_router.callback_query(TeacherNav.filter(F.action == "start"))
async def teacher_search_start(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.answer("⏳ Загрузка списка институтов...")
        nav_data = await get_cached_nav()
        if not nav_data:
            return await callback.message.edit_text(
                "❌ Не удалось загрузить список институтов. Попробуйте позже.",
                reply_markup=get_main_menu(None, {})
            )
        
        await callback.message.edit_text(
            "🎓 <b>Поиск преподавателя</b>\n\nВы можете выбрать кафедру из списка ниже или <b>сразу ввести фамилию</b> (тогда я поищу по всем кафедрам, но это может занять время):",
            reply_markup=get_teacher_institutes_kb(nav_data)
        )
        # Allow immediate surname entry
        await state.set_state(ScheduleState.waiting_for_teacher)
        # Remove specific dept to indicate global search if surname entered here
        await state.update_data(teacher_dept=None)
        
    except Exception as e:
        if "message is not modified" in str(e):
             await callback.answer()
        else:
             logging.error(f"Error in teacher_search_start: {e}")
             await callback.answer("❌ Ошибка при открытии меню", show_alert=True)

@teacher_router.callback_query(TeacherNav.filter(F.action == "select_inst"))
async def teacher_select_inst(callback: CallbackQuery, callback_data: TeacherNav):
    nav_data = await get_cached_nav()
    inst_idx = int(callback_data.target)
    inst = nav_data[inst_idx]
    
    if not inst["faculties"]:
        return await callback.answer("⚠️ В этом институте нет доступных данных.")
    
    await callback.message.edit_text(
        f"🎓 <b>{inst['name']}</b>\n\nВыберите факультет:",
        reply_markup=get_teacher_faculties_kb(inst["faculties"], inst_idx)
    )

@teacher_router.callback_query(TeacherNav.filter(F.action == "select_fac"))
async def teacher_select_fac(callback: CallbackQuery, callback_data: TeacherNav):
    nav_data = await get_cached_nav()
    inst_idx = int(callback_data.inst)
    fac_idx = int(callback_data.target)
    fac = nav_data[inst_idx]["faculties"][fac_idx]
    
    if not fac["departments"]:
        return await callback.answer("⚠️ На этом факультете нет доступных кафедр.")
    
    await callback.message.edit_text(
        f"🎓 <b>{fac['name']}</b>\n\nВыберите кафедру:",
        reply_markup=get_teacher_departments_kb(fac["departments"], inst_idx, fac_idx)
    )

@teacher_router.callback_query(TeacherNav.filter(F.action == "select_dept"))
async def teacher_select_dept(callback: CallbackQuery, callback_data: TeacherNav, state: FSMContext):
    nav_data = await get_cached_nav()
    inst_idx = int(callback_data.inst)
    fac_idx = int(callback_data.fac)
    dept_idx = int(callback_data.target)
    dept = nav_data[inst_idx]["faculties"][fac_idx]["departments"][dept_idx]
    
    # Store dept info in state
    await state.update_data(teacher_dept=dept)
    
    await callback.message.edit_text(
        f"🏢 <b>{dept['name']}</b>\n\nВведите фамилию преподавателя (или её часть):",
        reply_markup=InlineKeyboardBuilder().button(text="« Назад", callback_data=TeacherNav(action="select_fac", target=str(fac_idx), inst=str(inst_idx)).pack()).as_markup()
    )
    # Set state to wait for surname
    await state.set_state(ScheduleState.waiting_for_teacher)

@teacher_router.message(ScheduleState.waiting_for_teacher)
async def teacher_search_surname(message: Message, state: FSMContext):
    data = await state.get_data()
    dept = data.get("teacher_dept")
    
    surname = message.text.strip().lower()
    if len(surname) < 3:
        return await message.answer("⚠️ Введите хотя бы 3 буквы для поиска.")

    progress = ProgressReporter(message)
    
    try:
        if dept:
            # Searching in specific department
            await progress.report(f"⏳ Поиск на кафедре {dept['name']}...", 0.3)
            reports_to_scan = [(dept["name"], dept["reports"][0]["url"])]
        else:
            # Global search
            await progress.report("🔎 Глобальный поиск по всем кафедрам (это может занять до 10 сек)...", 0.1)
            nav_data = await get_cached_nav()
            reports_to_scan = []
            for inst in nav_data:
                for fac in inst["faculties"]:
                    for d in fac["departments"]:
                        if d.get("reports"):
                            reports_to_scan.append((d["name"], d["reports"][0]["url"]))
        
        all_teacher_lessons = []
        
        async with aiohttp.ClientSession(headers=config.HTTP_HEADERS) as session:
            async def fetch_and_parse(d_name, url):
                try:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            html = await resp.read()
                            lessons = parse_teacher_html_report(html, d_name)
                            return [l for l in lessons if surname in (l.teacher or "").lower()]
                except:
                    return []
                return []

            # Process in chunks to avoid overwhelming server or hitting limits
            chunk_size = 10
            for i in range(0, len(reports_to_scan), chunk_size):
                chunk = reports_to_scan[i:i + chunk_size]
                tasks = [fetch_and_parse(name, url) for name, url in chunk]
                results = await asyncio.gather(*tasks)
                for res in results:
                    all_teacher_lessons.extend(res)
                
                p = 0.1 + (i / len(reports_to_scan)) * 0.8
                await progress.report(f"⏳ Проверено {min(i+chunk_size, len(reports_to_scan))}/{len(reports_to_scan)} кафедр...", p)

        if not all_teacher_lessons:
            return await message.answer(f"🔍 Преподаватель '{surname}' не найден ни на одной кафедре в текущем расписании.")
        
        # Group results by teacher name
        teachers_found = {}
        for l in all_teacher_lessons:
            if l.teacher not in teachers_found:
                teachers_found[l.teacher] = []
            teachers_found[l.teacher].append(l)

        if len(teachers_found) > 1:
            text = "🔎 Найдено несколько преподавателей. Уточните поиск:\n\n"
            for t in sorted(teachers_found.keys()):
                text += f"• {t}\n"
            return await message.answer(text)
        
        teacher_name = list(teachers_found.keys())[0]
        teacher_lessons = teachers_found[teacher_name]
        
        today_iso = date.today().isoformat()
        today_lessons = [l for l in teacher_lessons if l.date == today_iso]
        
        text = f"👤 <b>{teacher_name}</b>\n\n"
        if today_lessons:
            text += f"📅 <b>Расписание на сегодня ({date.today().strftime('%d.%m')}):</b>\n"
            for l in sorted(today_lessons, key=lambda x: x.pair_number or 0):
                text += f"\n{l.pair_number}️⃣ {l.start_time}-{l.end_time}\n"
                text += f"📍 <b>{l.building}-{l.room}</b>\n"
                text += f"📖 {l.subject}\n"
        else:
            text += "📅 Сегодня занятий нет или данные отсутствуют.\n"
            
        await message.answer(text, reply_markup=get_main_menu(None, {}))
        await state.clear()
        
    except Exception as e:
        logging.error(f"Error in teacher search: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при поиске: {e}")
