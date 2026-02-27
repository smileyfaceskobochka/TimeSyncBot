import asyncio
from aiogram.types import Message, CallbackQuery
from typing import Union, Optional

class ProgressReporter:
    def __init__(self, target: Union[Message, CallbackQuery], prefix: str = ""):
        self.target = target
        self.message = target.message if isinstance(target, CallbackQuery) else target
        self.prefix = prefix
        self._last_text = ""

    async def report(self, text: str, progress: Optional[float] = None):
        """
        Reports progress to the user.
        progress: 0.0 to 1.0
        """
        full_text = f"{self.prefix}\n{text}"
        if progress is not None:
            bar_len = 10
            filled = int(progress * bar_len)
            bar = "▓" * filled + "░" * (bar_len - filled)
            full_text += f"\n\n<code>{bar} {int(progress * 100)}%</code>"
        
        if full_text == self._last_text:
            return
            
        self._last_text = full_text
        try:
            await self.message.edit_text(full_text)
        except Exception:
            # Fallback if editing is not possible or same content error
            pass

    def log(self, text: str):
        print(f"[Progress] {text}")
