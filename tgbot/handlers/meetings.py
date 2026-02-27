from datetime import date
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from tgbot.database.repositories import UserRepository, ScheduleRepository, AnalyticsRepository
from tgbot.services.services import ScheduleService
from tgbot.keyboards.inline import (
    get_meeting_all_groups_kb, 
    get_meeting_date_kb,
    get_back_to_dates_kb
)
from tgbot.keyboards.callback_data import MeetingCb
from tgbot.services.utils import parse_date
from tgbot.states.states import MeetingState

meeting_router = Router()

@meeting_router.callback_query(F.data == "meet_start")
async def meet_start(callback: CallbackQuery, state: FSMContext, schedule_repo: ScheduleRepository):
    await state.clear()
    all_groups = await schedule_repo.get_all_group_names()
    await state.update_data(selected_groups=[])
    await callback.message.edit_text(
        "🤝 <b>Общие окна (Встречи)</b>\nВыберите группы для сравнения расписания:",
        reply_markup=get_meeting_all_groups_kb(all_groups, [])
    )
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "toggle"))
async def toggle_group(callback: CallbackQuery, callback_data: MeetingCb, state: FSMContext, schedule_repo: ScheduleRepository):
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    group = callback_data.value
    
    if group in selected:
        selected.remove(group)
    else:
        selected.append(group)
    
    await state.update_data(selected_groups=selected)
    
    all_groups = await schedule_repo.get_all_group_names()
    page = data.get("page", 0)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_meeting_all_groups_kb(all_groups, selected, page)
    )
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "page"))
async def process_page(callback: CallbackQuery, callback_data: MeetingCb, state: FSMContext, schedule_repo: ScheduleRepository):
    page = int(callback_data.value)
    await state.update_data(page=page)
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    all_groups = await schedule_repo.get_all_group_names()
    
    await callback.message.edit_reply_markup(
        reply_markup=get_meeting_all_groups_kb(all_groups, selected, page)
    )
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "pick_date"))
async def pick_date(callback: CallbackQuery):
    await callback.message.edit_text(
        "📅 <b>Выберите дату встречи:</b>",
        reply_markup=get_meeting_date_kb()
    )
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "back_to_groups"))
async def back_to_groups(callback: CallbackQuery, state: FSMContext, schedule_repo: ScheduleRepository):
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    page = data.get("page", 0)
    all_groups = await schedule_repo.get_all_group_names()
    await callback.message.edit_text(
        "🤝 <b>Сравнение расписания</b>\nВыберите группы:",
        reply_markup=get_meeting_all_groups_kb(all_groups, selected, page)
    )
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "date"))
async def process_meet_date(
    callback: CallbackQuery, 
    callback_data: MeetingCb, 
    state: FSMContext, 
    schedule_repo: ScheduleRepository,
    service: ScheduleService,
    analytics_repo: AnalyticsRepository
):
    target_date = date.fromisoformat(callback_data.value)
    data = await state.get_data()
    groups = data.get("selected_groups", [])
    
    await analytics_repo.log_action(callback.from_user.id, "check_common_windows", f"groups:{groups}, date:{target_date}")
    
    result_text = await service.find_common_free_slots(schedule_repo, groups, target_date)
    await callback.message.edit_text(result_text, reply_markup=get_back_to_dates_kb())
    await callback.answer()

@meeting_router.callback_query(MeetingCb.filter(F.action == "manual_date"))
async def manual_date_start(callback: CallbackQuery, state: FSMContext):
    from tgbot.states.states import MeetingState
    await callback.message.edit_text("⌨️ Введите дату в формате <b>ДД.ММ</b> (например: 25.12):")
    await state.set_state(MeetingState.waiting_for_date)
    await callback.answer()

@meeting_router.message(MeetingState.waiting_for_date)
async def process_manual_date(
    message: Message,
    state: FSMContext,
    schedule_repo: ScheduleRepository,
    service: ScheduleService,
    analytics_repo: AnalyticsRepository
):
    target_date = parse_date(message.text.strip())
    if not target_date:
        return await message.answer("❌ Неверный формат даты. Введите в формате ДД.ММ (например, 25.12):")
    
    data = await state.get_data()
    groups = data.get("selected_groups", [])
    
    await analytics_repo.log_action(message.from_user.id, "check_common_windows_manual", f"groups:{groups}, date:{target_date}")
    
    result_text = await service.find_common_free_slots(schedule_repo, groups, target_date)
    await state.set_state(None)
    await message.answer(result_text, reply_markup=get_back_to_dates_kb())
# Note: meeting_router.message handler for ScheduleState.waiting_for_date is handled in user.py or we should add it here if it's meeting-specific. 
# Looking at user.py, it handles ScheduleState.waiting_for_date but it seems oriented towards 'show_schedule_for_group'.
# Let's add a specific state OR check how it's used.
