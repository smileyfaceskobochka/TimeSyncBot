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
    get_building_selection_kb,
    get_available_pairs_kb
)
from tgbot.keyboards.callback_data import FreeRoomsDate
from tgbot.states.states import ScheduleState # Using an existing state or creating a specific one

free_rooms_router = Router()

@free_rooms_router.callback_query(F.data == "free_rooms_start")
async def free_rooms_start(callback: CallbackQuery, state: FSMContext, occupancy_repo: OccupancyRepository):
    await state.clear()
    buildings = await occupancy_repo.get_buildings()
    await callback.message.edit_text(
        "🏢 <b>Выберите корпус:</b>",
        reply_markup=get_building_selection_kb(buildings)
    )
    await callback.answer()

@free_rooms_router.callback_query(F.data.startswith("building_"))
async def process_building_select(callback: CallbackQuery, state: FSMContext):
    building = callback.data.split("_")[1]
    await state.update_data(building=building)
    await callback.message.edit_text(
        f"🏢 Корпус <b>{building}</b>\n📅 <b>Выберите дату:</b>",
        reply_markup=get_free_rooms_date_kb()
    )
    await callback.answer()

@free_rooms_router.callback_query(FreeRoomsDate.filter(F.action == "select"))
async def process_date_select(
    callback: CallbackQuery, 
    callback_data: FreeRoomsDate, 
    state: FSMContext,
    occupancy_service: OccupancyService
):
    target_date = date.fromisoformat(callback_data.date)
    await state.update_data(target_date=callback_data.date)
    data = await state.get_data()
    building = data.get('building')
    
    available_pairs = await occupancy_service.get_available_pairs(target_date, building)
    
    await callback.message.edit_text(
        f"🏢 Корпус <b>{building}</b>\n📅 Дата: <b>{target_date.strftime('%d.%m')}</b>\n\n🕒 <b>Выберите пару:</b>",
        reply_markup=get_available_pairs_kb(available_pairs)
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
async def process_pair_select(
    callback: CallbackQuery, 
    state: FSMContext, 
    occupancy_service: OccupancyService,
    analytics_repo: AnalyticsRepository
):
    pair_number = int(callback.data.split("_")[1])
    data = await state.get_data()
    building = data.get('building')
    target_date = date.fromisoformat(data['target_date'])
    
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
