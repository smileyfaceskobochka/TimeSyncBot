from aiogram.fsm.state import StatesGroup, State

class RegState(StatesGroup):
    search_group = State()

class FavState(StatesGroup):
    add_group = State()

class ScheduleState(StatesGroup):
    waiting_for_date = State()
    waiting_for_teacher = State()

class UserStates(StatesGroup):
    waiting_for_group = State()
    main_menu = State()

class MeetingState(StatesGroup):
    waiting_for_date = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
