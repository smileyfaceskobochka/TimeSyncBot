from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from tgbot.config import config

class AdminFilter(BaseFilter):
    """Filter to ensure the user is listed in config.ADMIN_IDS."""
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        if not obj.from_user:
            return False
        return obj.from_user.id in config.ADMIN_IDS
