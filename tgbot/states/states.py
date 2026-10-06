from aiogram.fsm.state import StatesGroup, State

class RegState(StatesGroup):
    search_group = State()

class ScheduleState(StatesGroup):
    waiting_for_date = State()
    waiting_for_teacher = State()

class MeetingState(StatesGroup):
    waiting_for_date = State()

class FeedbackState(StatesGroup):
    waiting_for_feedback = State()
    waiting_for_admin_reply = State()
