from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from typing import List
import json

from tgbot.database.models import User
from tgbot.database.repositories import UserRepository, ScheduleRepository, AnalyticsRepository
from tgbot.keyboards.inline import get_main_menu, get_schedule_hub_kb
from tgbot.keyboards.callback_data import GroupSelectCb
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

favorites_router = Router()

def get_favorites_kb(favorites: List[str]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for group in favorites:
        builder.row(
            InlineKeyboardButton(text=f"📅 {group}", callback_data=GroupSelectCb(name=group, action="fav_select").pack()),
            InlineKeyboardButton(text="❌", callback_data=GroupSelectCb(name=group, action="fav_remove").pack())
        )
    builder.row(InlineKeyboardButton(text="« Главное меню", callback_data="cmd_start"))
    return builder

@favorites_router.callback_query(F.data == "fav_menu")
async def show_favorites(callback: CallbackQuery, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    favorites = user.favorites
    
    if not favorites:
        await callback.answer("⭐ У вас пока нет избранных групп. Добавьте их в меню расписания!", show_alert=True)
        return

    await callback.message.edit_text(
        "⭐ <b>Ваши избранные группы:</b>\nНажмите на группу, чтобы быстро переключиться на неё.",
        reply_markup=get_favorites_kb(favorites).as_markup()
    )
    await callback.answer()

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_add"))
async def add_to_favorites(callback: CallbackQuery, callback_data: GroupSelectCb, user_repo: UserRepository, analytics_repo: AnalyticsRepository):
    user = await user_repo.get_user(callback.from_user.id)
    favorites = user.favorites
    group_name = callback_data.name
    
    if group_name in favorites:
        await callback.answer("⭐ Группа уже есть в избранном!", show_alert=True)
        return
        
    favorites.append(group_name)
    user.favorites = favorites
    await user_repo.upsert_user(user)
    await analytics_repo.log_action(user.telegram_id, "add_favorite", group_name)
    
    await callback.answer(f"✅ {group_name} добавлена в избранное!")
    # Update current keyboard to hide "add to fav" button if it was there
    # But usually it's just a confirm snackbar. 
    # For better UX we could refresh the schedule hub kb.

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_remove"))
async def remove_from_favorites(callback: CallbackQuery, callback_data: GroupSelectCb, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    favorites = user.favorites
    group_name = callback_data.name
    
    if group_name in favorites:
        favorites.remove(group_name)
        user.favorites = favorites
        await user_repo.upsert_user(user)
    
    if not favorites:
        bot_settings = await user_repo.get_settings()
        await callback.message.edit_text("Главное меню", reply_markup=get_main_menu(user, bot_settings))
    else:
        await callback.message.edit_reply_markup(reply_markup=get_favorites_kb(favorites).as_markup())
    
    await callback.answer(f"❌ {group_name} удалена из избранного")

@favorites_router.callback_query(GroupSelectCb.filter(F.action == "fav_select"))
async def select_from_favorites(callback: CallbackQuery, callback_data: GroupSelectCb, user_repo: UserRepository, analytics_repo: AnalyticsRepository):
    user = await user_repo.get_user(callback.from_user.id)
    group_name = callback_data.name
    
    user.group_name = group_name
    await user_repo.upsert_user(user)
    await analytics_repo.log_action(user.telegram_id, "select_favorite", group_name)
    
    await callback.message.edit_text(
        f"📅 <b>Расписание для {group_name}</b>\nВыберите период:",
        reply_markup=get_schedule_hub_kb(group_name)
    )
    await callback.answer(f"🚀 Переключено на {group_name}")
