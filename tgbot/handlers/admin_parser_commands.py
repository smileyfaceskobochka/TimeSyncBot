"""
Админ-команды для управления планировщиком парсера.

Добавьте этот код в tgbot/handlers/admin.py или создайте новый файл.
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from tgbot.services.parser.occupancy_parser import update_occupancy
from tgbot.database.repositories import DatabaseManager
from tgbot.config import config

admin_parser_router = Router()


@admin_parser_router.message(Command("parser_status"))
async def cmd_parser_status(message: Message, parser_scheduler):
    """
    Показывает детальный статус планировщика парсера.
    Использование: /parser_status
    """
    status = parser_scheduler.get_status()
    
    # Формируем текст
    text = "🤖 <b>Статус парсера расписаний</b>\n\n"
    
    # Статус работы
    if status['running']:
        text += "▫️ Планировщик: <b>✅ Работает</b>\n"
    else:
        text += "▫️ Планировщик: <b>❌ Остановлен</b>\n"
    
    # Последний запуск
    if status['last_run']:
        time_str = status['last_run'].strftime('%d.%m.%Y %H:%M:%S')
        text += f"▫️ Последний запуск: {time_str}\n"
        
        # Статус последнего запуска с эмодзи
        if status['last_status'] == 'success':
            text += "▫️ Результат: <b>✅ Успешно</b>\n"
        else:
            text += "▫️ Результат: <b>❌ Ошибка</b>\n"
    else:
        text += "▫️ Последний запуск: <i>Нет данных</i>\n"
    
    # Статистика
    stats = status['stats']
    text += f"\n📊 <b>Статистика за всё время:</b>\n"
    text += f"▫️ Всего запусков: <code>{stats['total_runs']}</code>\n"
    text += f"▫️ Успешных: <code>{stats['successful_runs']}</code>\n"
    text += f"▫️ Ошибок: <code>{stats['failed_runs']}</code>\n"
    
    # Кнопки управления
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запустить сейчас", callback_data="parser_run_now")
    builder.adjust(2)
    
    await message.answer(text, reply_markup=builder.as_markup())


@admin_parser_router.callback_query(F.data == "parser_status_refresh")
async def callback_parser_status_refresh(callback: CallbackQuery, parser_scheduler):
    """Обновление статуса через кнопку"""
    status = parser_scheduler.get_status()
    
    # Тот же текст что и в cmd_parser_status
    text = "🤖 <b>Статус парсера расписаний</b>\n\n"
    
    if status['running']:
        text += "▫️ Планировщик: <b>✅ Работает</b>\n"
    else:
        text += "▫️ Планировщик: <b>❌ Остановлен</b>\n"
    
    if status['last_run']:
        time_str = status['last_run'].strftime('%d.%m.%Y %H:%M:%S')
        text += f"▫️ Последний запуск: {time_str}\n"
        
        if status['last_status'] == 'success':
            text += "▫️ Результат: <b>✅ Успешно</b>\n"
        else:
            text += "▫️ Результат: <b>❌ Ошибка</b>\n"
    else:
        text += "▫️ Последний запуск: <i>Нет данных</i>\n"
    
    stats = status['stats']
    text += f"\n📊 <b>Статистика за всё время:</b>\n"
    text += f"▫️ Всего запусков: <code>{stats['total_runs']}</code>\n"
    text += f"▫️ Успешных: <code>{stats['successful_runs']}</code>\n"
    text += f"▫️ Ошибок: <code>{stats['failed_runs']}</code>\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Запустить сейчас", callback_data="parser_run_now")
    builder.adjust(2)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer("✅ Обновлено")


@admin_parser_router.callback_query(F.data == "parser_run_now")
async def callback_parser_run_now(callback: CallbackQuery, parser_scheduler):
    """Принудительный запуск парсера через кнопку"""
    await callback.answer("⏳ Запускаю парсер...", show_alert=True)
    
    # Запускаем парсер в фоне
    import asyncio
    asyncio.create_task(parser_scheduler.run_parser_process())
    
    await callback.message.answer(
        "▶️ Парсер запущен!\n\n"
        "Проверьте логи сервера для отслеживания прогресса.\n"
        "Используйте /parser_status через минуту для проверки результата."
    )


@admin_parser_router.message(Command("parser_run"))
async def cmd_parser_run(message: Message, parser_scheduler):
    """
    Принудительно запускает парсер прямо сейчас.
    Полезно для тестирования или внеплановых обновлений.
    
    Использование: /parser_run
    """
    await message.answer("⏳ Запускаю парсер расписаний...")
    
    # Запускаем парсер и ждём результата
    try:
        await parser_scheduler.run_parser_process()
        
        # Получаем статус после выполнения
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
async def cmd_parser_logs(message: Message):
    """
    Показывает последние строки из лог-файла парсера.
    
    Использование: /parser_logs [количество_строк]
    По умолчанию: 20 строк
    """
    # Парсим количество строк
    args = message.text.split()
    lines_count = 20
    
    if len(args) > 1:
        try:
            lines_count = int(args[1])
            lines_count = min(max(lines_count, 5), 100)  # От 5 до 100
        except ValueError:
            pass
    
    # Читаем лог-файл (путь нужно настроить под вашу систему)
    import os
    log_path = "logs/bot.log"  # Измените на ваш путь
    
    if not os.path.exists(log_path):
        await message.answer(
            "❌ Лог-файл не найден.\n\n"
            f"Ожидаемый путь: <code>{log_path}</code>"
        )
        return
    
    try:
        # Читаем последние N строк
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-lines_count:]
        
        # Фильтруем строки связанные с парсером
        parser_lines = [
            line for line in last_lines 
            if 'парсер' in line.lower() or 'parser' in line.lower()
        ]
        
        if parser_lines:
            text = f"📄 <b>Последние {len(parser_lines)} записей парсера:</b>\n\n"
            text += "<code>" + "".join(parser_lines[-20:]) + "</code>"
        else:
            text = f"📄 Записей о парсере не найдено в последних {lines_count} строках."
        
        # Telegram ограничивает длину сообщения
        if len(text) > 4000:
            text = text[:3950] + "\n\n... (обрезано)</code>"
        
        await message.answer(text)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения логов: <code>{str(e)}</code>")


@admin_parser_router.message(Command("sync_occupancy"))
async def cmd_sync_occupancy(message: Message):
    """Принудительная синхронизация занятости аудиторий"""
    await message.answer("🔄 Запускаю синхронизацию занятости аудиторий...")
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{config.DB_NAME}")
    try:
        await update_occupancy(engine)
        await message.answer("✅ Занятость аудиторий успешно обновлена!")
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
