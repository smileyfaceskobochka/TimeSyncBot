from typing import List
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgbot.database.models import User
from tgbot.database.repositories import UserRepository, ScheduleRepository, AnalyticsRepository
from tgbot.keyboards.inline import get_main_menu, get_schedule_hub_kb
from tgbot.keyboards.callback_data import GroupSelectCb, TeacherNav
from tgbot.services.services import ScheduleService
from tgbot.handlers.teacher import get_teacher_id, resolve_teacher

favorites_router = Router()

def get_favorites_combined_kb(groups: List[str], teachers: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.row(
            InlineKeyboardButton(text=f"📅 {group}", callback_data=GroupSelectCb(name=group, action="fav_select").pack()),
            InlineKeyboardButton(text="❌", callback_data=GroupSelectCb(name=group, action="fav_remove").pack())
        )
    for teacher in teachers:
        t_id = get_teacher_id(teacher)
        builder.row(
            InlineKeyboardButton(text=f"👨‍🏫 {teacher}", callback_data=TeacherNav(action="fav_open", target=t_id).pack()),
            InlineKeyboardButton(text="❌", callback_data=TeacherNav(action="fav_del", target=t_id).pack())
        )
    builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="search_start"))
    builder.row(InlineKeyboardButton(text="🎓 Найти преподавателя", callback_data=TeacherNav(action="start").pack()))
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    return builder.as_markup()

@favorites_router.message(Command("favorites", "fav"))
async def cmd_favorites(message: Message, user_repo: UserRepository):
    user = await user_repo.get_user(message.from_user.id)
    groups = user.favorites if user else []
    teachers = user.favorite_teachers if user else []
    
    if not groups and not teachers:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="search_start"))
        builder.row(InlineKeyboardButton(text="🎓 Найти преподавателя", callback_data=TeacherNav(action="start").pack()))
        builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
        await message.answer(
            "⭐ <b>Избранное</b>\n\n"
            "У вас пока нет сохранённых групп и преподавателей в избранном.\n\n"
            "Вы можете найти группу или преподавателя и добавить их сюда, чтобы быстро просматривать расписание!",
            reply_markup=builder.as_markup()
        )
        return

    await message.answer(
        "⭐ <b>Ваше избранное:</b>\n"
        "Нажмите для просмотра расписания или на ❌ для удаления:",
        reply_markup=get_favorites_combined_kb(groups, teachers)
    )

@favorites_router.callback_query(F.data == "fav_menu")
async def show_favorites(callback: CallbackQuery, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    groups = user.favorites if user else []
    teachers = user.favorite_teachers if user else []
    
    if not groups and not teachers:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="search_start"))
        builder.row(InlineKeyboardButton(text="🎓 Найти преподавателя", callback_data=TeacherNav(action="start").pack()))
        builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "У вас пока нет сохранённых групп и преподавателей в избранном.\n\n"
            "Вы можете найти группу или преподавателя и добавить их сюда, чтобы быстро просматривать расписание!",
            reply_markup=builder.as_markup()
        )
        return

    await callback.message.edit_text(
        "⭐ <b>Ваше избранное:</b>\n"
        "Нажмите для просмотра расписания или на ❌ для удаления:",
        reply_markup=get_favorites_combined_kb(groups, teachers)
    )
    await callback.answer()

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_add"))
async def add_to_favorites(
    callback: CallbackQuery, 
    callback_data: GroupSelectCb, 
    user_repo: UserRepository, 
    analytics_repo: AnalyticsRepository
):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return
    favorites = user.favorites
    group_name = callback_data.name
    
    if group_name not in favorites:
        favorites.append(group_name)
        user.favorites = favorites
        await user_repo.upsert_user(user)
        await analytics_repo.log_action(user.telegram_id, "add_favorite", group_name)
    
    await callback.answer(f"⭐ {group_name} добавлена в избранное!")
    
    is_my = bool(user.group_name == group_name)
    await callback.message.edit_reply_markup(
        reply_markup=get_schedule_hub_kb(group_name, is_favorite=True, is_my_group=is_my)
    )

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_remove_from_hub"))
async def remove_from_hub(
    callback: CallbackQuery, 
    callback_data: GroupSelectCb, 
    user_repo: UserRepository, 
    analytics_repo: AnalyticsRepository
):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return
    favorites = user.favorites
    group_name = callback_data.name
    
    if group_name in favorites:
        favorites.remove(group_name)
        user.favorites = favorites
        await user_repo.upsert_user(user)
        await analytics_repo.log_action(user.telegram_id, "remove_favorite", group_name)
    
    await callback.answer(f"❌ {group_name} удалена из избранного")
    
    is_my = bool(user.group_name == group_name)
    await callback.message.edit_reply_markup(
        reply_markup=get_schedule_hub_kb(group_name, is_favorite=False, is_my_group=is_my)
    )

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "set_as_my_group"))
async def set_as_my_group(
    callback: CallbackQuery, 
    callback_data: GroupSelectCb, 
    user_repo: UserRepository, 
    analytics_repo: AnalyticsRepository
):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return
    group_name = callback_data.name
    user.group_name = group_name
    await user_repo.upsert_user(user)
    await analytics_repo.log_action(user.telegram_id, "set_my_group", group_name)
    
    await callback.answer(f"📌 {group_name} установлена как ваша основная группа!", show_alert=True)
    
    is_fav = bool(group_name in user.favorites)
    await callback.message.edit_reply_markup(
        reply_markup=get_schedule_hub_kb(group_name, is_favorite=is_fav, is_my_group=True)
    )

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_remove"))
async def remove_from_favorites(callback: CallbackQuery, callback_data: GroupSelectCb, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return
    favorites = user.favorites
    group_name = callback_data.name
    
    if group_name in favorites:
        favorites.remove(group_name)
        user.favorites = favorites
        await user_repo.upsert_user(user)
    
    teachers = user.favorite_teachers
    if not favorites and not teachers:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="search_start"))
        builder.row(InlineKeyboardButton(text="🎓 Найти преподавателя", callback_data=TeacherNav(action="start").pack()))
        builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "Все элементы удалены из избранного.",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.edit_reply_markup(reply_markup=get_favorites_combined_kb(favorites, teachers))
    
    await callback.answer(f"❌ {group_name} удалена из избранного")

@favorites_router.callback_query(TeacherNav.filter(F.action == "fav_del"))
async def remove_teacher_from_favorites(
    callback: CallbackQuery, 
    callback_data: TeacherNav, 
    user_repo: UserRepository
):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return
    
    teacher_id = callback_data.target
    teacher_name = resolve_teacher(teacher_id, user)
    teachers = user.favorite_teachers
    deleted_name = "Преподаватель"

    if teacher_name and teacher_name in teachers:
        teachers.remove(teacher_name)
        deleted_name = teacher_name
        user.favorite_teachers = teachers
        await user_repo.upsert_user(user)
    else:
        for t in list(teachers):
            if get_teacher_id(t) == teacher_id:
                teachers.remove(t)
                deleted_name = t
                user.favorite_teachers = teachers
                await user_repo.upsert_user(user)
                break

    groups = user.favorites
    if not groups and not teachers:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Добавить группу", callback_data="search_start"))
        builder.row(InlineKeyboardButton(text="🎓 Найти преподавателя", callback_data=TeacherNav(action="start").pack()))
        builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "Все элементы удалены из избранного.",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.edit_reply_markup(reply_markup=get_favorites_combined_kb(groups, teachers))
        
    await callback.answer(f"❌ {deleted_name} удален из избранного")

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_select"))
async def select_from_favorites(
    callback: CallbackQuery, 
    callback_data: GroupSelectCb, 
    user_repo: UserRepository, 
    analytics_repo: AnalyticsRepository,
    schedule_repo: ScheduleRepository,
):
    user = await user_repo.get_user(callback.from_user.id)
    group_name = callback_data.name
    if user:
        await analytics_repo.log_action(user.telegram_id, "select_favorite", group_name)
    
    today = date.today()
    lessons, is_predicted = await schedule_repo.get_lessons_with_status(group_name, today)
    service = ScheduleService()
    settings = user.settings if user and user.settings else None
    is_fav = bool(user and group_name in user.favorites)
    is_my = bool(user and user.group_name == group_name)
    
    await callback.message.edit_text(
        service.format_day(lessons, today, group_name, settings, is_predicted=is_predicted),
        reply_markup=get_schedule_hub_kb(group_name, is_favorite=is_fav, is_my_group=is_my)
    )
    await callback.answer()
