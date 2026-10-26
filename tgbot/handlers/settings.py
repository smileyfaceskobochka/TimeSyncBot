from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from tgbot.database.repositories import UserRepository
from tgbot.keyboards.inline import get_user_settings_kb
from tgbot.keyboards.callback_data import SettingCb, DigestTimeCb, ReminderMinutesCb

settings_router = Router()


def _shift_time(hhmm: str, delta_minutes: int = 30) -> str:
    """Shift 'HH:MM' by ±delta, wrapping across midnight."""
    try:
        h, m = map(int, hhmm.split(":"))
    except (ValueError, AttributeError):
        h, m = 7, 30
    total = (h * 60 + m + delta_minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _shift_minutes(cur: int, delta: int = 5, lo: int = 0, hi: int = 60) -> int:
    return max(lo, min(hi, cur + delta))

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


@settings_router.callback_query(DigestTimeCb.filter())
async def change_digest_time(callback: CallbackQuery, callback_data: DigestTimeCb, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return await callback.answer("Пользователь не найден", show_alert=True)

    delta = -30 if callback_data.action == "minus" else 30
    user.settings.notify_daily_time = _shift_time(user.settings.notify_daily_time, delta)
    await user_repo.upsert_user(user)

    await callback.message.edit_reply_markup(reply_markup=get_user_settings_kb(user.settings))
    await callback.answer(f"Время дайджеста: {user.settings.notify_daily_time}")


@settings_router.callback_query(ReminderMinutesCb.filter())
async def change_reminder_minutes(callback: CallbackQuery, callback_data: ReminderMinutesCb, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        return await callback.answer("Пользователь не найден", show_alert=True)

    delta = -5 if callback_data.action == "minus" else 5
    user.settings.notify_before_minutes = _shift_minutes(user.settings.notify_before_minutes, delta)
    await user_repo.upsert_user(user)

    await callback.message.edit_reply_markup(reply_markup=get_user_settings_kb(user.settings))
    await callback.answer(f"Грань напоминания: {user.settings.notify_before_minutes} мин")
