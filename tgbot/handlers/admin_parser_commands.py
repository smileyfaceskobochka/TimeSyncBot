"""
Админ-команды для управления планировщиком парсера.

Все операции парсинга/синхронизации проксируются через HTTP на сервер
(core service); клиент бота не трогает парсер напрямую.
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, EphemeralMessageParameters
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from tgbot.filters import AdminFilter
from tgbot.database.repositories import ParserSchedulerService

admin_parser_router = Router()
admin_parser_router.message.filter(AdminFilter())
admin_parser_router.callback_query.filter(AdminFilter())


@admin_parser_router.message(Command("parser_status"))
async def cmd_parser_status(message: Message, parser_scheduler: ParserSchedulerService):
    """
    Показывает детальный статус планировщика парсера.
    Использование: /parser_status
    """
    status = parser_scheduler.get_status()

    text = "🤖 <b>Статус парсера расписаний</b>\n\n"

    if status['running']:
        text += "▫️ Планировщик: <b>✅ Работает</b>\n"
    else:
        text += "▫️ Планировщик: <b>❌ Остановлен</b>"

    if status['last_run']:
        last_run = status['last_run']
        if isinstance(last_run, str):
            last_run = datetime.fromisoformat(last_run)
        time_str = last_run.strftime('%d.%m.%Y %H:%M:%S')
        text += f"▫️ Последний запуск: {time_str}\n"

        if status['last_status'] == 'success':
            text += "▫️ Результат: <b>✅ Успешно</b>\n"
        else:
            text += "▫️ Результат: <b>❌ Ошибка</b>"
    else:
        text += "▫️ Последний запуск: <i>Нет данных</i>"

    stats = status['stats']
    text += f"\n📊 <b>Статистика за всё время:</b>\n"
    text += f"▫️ Всего запусков: <code>{stats['total_runs']}</code>\n"
    text += f"▫️ Успешных: <code>{stats['successful_runs']}</code>\n"
    text += f"▫️ Ошибок: <code>{stats['failed_runs']}</code>\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="parser_status_refresh")
    builder.button(text="▶️ Запустить сейчас", callback_data="parser_run_now")
    builder.adjust(2)

    if message.chat.type in ("group", "supergroup"):
        await message.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=builder.as_markup(),
            ephemeral_message_parameters=EphemeralMessageParameters(
                receiver_user_id=message.from_user.id
            )
        )
    else:
        await message.answer(text, reply_markup=builder.as_markup())


@admin_parser_router.callback_query(F.data == "parser_status_refresh")
async def callback_parser_status_refresh(callback: CallbackQuery, parser_scheduler: ParserSchedulerService):
    status = parser_scheduler.get_status()

    text = "🤖 <b>Статус парсера расписаний</b>\n\n"

    if status['running']:
        text += "▫️ Планировщик: <b>✅ Работает</b>\n"
    else:
        text += "▫️ Планировщик: <b>❌ Остановлен</b>"

    if status['last_run']:
        last_run = status['last_run']
        if isinstance(last_run, str):
            last_run = datetime.fromisoformat(last_run)
        time_str = last_run.strftime('%d.%m.%Y %H:%M:%S')
        text += f"▫️ Последний запуск: {time_str}\n"

        if status['last_status'] == 'success':
            text += "▫️ Результат: <b>✅ Успешно</b>\n"
        else:
            text += "▫️ Результат: <b>❌ Ошибка</b>"
    else:
        text += "▫️ Последний запуск: <i>Нет данных</i>"

    stats = status['stats']
    text += f"\n📊 <b>Статистика за всё время:</b>\n"
    text += f"▫️ Всего запусков: <code>{stats['total_runs']}</code>\n"
    text += f"▫️ Успешных: <code>{stats['successful_runs']}</code>\n"
    text += f"▫️ Ошибок: <code>{stats['failed_runs']}</code>\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="parser_status_refresh")
    builder.button(text="▶️ Запустить сейчас", callback_data="parser_run_now")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer("✅ Обновлено")


@admin_parser_router.callback_query(F.data == "parser_run_now")
async def callback_parser_run_now(callback: CallbackQuery, parser_scheduler: ParserSchedulerService):
    await callback.answer("⏳ Запускаю парсер...", show_alert=True)

    import asyncio
    asyncio.create_task(parser_scheduler.run_parser_process())

    await callback.message.answer(
        "▶️ Парсер запущен!\n\n"
        "Проверьте логи сервера для отслеживания прогресса.\n"
        "Используйте /parser_status через минуту для проверки результата."
    )


@admin_parser_router.message(Command("parser_run"))
async def cmd_parser_run(message: Message, parser_scheduler: ParserSchedulerService):
    """Принудительно запускает парсер прямо сейчас."""
    await message.answer("⏳ Запускаю парсер расписаний...")

    try:
        await parser_scheduler.run_parser_process()

        status = parser_scheduler.get_status()

        if status['last_status'] == 'success':
            await message.answer(
                "✅ <b>Парсер выполнен успешно!</b>\n\n"
                "Расписание обновлено. Используйте /parser_status для просмотра статистики."
            )
        else:
            await message.answer(
                "❌ <b>Парсер завершился с ошибкой</b>\n\n"
                "Проверьте логи сервера для диагностики проблемы."
            )
    except Exception as e:
        await message.answer(
            f"❌ <b>Ошибка при запуске парсера:</b>\n\n"
            f"<code>{str(e)}</code>\n\n"
            "Проверьте логи сервера."
        )


@admin_parser_router.message(Command("parser_logs"))
async def cmd_parser_logs(message: Message, parser_scheduler: ParserSchedulerService):
    """Показывает последние строки из лог-файла парсера (с сервера)."""
    args = message.text.split()
    lines_count = 20

    if len(args) > 1:
        try:
            lines_count = int(args[1])
            lines_count = min(max(lines_count, 5), 100)
        except ValueError:
            pass

    try:
        text = await parser_scheduler.get_parser_logs(tail=lines_count) or ""
        parser_lines = [
            line for line in text.splitlines()
            if 'парсер' in line.lower() or 'parser' in line.lower()
        ]

        if parser_lines:
            body = f"📄 <b>Последние {len(parser_lines)} записей парсера:</b>\n\n"
            body += "<code>" + "".join(parser_lines[-20:]) + "</code>"
        else:
            body = f"📄 Записей о парсере не найдено в последних {lines_count} строках."

        if len(body) > 4000:
            body = body[:3950] + "\n\n... (обрезано)</code>"

        await message.answer(body)
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения логов: <code>{str(e)}</code>")


@admin_parser_router.message(Command("sync_teachers"))
async def cmd_sync_teachers(message: Message, parser_scheduler: ParserSchedulerService):
    """Принудительная синхронизация карты преподавателей ВятГУ (через сервер)."""
    await message.answer("🔄 Запускаю синхронизацию преподавателей на сервере...")
    try:
        ok = await parser_scheduler.sync_teachers()
        if ok:
            await message.answer("✅ Преподаватели успешно обновлены на сервере!")
        else:
            await message.answer("❌ Не удалось обновить список преподавателей. Проверьте логи сервера.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при синхронизации преподавателей: {e}")


@admin_parser_router.message(Command("sync_occupancy"))
async def cmd_sync_occupancy(message: Message, parser_scheduler: ParserSchedulerService):
    """Принудительная синхронизация занятости аудиторий (через сервер)."""
    await message.answer("🔄 Запускаю синхронизацию занятости аудиторий на сервере...")
    try:
        ok = await parser_scheduler.sync_occupancy()
        if ok:
            await message.answer("✅ Занятость аудиторий успешно обновлена!")
        else:
            await message.answer("❌ Не удалось обновить занятость аудиторий. Проверьте логи сервера.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при обновлении занятости: {e}")


@admin_parser_router.message(Command("parser_help"))
async def cmd_parser_help(message: Message):
    """Справка по командам парсера"""
    text = (
        "🤖 <b>Команды управления парсером</b>\n\n"

        "<b>/parser_status</b>\n"
        "Показывает текущий статус планировщика, последний запуск и статистику.\n\n"

        "<b>/parser_run</b>\n"
        "Принудительно запускает парсер прямо сейчас (внеплановое обновление).\n\n"

        "<b>/parser_logs [N]</b>\n"
        "Показывает последние N строк из логов парсера (по умолчанию 20).\n\n"

        "<b>/sync_teachers</b>\n"
        "Обновляет список преподавателей ВятГУ.\n\n"

        "<b>/sync_occupancy</b>\n"
        "Обновляет данные о занятости аудиторий.\n\n"

        "<b>/parser_help</b>\n"
        "Эта справка."
    )

    await message.answer(text)
