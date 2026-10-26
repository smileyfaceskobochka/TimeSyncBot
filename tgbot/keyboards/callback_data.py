from aiogram.filters.callback_data import CallbackData

class GroupSelectCb(CallbackData, prefix="sel_grp"):
    name: str
    action: str
    page: int = 1

class ScheduleNav(CallbackData, prefix="nav"):
    action: str
    current_date: str
    group: str

class SettingCb(CallbackData, prefix="set"):
    field: str

class DigestTimeCb(CallbackData, prefix="digest_t"):
    action: str  # "minus" | "plus"

class ReminderMinutesCb(CallbackData, prefix="remind_m"):
    action: str  # "minus" | "plus"

class MeetingCb(CallbackData, prefix="meet"):
    action: str
    value: str = ""
    
class AdminCallback(CallbackData, prefix="adm"):
    action: str
    value: str = ""

class FreeRoomsDate(CallbackData, prefix="fr_date"):
    action: str
    date: str = ""

class TeacherNav(CallbackData, prefix="teach"):
    action: str
    target: str = ""    # Name or short ID
    date_val: str = ""  # Date (YYYY-MM-DD)
    fac: str = ""       # Faculty index/id
    inst: str = ""      # Institute index/id

class GroupChatCb(CallbackData, prefix="grp_chat"):
    action: str
    value: str = ""


class FeedbackCb(CallbackData, prefix="fb"):
    action: str
    user_id: int = 0