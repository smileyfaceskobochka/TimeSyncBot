import logging
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat
)
from tgbot.config import config


async def setup_bot_metadata(bot: Bot):
    """
    Sets up contextual command menus and bot descriptions via Telegram Bot API.
    - Private chats: personal schedule, teacher search, free rooms, meetings, etc.
    - Group chats: today, tomorrow, week, settings.
    - Admin chats: admin panel, synchronizations.
    """
    try:
        # 1. Личные чаты с пользователями
        private_commands = [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="schedule", description="Моё расписание"),
            BotCommand(command="search", description="Поиск расписания группы"),
            BotCommand(command="teacher", description="Поиск преподавателя"),
            BotCommand(command="free", description="Свободные аудитории"),
            BotCommand(command="meet", description="Общие окна (встречи)"),
            BotCommand(command="favorites", description="⭐ Избранное"),
            BotCommand(command="feedback", description="✍️ Отзыв или предложение"),
            BotCommand(command="help", description="Справка по боту"),
        ]
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())

        # 2. Группы и супергруппы (беседы)
        group_commands = [
            BotCommand(command="today", description="Расписание на сегодня"),
            BotCommand(command="tomorrow", description="Расписание на завтра"),
            BotCommand(command="week", description="Расписание на неделю"),
            BotCommand(command="settings", description="⚙️ Настройки рассылки (для админов)"),
            BotCommand(command="help", description="Справка по командам чата"),
        ]
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())

        # 3. Команды для администраторов бота
        admin_commands = private_commands + [
            BotCommand(command="admin", description="👑 Панель администратора"),
            BotCommand(command="parser_status", description="Статус фонового парсера"),
            BotCommand(command="sync_occupancy", description="Синхронизация занятости"),
        ]
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:
                logging.debug(f"Could not set admin commands for {admin_id}: {e}")

        # 4. Описание бота (отображается в пустом чате ДО нажатия кнопки Старт)
        description_text = (
            "🎓 TimeSyncBot — умный помощник по расписанию ВятГУ.\n\n"
            "✨ Возможности:\n"
            "• Быстрое расписание занятий для студентов (день / неделя / календарь)\n"
            "• Поиск преподавателей по кафедрам и институтам\n"
            "• Поиск свободных аудиторий в корпусах\n"
            "• Поиск общих окон между группами для встреч\n"
            "• Избранные группы и преподаватели\n"
            "• Автоматическая утренняя рассылка в беседы групп\n\n"
            "Нажмите «Запустить», чтобы начать!"
        )
        try:
            await bot.set_my_description(description_text)
        except Exception as e:
            logging.debug(f"Could not set bot description: {e}")

        # 5. Краткое описание бота (в профиле бота и при шеринге ссылки)
        short_desc = "Умный бот расписания ВятГУ: пары, преподаватели, свободные аудитории и авто-рассылки в беседы."
        try:
            await bot.set_my_short_description(short_desc)
        except Exception as e:
            logging.debug(f"Could not set bot short description: {e}")

        logging.info("✓ Bot contextual commands and descriptions registered")
    except Exception as e:
        logging.warning(f"Failed to configure bot metadata: {e}")
