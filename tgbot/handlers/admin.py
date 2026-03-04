from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, BaseFilter
from tgbot.database.repositories import UserRepository
from tgbot.keyboards.inline import get_admin_menu_kb, get_bot_settings_kb
from tgbot.keyboards.callback_data import AdminCallback
from tgbot.config import config

class AdminFilter(BaseFilter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        return obj.from_user.id in config.ADMIN_IDS

admin_router = Router()
admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())

@admin_router.message(Command("admin"))
async def admin_start(message: Message):
    await message.answer("👑 <b>Панель администратора</b>", reply_markup=get_admin_menu_kb())

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
async def admin_sync_groups(callback: CallbackQuery):
    from tgbot.services.parser.site_to_pdf import sync_groups_list
    from tgbot.services.parser.progress import ProgressReporter
    
    progress = ProgressReporter(callback.message)
    await progress.report("⏳ Начало синхронизации списка групп...", 0.0)
    
    success = await sync_groups_list(progress=progress)
    
    if success:
        await callback.message.edit_text("✅ Список групп успешно обновлен!", reply_markup=get_admin_menu_kb())
    else:
        from tgbot.services.parser.site_to_pdf import check_website_status
        is_available, status_code, error_msg = await check_website_status()
        if not is_available:
            await callback.message.edit_text(
                f"🌐 Сайт ВятГУ недоступен ({error_msg}).\n"
                "Синхронизация невозможна. Попробуйте позже.",
                reply_markup=get_admin_menu_kb()
            )
        else:
            await callback.message.edit_text("❌ Ошибка при синхронизации.", reply_markup=get_admin_menu_kb())
    await callback.answer()
