from datetime import date
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from tgbot.database.repositories import OccupancyRepository, AnalyticsRepository
from tgbot.services.services import OccupancyService
from tgbot.keyboards.inline import (
    get_free_rooms_date_kb, 
    get_free_rooms_calendar_kb,
    get_pair_selection_kb,
    get_building_selection_kb
)
from tgbot.keyboards.callback_data import FreeRoomsDate
from tgbot.states.states import ScheduleState # Using an existing state or creating a specific one

free_rooms_router = Router()

@free_rooms_router.callback_query(F.data == "free_rooms_start")
async def free_rooms_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🔍 <b>Поиск свободных аудиторий</b>\nВыберите дату:",
        reply_markup=get_free_rooms_date_kb()
    )
    await callback.answer()

@free_rooms_router.callback_query(FreeRoomsDate.filter(F.action == "select"))
async def process_date_select(callback: CallbackQuery, callback_data: FreeRoomsDate, state: FSMContext):
    await state.update_data(target_date=callback_data.date)
    await callback.message.edit_text(
        "🕒 <b>Выберите пару:</b>",
        reply_markup=get_pair_selection_kb()
    )
    await callback.answer()

@free_rooms_router.callback_query(FreeRoomsDate.filter(F.action == "custom"))
async def process_custom_date(callback: CallbackQuery):
    await callback.message.edit_text(
        "📅 <b>Выберите дату из списка:</b>",
        reply_markup=get_free_rooms_calendar_kb()
    )
    await callback.answer()

@free_rooms_router.callback_query(F.data.startswith("pair_"))
async def process_pair_select(callback: CallbackQuery, state: FSMContext, occupancy_repo: OccupancyRepository):
    pair_number = int(callback.data.split("_")[1])
    await state.update_data(pair_number=pair_number)
    
    buildings = await occupancy_repo.get_buildings()
    await callback.message.edit_text(
        "🏢 <b>Выберите корпус:</b>",
        reply_markup=get_building_selection_kb(buildings)
    )
    await callback.answer()

@free_rooms_router.callback_query(F.data.startswith("building_"))
async def process_building_select(
    callback: CallbackQuery, 
    state: FSMContext, 
    occupancy_service: OccupancyService,
    analytics_repo: AnalyticsRepository
):
    building = callback.data.split("_")[1]
    data = await state.get_data()
    target_date = date.fromisoformat(data['target_date'])
    pair_number = data['pair_number']
    
    free_rooms = await occupancy_service.find_free_rooms(target_date, pair_number, building)
    
    await analytics_repo.log_action(callback.from_user.id, "search_free_rooms", f"building:{building}, date:{target_date}, pair:{pair_number}")
    
    if not free_rooms:
        text = f"❌ Свободных аудиторий в корпусе <b>{building}</b> на <b>{pair_number} пару</b> ({target_date.strftime('%d.%m')}) не найдено."
    else:
        rooms_str = ", ".join(sorted(free_rooms))
        text = (
            f"🏢 <b>Корпус {building}</b>\n"
            f"📅 <b>{target_date.strftime('%d.%m')}</b>, <b>{pair_number} пара</b>\n\n"
            f"✅ <b>Свободные аудитории:</b>\n{rooms_str}"
        )
    
    await callback.message.edit_text(text, reply_markup=get_free_rooms_date_kb())
    await callback.answer()
