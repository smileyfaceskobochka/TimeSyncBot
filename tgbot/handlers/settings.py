from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from tgbot.database.repositories import UserRepository
from tgbot.keyboards.inline import get_user_settings_kb
from tgbot.keyboards.callback_data import SettingCb

settings_router = Router()

@settings_router.callback_query(F.data == "settings_menu")
async def settings_menu(callback: CallbackQuery, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    await callback.message.edit_text(
        "⚙️ <b>Настройки отображения</b>\n\nЗдесь вы можете настроить, какие элементы расписания будут видны:",
        reply_markup=get_user_settings_kb(user.settings)
    )
    await callback.answer()

@settings_router.callback_query(SettingCb.filter())
async def toggle_setting(callback: CallbackQuery, callback_data: SettingCb, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    
    # Toggle the boolean value
    current_val = getattr(user.settings, callback_data.field)
    new_val = not current_val
    setattr(user.settings, callback_data.field, new_val)
    
    # Save to DB
    await user_repo.upsert_user(user)
    
    # Update keyboard
    await callback.message.edit_reply_markup(reply_markup=get_user_settings_kb(user.settings))
    await callback.answer("Настройка обновлена")
