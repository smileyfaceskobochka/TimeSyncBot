from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, EphemeralMessageParameters
from aiogram.filters import Command
from tgbot.filters import AdminFilter
from tgbot.database.repositories import UserRepository, ParserSchedulerService
from tgbot.keyboards.inline import get_admin_menu_kb, get_bot_settings_kb
from tgbot.keyboards.callback_data import AdminCallback
from tgbot.config import config

admin_router = Router()
admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())

@admin_router.message(Command("admin"))
async def admin_start(message: Message):
    if message.chat.type in ("group", "supergroup"):
        # В групповых чатах отправляем эфемерно, чтобы не засорять чат и не раскрывать админку
        await message.bot.send_message(
            chat_id=message.chat.id,
            text="👑 <b>Панель администратора</b>",
            reply_markup=get_admin_menu_kb(),
            ephemeral_message_parameters=EphemeralMessageParameters(
                receiver_user_id=message.from_user.id
            )
        )
    else:
        await message.answer("👑 <b>Панель администратора</b>", reply_markup=get_admin_menu_kb())

@admin_router.message(Command("stop_bot"))
async def admin_stop_bot(message: Message):
    import os
    import signal
    await message.answer("🛑 <b>Бот выключается...</b>\nПроцесс на сервере будет остановлен.")
    # Send SIGTERM to own process to trigger graceful shutdown in main.py
    os.kill(os.getpid(), signal.SIGTERM)

@admin_router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery):
    await callback.message.edit_text("👑 <b>Панель администратора</b>", reply_markup=get_admin_menu_kb())
    await callback.answer()

@admin_router.callback_query(AdminCallback.filter(F.action == "sett"))
async def admin_settings(callback: CallbackQuery, user_repo: UserRepository):
    settings = await user_repo.get_settings()
    await callback.message.edit_text("⚙️ <b>Настройки кнопок меню</b>", reply_markup=get_bot_settings_kb(settings))
    await callback.answer()

@admin_router.callback_query(AdminCallback.filter(F.action == "btn_tog"))
async def admin_toggle_btn(callback: CallbackQuery, callback_data: AdminCallback, user_repo: UserRepository):
    settings = await user_repo.get_settings()
    current_val = settings.get(callback_data.value, '1')
    new_val = '0' if current_val == '1' else '1'
    
    await user_repo.update_setting(callback_data.value, new_val)
    settings[callback_data.value] = new_val
    
    await callback.message.edit_reply_markup(reply_markup=get_bot_settings_kb(settings))
    await callback.answer(f"Кнопка {'выключена' if new_val == '0' else 'включена'}")

@admin_router.callback_query(F.data == "admin_sync_groups")
async def admin_sync_groups(callback: CallbackQuery, parser_scheduler: ParserSchedulerService):
    await callback.message.edit_text("⏳ Запускаю синхронизацию расписания на сервере...", reply_markup=get_admin_menu_kb())
    try:
        ok = await parser_scheduler.sync_groups()
        if ok:
            await callback.message.edit_text("✅ Список групп и расписание успешно синхронизированы!", reply_markup=get_admin_menu_kb())
        else:
            await callback.message.edit_text("❌ Синхронизация не удалась. Попробуйте позже.", reply_markup=get_admin_menu_kb())
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка синхронизации: <code>{e}</code>", reply_markup=get_admin_menu_kb())
    await callback.answer()

@admin_router.callback_query(F.data == "admin_sync_occupancy")
async def admin_sync_occupancy(callback: CallbackQuery, parser_scheduler: ParserSchedulerService):
    await callback.message.edit_text("⏳ Запускаю обновление занятости аудиторий на сервере...", reply_markup=get_admin_menu_kb())
    try:
        ok = await parser_scheduler.sync_occupancy()
        await callback.message.edit_text("✅ Занятость аудиторий успешно обновлена!", reply_markup=get_admin_menu_kb())
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка при обновлении занятости: {e}", reply_markup=get_admin_menu_kb())
    await callback.answer()
