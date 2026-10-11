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
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
        
    current_val = getattr(user.settings, callback_data.field, False)
    new_val = not current_val

    # Если пользователь пытается включить рассылку или алерты, но не выбрал группу
    if new_val and callback_data.field in ("notify_daily", "notify_before_lesson") and not user.group_name:
        await callback.answer("⚠️ Сначала привяжите учебную группу через поиск!", show_alert=True)
        return

    setattr(user.settings, callback_data.field, new_val)
    
    # Save to DB
    await user_repo.upsert_user(user)
    
    # Update keyboard
    await callback.message.edit_reply_markup(reply_markup=get_user_settings_kb(user.settings))
    status_text = "включено" if new_val else "выключено"
    await callback.answer(f"Настройка обновлена: {status_text}")
