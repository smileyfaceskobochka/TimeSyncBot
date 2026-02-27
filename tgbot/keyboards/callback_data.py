from aiogram.filters.callback_data import CallbackData

class GroupSelectCb(CallbackData, prefix="sel_grp"):
    name: str
    action: str

class ScheduleNav(CallbackData, prefix="nav"):
    action: str
    current_date: str
    group: str

class SettingCb(CallbackData, prefix="set"):
    field: str

class MeetingCb(CallbackData, prefix="meet"):
    action: str
    value: str = ""
    
class AdminCallback(CallbackData, prefix="adm"):
    action: str
    value: str = ""

class MenuCallback(CallbackData, prefix="menu"):
    action: str

class FreeRoomsDate(CallbackData, prefix="fr_date"):
    action: str
    date: str = ""