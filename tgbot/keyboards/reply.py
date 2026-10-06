"""
Persistent Reply keyboards (keyboards under chat textbox) for TimeSyncBot.
Adheres to the Unix principle of direct, one-tap composition.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


REPLY_BUTTON_TEXTS = {
    "📅 Сегодня", "📆 Завтра", "🗓 Неделя",
    "🏢 Аудитории", "👨‍🏫 Преподаватели", "⭐ Избранное",
    "🔎 Поиск группы", "⚙️ Настройки", "💬 Главное меню"
}


def get_main_reply_kb() -> ReplyKeyboardMarkup:
    """
    Persistent bottom keyboard under the Telegram text input.
    Provides instant 1-tap access to primary schedule queries and navigation.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Сегодня"),
                KeyboardButton(text="📆 Завтра"),
                KeyboardButton(text="🗓 Неделя"),
            ],
            [
                KeyboardButton(text="🏢 Аудитории"),
                KeyboardButton(text="👨‍🏫 Преподаватели"),
                KeyboardButton(text="⭐ Избранное"),
            ],
            [
                KeyboardButton(text="🔎 Поиск группы"),
                KeyboardButton(text="⚙️ Настройки"),
                KeyboardButton(text="💬 Главное меню"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие или введите группу...",
    )
