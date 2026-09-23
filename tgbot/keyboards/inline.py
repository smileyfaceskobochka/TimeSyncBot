from datetime import date, timedelta
from typing import List, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from tgbot.database.models import User, UserSettings, GroupChat
from tgbot.config import config
from tgbot.keyboards.callback_data import GroupSelectCb, ScheduleNav, SettingCb, AdminCallback, FreeRoomsDate, MeetingCb, TeacherNav, GroupChatCb, FeedbackCb
def is_admin(user_id: int) -> bool: return user_id in config.ADMIN_IDS
def get_week_calendar_kb(group: str, base_date: date = None) -> InlineKeyboardMarkup:
    if base_date is None:
        base_date = date.today()
    builder = InlineKeyboardBuilder()
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    
    for i in range(7):
        day = base_date + timedelta(days=i)
        day_str = day.strftime('%d.%m')
        label = f"{day_str} ({weekdays[day.weekday()]})"
        callback = ScheduleNav(
            action="show_date", 
            current_date=day.isoformat(), 
            group=group
        ).pack()
        builder.button(text=label, callback_data=callback)
    
    builder.adjust(2)  
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=ScheduleNav(action="today", current_date=base_date.isoformat(), group=group).pack()))
    return builder.as_markup()


def get_free_rooms_date_kb() -> InlineKeyboardMarkup:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    after_tomorrow = today + timedelta(days=2)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Сегодня", 
            callback_data=FreeRoomsDate(action="select", date=today.isoformat()).pack()
        ),
        InlineKeyboardButton(
            text="Завтра", 
            callback_data=FreeRoomsDate(action="select", date=tomorrow.isoformat()).pack()
        ),
        InlineKeyboardButton(
            text="Послезавтра", 
            callback_data=FreeRoomsDate(action="select", date=after_tomorrow.isoformat()).pack()
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📅 Выбрать дату", 
            callback_data=FreeRoomsDate(action="custom").pack()
        )
    )
    builder.row(
        InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start")
    )
    return builder.as_markup()


def get_free_rooms_calendar_kb(base_date: date = None) -> InlineKeyboardMarkup:
    if base_date is None:
        base_date = date.today()
    builder = InlineKeyboardBuilder()
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    
    for i in range(7):
        day = base_date + timedelta(days=i)
        day_str = day.strftime('%d.%m')
        label = f"{day_str} ({weekdays[day.weekday()]})"
        callback = FreeRoomsDate(action="select", date=day.isoformat()).pack()
        builder.button(text=label, callback_data=callback)
    
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="free_rooms_start"))
    return builder.as_markup()
def get_group_selection_kb(
    groups: list[str],
    action: str,
    selected_groups: list[str] = None,
    page: int = 1,
    per_page: int = 8,
) -> InlineKeyboardMarkup:
    if selected_groups is None: selected_groups = []
    builder = InlineKeyboardBuilder()
    
    total_pages = max(1, (len(groups) + per_page - 1) // per_page)
    current_page = max(1, min(page, total_pages))
    
    start_idx = (current_page - 1) * per_page
    end_idx = start_idx + per_page
    page_groups = groups[start_idx:end_idx]
    
    # If we are in parse_ondemand mode, we support multi-select toggling
    is_multi = action == "parse_ondemand" or action == "toggle_parse"
    
    for group in page_groups:
        btn_text = group
        btn_action = action
        
        if is_multi:
            status = "✅ " if group in selected_groups else ""
            btn_text = f"{status}{group}"
            btn_action = "toggle_parse"
            
        builder.button(
            text=btn_text, 
            callback_data=GroupSelectCb(name=group, action=btn_action, page=current_page).pack()
        )
    
    builder.adjust(2)
    
    # Pagination navigation controls
    if total_pages > 1:
        nav_buttons = []
        if current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=GroupSelectCb(name="NAV", action="page", page=current_page - 1).pack()
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page}/{total_pages}",
                callback_data="noop"
            )
        )
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=GroupSelectCb(name="NAV", action="page", page=current_page + 1).pack()
                )
            )
        builder.row(*nav_buttons)
        
    if is_multi and selected_groups:
        builder.row(InlineKeyboardButton(text="🚀 Загрузить выбранные", callback_data=GroupSelectCb(name="CONFIRM", action="confirm_parse").pack()))
        
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cmd_start"))
    return builder.as_markup()

def get_main_menu(user: User, bot_settings: dict = None) -> InlineKeyboardMarkup:
    if bot_settings is None: bot_settings = {}
    buttons = []
    
    if bot_settings.get('btn_schedule', '1') == '1':
        buttons.append([InlineKeyboardButton(text="📅 Моё расписание", callback_data="my_schedule")])

    if bot_settings.get('btn_search', '1') == '1':
        buttons.append([InlineKeyboardButton(text="🔎 Поиск группы", callback_data="search_start")])

    if bot_settings.get('btn_free_rooms', '1') == '1':
        buttons.append([InlineKeyboardButton(text="🔍 Свободные аудитории", callback_data="free_rooms_start")])
    
    buttons.append([InlineKeyboardButton(text="🤝 Общие окна (Встречи)", callback_data="meet_start")])
    buttons.append([InlineKeyboardButton(text="🎓 Поиск преподавателя", callback_data=TeacherNav(action="start").pack())])
    
    row2 = []
    if bot_settings.get('btn_favorites', '1') == '1':
        row2.append(InlineKeyboardButton(text="⭐ Избранное", callback_data="fav_menu"))
    if bot_settings.get('btn_settings', '1') == '1':
        row2.append(InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_menu"))
    if row2: buttons.append(row2)
    
    buttons.append([InlineKeyboardButton(text="✍️ Отзывы и предложения", callback_data="feedback_start")])
    buttons.append([InlineKeyboardButton(text="❓ Помощь", callback_data="cmd_help")])
    if user and is_admin(user.telegram_id):
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_schedule_hub_kb(
    group_name: str, 
    is_favorite: bool = False, 
    is_my_group: bool = False
) -> InlineKeyboardMarkup:
    today = date.today()
    tmrw = today + timedelta(days=1)
    after_tmrw = today + timedelta(days=2)

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="Сегодня", callback_data=ScheduleNav(action="day", current_date=today.isoformat(), group=group_name).pack()),
        InlineKeyboardButton(text="Завтра", callback_data=ScheduleNav(action="day", current_date=tmrw.isoformat(), group=group_name).pack()),
        InlineKeyboardButton(text="Послезавтра", callback_data=ScheduleNav(action="day", current_date=after_tmrw.isoformat(), group=group_name).pack())
    )

    this_monday = today - timedelta(days=today.weekday())
    week_buttons = []
    for i in range(4):
        mon = this_monday + timedelta(days=i*7)
        sun = mon + timedelta(days=6)
        text = f"{mon.strftime('%d.%m')} - {sun.strftime('%d.%m')} | Неделя"
        week_buttons.append(InlineKeyboardButton(text=text, callback_data=ScheduleNav(action="week", current_date=mon.isoformat(), group=group_name).pack()))

    builder.row(week_buttons[0], week_buttons[1])
    builder.row(week_buttons[2], week_buttons[3])

    builder.row(InlineKeyboardButton(text="📅 Календарь на неделю", callback_data=ScheduleNav(action="custom_day", current_date=today.isoformat(), group=group_name).pack()))

    action_btns = []
    if is_favorite:
        action_btns.append(InlineKeyboardButton(text="⭐ В избранном ❌", callback_data=GroupSelectCb(name=group_name, action="fav_remove_from_hub").pack()))
    else:
        action_btns.append(InlineKeyboardButton(text="☆ В избранное", callback_data=GroupSelectCb(name=group_name, action="fav_add").pack()))
    
    if not is_my_group:
        action_btns.append(InlineKeyboardButton(text="📌 Сделать моей", callback_data=GroupSelectCb(name=group_name, action="set_as_my_group").pack()))

    if action_btns:
        builder.row(*action_btns)

    builder.row(
        InlineKeyboardButton(text="🔍 Другая группа", callback_data="search_start"),
        InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start")
    )
    return builder.as_markup()

def get_user_settings_kb(settings: UserSettings) -> InlineKeyboardMarkup:
    def btn(text, field):
        status = "✅" if getattr(settings, field) else "❌"
        return InlineKeyboardButton(text=f"{text}: {status}", callback_data=SettingCb(field=field).pack())

    rows = [
        [btn("Показывать преподавателей", "show_teachers")],
        [btn("Показывать аудитории", "show_building")],
        [btn("Показывать окна (своб. время)", "show_windows")],
        [InlineKeyboardButton(text="🔎 Сменить группу", callback_data="search_start")],
        [InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
def get_meeting_all_groups_kb(all_groups: list[str], selected_groups: list[str], page: int = 0) -> InlineKeyboardMarkup:
    """Постраничная клавиатура со списком всех групп"""
    ITEMS_PER_PAGE = 24 # Количество кнопок на 1 страницу (кратно 3)
    builder = InlineKeyboardBuilder()
    
    # Если выбрано 2 и более групп - показываем кнопку перехода к датам
    if len(selected_groups) >= 2:
        builder.row(InlineKeyboardButton(text="➡️ Выбрать дату", callback_data=MeetingCb(action="pick_date").pack()))

    # Вычисляем срез групп для текущей страницы
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_page_groups = all_groups[start_idx:end_idx]

    # Добавляем кнопки групп
    group_btns = []
    for g in current_page_groups:
        # Если группа выбрана, ставим галочку
        text = f"✅ {g}" if g in selected_groups else g
        group_btns.append(InlineKeyboardButton(text=text, callback_data=MeetingCb(action="toggle", value=g).pack()))
    
    # Группируем по 3 в ряд
    builder.row(*group_btns, width=3)
    
    # Кнопки навигации (пагинация)
    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=MeetingCb(action="page", value=str(page-1)).pack()))
    if end_idx < len(all_groups):
        nav_btns.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=MeetingCb(action="page", value=str(page+1)).pack()))
    
    if nav_btns:
        builder.row(*nav_btns)
        
    builder.row(InlineKeyboardButton(text="« В главное меню", callback_data="cmd_start"))
    return builder.as_markup()

def get_meeting_date_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора даты для встречи"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    after_tomorrow = today + timedelta(days=2)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Сегодня", callback_data=MeetingCb(action="date", value=today.isoformat()).pack()),
        InlineKeyboardButton(text="Завтра", callback_data=MeetingCb(action="date", value=tomorrow.isoformat()).pack()),
        InlineKeyboardButton(text="Послезавтра", callback_data=MeetingCb(action="date", value=after_tomorrow.isoformat()).pack())
    )
    builder.row(InlineKeyboardButton(text="📅 Ввести дату вручную", callback_data=MeetingCb(action="manual_date").pack()))
    builder.row(InlineKeyboardButton(text="« Назад к списку групп", callback_data=MeetingCb(action="back_to_groups").pack()))
    return builder.as_markup()

def get_back_to_dates_kb() -> InlineKeyboardMarkup:
    """Клавиатура для возврата из результата обратно в даты"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« К выбору даты", callback_data=MeetingCb(action="pick_date").pack()))
    builder.row(InlineKeyboardButton(text="« В главное меню", callback_data="cmd_start"))
    return builder.as_markup()
def get_pair_selection_kb() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=f"{p}-я пара", callback_data=f"pair_{p}")] for p in range(1, 8)]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data="free_rooms_start")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_building_selection_kb(buildings: List[str]) -> InlineKeyboardMarkup:
    # Sort buildings: numbers first, then text
    try:
        sorted_b = sorted(buildings, key=lambda x: int(x) if x.isdigit() else 999)
    except:
        sorted_b = sorted(buildings)
        
    buttons = [[InlineKeyboardButton(text=f"🏢 Корпус {b}", callback_data=f"building_{b}")] for b in sorted_b]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data="cmd_start")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_available_pairs_kb(available_pairs: List[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Always check 1-7
    for p in range(1, 8):
        if p in available_pairs:
            time_start = config.STANDARD_PAIR_STARTS.get(p, "??:??")
            builder.button(text=f"{p} пара ({time_start})", callback_data=f"pair_{p}")
    
    if not available_pairs:
        builder.button(text="❌ Нет свободных пар", callback_data="noop")
        
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="free_rooms_start"))
    return builder.as_markup()

def get_admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Синхронизировать список групп", callback_data="admin_sync_groups")],
        [InlineKeyboardButton(text="🏢 Обновить занятость", callback_data="admin_sync_occupancy")],
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data=AdminCallback(action="sett").pack())],
        [InlineKeyboardButton(text="« Меню", callback_data="cmd_start")]
    ])
def get_meeting_groups_kb(added_groups: list[str]) -> InlineKeyboardMarkup:
    """Клавиатура управления списком групп для общих окон"""
    builder = InlineKeyboardBuilder()
    
    # Кнопка добавления группы
    builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data=MeetingCb(action="add_btn").pack()))
    
    # Если добавлено хотя бы 2 группы, показываем кнопку "Далее (Выбрать дату)"
    if len(added_groups) >= 2:
        builder.row(InlineKeyboardButton(text="➡️ Выбрать дату", callback_data=MeetingCb(action="pick_date").pack()))
    
    # Кнопки для удаления добавленных групп (если ошиблись)
    if added_groups:
        for grp in added_groups:
            builder.row(InlineKeyboardButton(text=f"❌ Удалить {grp}", callback_data=MeetingCb(action="del", value=grp).pack()))
            
    # Кнопка выхода
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    return builder.as_markup()
def get_bot_settings_kb(settings: dict) -> InlineKeyboardMarkup:
    def status_icon(value: str) -> str: return "🟢" if value == '1' else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Видимость кнопок:", callback_data="noop")],
        [InlineKeyboardButton(text=f"{status_icon(settings.get('btn_schedule', '1'))} Расписание", callback_data=AdminCallback(action="btn_tog", value="btn_schedule").pack())],
        [InlineKeyboardButton(text=f"{status_icon(settings.get('btn_search', '1'))} Сменить группу", callback_data=AdminCallback(action="btn_tog", value="btn_search").pack())],
        [InlineKeyboardButton(text=f"{status_icon(settings.get('btn_favorites', '1'))} Избранное", callback_data=AdminCallback(action="btn_tog", value="btn_favorites").pack())],
        [InlineKeyboardButton(text=f"{status_icon(settings.get('btn_settings', '1'))} Настройки", callback_data=AdminCallback(action="btn_tog", value="btn_settings").pack())],
        [InlineKeyboardButton(text=f"{status_icon(settings.get('btn_free_rooms', '1'))} Свободные аудитории", callback_data=AdminCallback(action="btn_tog", value="btn_free_rooms").pack())],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")]
    ])

def get_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]])
def get_teacher_institutes_kb(institutes: List[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, inst in enumerate(institutes):
        builder.button(
            text=inst["name"],
            callback_data=TeacherNav(action="select_inst", target=str(idx)).pack()
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="cmd_start"))
    return builder.as_markup()

def get_teacher_faculties_kb(faculties: List[dict], inst_idx: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, fac in enumerate(faculties):
        builder.button(
            text=fac["name"],
            callback_data=TeacherNav(action="select_fac", target=str(idx), inst=str(inst_idx)).pack()
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=TeacherNav(action="start").pack()))
    return builder.as_markup()

def get_teacher_departments_kb(departments: List[dict], inst_idx: int, fac_idx: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, dept in enumerate(departments):
        builder.button(
            text=dept["name"],
            callback_data=TeacherNav(action="select_dept", target=str(idx), inst=str(inst_idx), fac=str(fac_idx)).pack()
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=TeacherNav(action="select_inst", target=str(inst_idx)).pack()))
    return builder.as_markup()

def get_teachers_selection_kb(teachers: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, t in enumerate(teachers):
        builder.button(
            text=f"👨‍🏫 {t}",
            callback_data=TeacherNav(action="view", target=str(idx)).pack()
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔍 Искать снова", callback_data=TeacherNav(action="start").pack()))
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    return builder.as_markup()

def get_teacher_schedule_kb(teacher_id: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if teacher_id:
        today_iso = date.today().isoformat()
        builder.button(text="« К выбору дня", callback_data=TeacherNav(action="day", target=teacher_id, date_val=today_iso).pack())
    builder.button(text="🔍 Искать другого преподавателя", callback_data=TeacherNav(action="start").pack())
    builder.button(text="« Главное меню", callback_data="cmd_start")
    builder.adjust(1)
    return builder.as_markup()

def get_teacher_schedule_hub_kb(teacher_id: str, current_date: date, is_favorite: bool = False) -> InlineKeyboardMarkup:
    today = date.today()
    tmrw = today + timedelta(days=1)
    after_tmrw = today + timedelta(days=2)

    builder = InlineKeyboardBuilder()

    # Быстрые кнопки: Сегодня, Завтра, Послезавтра
    builder.row(
        InlineKeyboardButton(
            text="Сегодня",
            callback_data=TeacherNav(action="day", target=teacher_id, date_val=today.isoformat()).pack()
        ),
        InlineKeyboardButton(
            text="Завтра",
            callback_data=TeacherNav(action="day", target=teacher_id, date_val=tmrw.isoformat()).pack()
        ),
        InlineKeyboardButton(
            text="Послезавтра",
            callback_data=TeacherNav(action="day", target=teacher_id, date_val=after_tmrw.isoformat()).pack()
        )
    )

    # Неделя и Календарь
    builder.row(
        InlineKeyboardButton(
            text="📆 Вся неделя",
            callback_data=TeacherNav(action="week", target=teacher_id, date_val=today.isoformat()).pack()
        ),
        InlineKeyboardButton(
            text="📅 Календарь на неделю",
            callback_data=TeacherNav(action="cal", target=teacher_id, date_val=today.isoformat()).pack()
        )
    )

    # Избранное
    fav_text = "⭐ В избранном ❌" if is_favorite else "☆ В избранное"
    builder.row(
        InlineKeyboardButton(
            text=fav_text,
            callback_data=TeacherNav(action="fav_toggle", target=teacher_id, date_val=current_date.isoformat()).pack()
        )
    )

    # Другой преподаватель и Меню
    builder.row(
        InlineKeyboardButton(text="🔍 Другой преподаватель", callback_data=TeacherNav(action="start").pack()),
        InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start")
    )
    return builder.as_markup()

def get_teacher_calendar_kb(teacher_id: str, current_date: date) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    monday = current_date - timedelta(days=current_date.weekday())
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]

    buttons = []
    for i in range(6):
        d = monday + timedelta(days=i)
        buttons.append(
            InlineKeyboardButton(
                text=f"{day_names[i]} {d.strftime('%d.%m')}",
                callback_data=TeacherNav(action="day", target=teacher_id, date_val=d.isoformat()).pack()
            )
        )
    builder.row(buttons[0], buttons[1], buttons[2])
    builder.row(buttons[3], buttons[4], buttons[5])
    builder.row(
        InlineKeyboardButton(
            text="« Назад к расписанию",
            callback_data=TeacherNav(action="day", target=teacher_id, date_val=current_date.isoformat()).pack()
        )
    )
    return builder.as_markup()

def get_group_chat_settings_kb(chat: GroupChat, is_supergroup: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    auto_icon = "✅ Вкл" if chat.auto_post else "❌ Выкл"
    builder.row(InlineKeyboardButton(text=f"Авторассылка: {auto_icon}", callback_data=GroupChatCb(action="toggle_auto").pack()))
    
    builder.row(InlineKeyboardButton(text=f"⏰ Время рассылки: {chat.post_time}", callback_data=GroupChatCb(action="cycle_time").pack()))
    
    target_str = "на сегодня" if chat.post_target == "today" else "на завтра"
    builder.row(InlineKeyboardButton(text=f"🎯 Отправлять: {target_str}", callback_data=GroupChatCb(action="toggle_target").pack()))
    
    pin_icon = "✅ Да" if chat.pin_message else "❌ Нет"
    builder.row(InlineKeyboardButton(text=f"📌 Закреплять рассылку: {pin_icon}", callback_data=GroupChatCb(action="toggle_pin").pack()))
    
    if is_supergroup:
        topic_title = f"#{chat.topic_id}" if chat.topic_id else "Основной чат"
        builder.row(InlineKeyboardButton(text=f"💬 Тема (топик): {topic_title}", callback_data=GroupChatCb(action="toggle_topic").pack()))
        
        pin_rep_icon = "✅ Да" if getattr(chat, 'pin_replies', False) else "❌ Нет"
        builder.row(InlineKeyboardButton(text=f"📌 Закреплять ответы /today: {pin_rep_icon}", callback_data=GroupChatCb(action="toggle_pin_replies").pack()))
    
    builder.row(
        InlineKeyboardButton(text="📅 Отправить расписание сейчас", callback_data=GroupChatCb(action="send_now").pack())
    )
    builder.row(
        InlineKeyboardButton(text="❌ Закрыть настройки", callback_data=GroupChatCb(action="close").pack())
    )
    return builder.as_markup()


def get_feedback_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="« Отмена", callback_data="cmd_start")
    return builder.as_markup()


def get_feedback_admin_kb(user_id: int, username: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=FeedbackCb(action="reply", user_id=user_id).pack())
    if username:
        builder.button(text="👤 Профиль", url=f"https://t.me/{username}")
    builder.adjust(2)
    return builder.as_markup()

