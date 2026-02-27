from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from tgbot.database.repositories import (
    UserRepository,
    ScheduleRepository,
    AnalyticsRepository,
)
from tgbot.services.services import ScheduleService
from tgbot.keyboards.callback_data import ScheduleNav
from tgbot.keyboards.inline import get_schedule_hub_kb, get_main_menu
from tgbot.states.states import ScheduleState
from tgbot.services.utils import parse_date

schedule_router = Router()

DAYS_RU = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}


@schedule_router.callback_query(F.data == "my_schedule")
async def show_my_schedule(
    callback: CallbackQuery,
    user_repo: UserRepository,
    analytics_repo: AnalyticsRepository,
    state: FSMContext,
):
    from aiogram.exceptions import TelegramBadRequest
    from tgbot.states.states import RegState

    await state.clear()
    user = await user_repo.get_user(callback.from_user.id)
    if not user or not user.group_name:
        await state.set_state(RegState.search_group)
        try:
            await callback.message.edit_text(
                "🔍 <b>Выберите свою группу</b>\n\n"
                "У вас ещё не установлена группа. Введите название или часть названия группы для поиска:\n\n"
                "<i>Например: ИВТб-1301 или просто ИВТ</i>"
            )
        except TelegramBadRequest:
            await callback.answer("Введите название вашей группы в чат.", show_alert=True)
        return

    await analytics_repo.log_action(
        callback.from_user.id, "view_my_schedule", user.group_name
    )
    
    try:
        await callback.message.edit_text(
            f"📅 <b>Ваше расписание для {user.group_name}</b>\nВыберите период:",
            reply_markup=get_schedule_hub_kb(user.group_name),
        )
    except TelegramBadRequest:
        await callback.answer()


async def show_schedule_for_group(
    callback: CallbackQuery,
    group_name: str,
    target_date: date,
    user_repo: UserRepository,
    schedule_repo: ScheduleRepository,
    service: ScheduleService,
):
    user = await user_repo.get_user(callback.from_user.id)
    settings = user.settings if user and user.settings else None
    lessons = await schedule_repo.get_lessons(group_name, target_date)
    is_predicted = False
    
    if not lessons:
        lessons = await schedule_repo.get_predicted_schedule(group_name, target_date)
        is_predicted = True if lessons else False

    await callback.message.edit_text(
        service.format_day(lessons, target_date, group_name, settings, is_predicted=is_predicted),
        reply_markup=get_schedule_hub_kb(group_name),
    )


async def show_week_calendar(callback: CallbackQuery, group: str, state: FSMContext):
    """Показывает календарь на неделю для выбора даты"""
    from tgbot.keyboards.inline import get_week_calendar_kb

    await state.clear()  
    await callback.message.edit_text(
        "📅 <b>Выберите дату:</b>", reply_markup=get_week_calendar_kb(group)
    )

@schedule_router.callback_query(ScheduleNav.filter())
async def navigate_schedule(
    callback: CallbackQuery,
    callback_data: ScheduleNav,
    user_repo: UserRepository,
    analytics_repo: AnalyticsRepository,
    schedule_repo: ScheduleRepository,
    service: ScheduleService,
    state: FSMContext,
):
    from aiogram.exceptions import TelegramBadRequest
    
    user = await user_repo.get_user(callback.from_user.id)
    settings = user.settings if user else {}
    current = date.fromisoformat(callback_data.current_date)
    group = callback_data.group

    
    if callback_data.action == "custom_day":
        await show_week_calendar(callback, group, state)
        return

    if callback_data.action == "week":
        start_date = current
        end_date = start_date + timedelta(days=6)

        text_parts = [
            f"📆 <b>Расписание на неделю ({start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m')})</b>\nГруппа: {group}\n"
        ]

        has_any = False
        for i in range(7):
            day_date = start_date + timedelta(days=i)
            lessons = await schedule_repo.get_lessons(group, day_date)
            if lessons:
                has_any = True
                day_text = service.format_day(lessons, day_date, group, settings)
                text_parts.append(day_text)

        if not has_any:
            text_parts.append("🎉 На эту неделю пар нет!")

        try:
            await callback.message.edit_text(
                text="\n\n".join(text_parts),
                reply_markup=get_schedule_hub_kb(group)
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer("Это расписание уже показано.")
            else:
                raise e
        return

    
    if callback_data.action == "show_date":
        target_date = current
        lessons = await schedule_repo.get_lessons(group, target_date)
        is_predicted = False
        if not lessons:
            lessons = await schedule_repo.get_predicted_schedule(group, target_date)
            is_predicted = True if lessons else False
            
        await analytics_repo.log_action(
            callback.from_user.id,
            "schedule_nav_calendar",
            f"group:{callback_data.group}, date:{target_date}",
        )
        
        try:
            await callback.message.edit_text(
                text=service.format_day(lessons, target_date, group, settings, is_predicted=is_predicted),
                reply_markup=get_schedule_hub_kb(group)
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer("Это расписание уже показано.")
            else:
                raise e
        return

    
    if callback_data.action == "prev_day":
        new_date = current - timedelta(days=1)
        await analytics_repo.log_action(
            callback.from_user.id,
            f"schedule_nav_prev_day",
            f"group: {callback_data.group}, date:{new_date}",
        )
    elif callback_data.action == "next_day":
        new_date = current + timedelta(days=1)
        await analytics_repo.log_action(
            callback.from_user.id,
            f"schedule_nav_next_day",
            f"group: {callback_data.group}, date:{new_date}",
        )
    else:  # today
        new_date = current
        await analytics_repo.log_action(
            callback.from_user.id,
            f"schedule_nav_today",
            f"group: {callback_data.group}, date:{new_date}",
        )

    lessons = await schedule_repo.get_lessons(group, new_date)
    is_predicted = False
    if not lessons:
        lessons = await schedule_repo.get_predicted_schedule(group, new_date)
        is_predicted = True if lessons else False
    
    try:
        await callback.message.edit_text(
            text=service.format_day(lessons, new_date, group, settings, is_predicted=is_predicted),
            reply_markup=get_schedule_hub_kb(group)
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Это расписание уже показано.")
        else:
            raise e
@schedule_router.message(ScheduleState.waiting_for_date)
async def process_custom_date(
    message: Message,
    state: FSMContext,
    user_repo: UserRepository,
    schedule_repo: ScheduleRepository,
    service: ScheduleService,
):
    chosen_date = parse_date(message.text.strip())
    data = await state.get_data()
    group = data.get("group")
    kb = get_schedule_hub_kb(group)

    if not chosen_date:
        return await message.answer(
            "❌ Неверный формат даты. Введите в формате ДД.ММ (например, 25.12):",
            reply_markup=kb,
        )

    
    if chosen_date.year == 1900:
        chosen_date = chosen_date.replace(year=date.today().year)

    await state.clear()
    user = await user_repo.get_user(message.from_user.id)
    lessons = await schedule_repo.get_lessons(group, chosen_date)
    settings = user.settings if user else {}

    await message.answer(
        service.format_day(lessons, chosen_date, group, settings),
        reply_markup=get_schedule_hub_kb(group),
    )
