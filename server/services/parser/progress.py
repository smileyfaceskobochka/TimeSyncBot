import asyncio
import time
from aiogram.types import Message, CallbackQuery
from typing import Union, Optional

class ProgressReporter:
    # Docker-style Unicode spinner
    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, target: Union[Message, CallbackQuery], prefix: str = ""):
        self.target = target
        self.message = target.message if isinstance(target, CallbackQuery) else target
        self.prefix = prefix
        self._last_text = ""
        self._last_update = 0
        self._spinner_idx = 0

    async def report(self, text: str, progress: Optional[float] = None):
        """
        Reports progress to the user with Docker-style Unicode animation.
        progress: 0.0 to 1.0
        """
        now = time.time()
        
        # Rate limit updates to ~2.5 per second to avoid Telegram flood limits
        # We always allow the 100% update to ensure it finishes correctly
        is_finished = progress is not None and progress >= 1.0
        if not is_finished and now - self._last_update < 0.4:
            return

        # Choose spinner or checkmark
        if is_finished:
            spinner = "✅"
        else:
            spinner = self.SPINNER[self._spinner_idx % len(self.SPINNER)]
            self._spinner_idx += 1

        # Docker-like header
        header = f"<b>{self.prefix}</b>" if self.prefix else "<b>TimeSync Parser</b>"
        
        # Prepare the state line
        # Truncate text if it's too long to keep the bar aligned
        display_text = (text[:18] + '..') if len(text) > 20 else text
        
        if progress is not None:
            bar_len = 15
            filled = int(progress * bar_len)
            
            # Docker style [=====>    ]
            if filled < bar_len:
                bar = "=" * filled + ">" + " " * (bar_len - filled - 1)
            else:
                bar = "=" * bar_len
                
            percent = int(progress * 100)
            # Unicode monospaced layout
            status_line = f"<code>{spinner} {display_text:<20} [{bar}] {percent:>3}%</code>"
        else:
            status_line = f"<code>{spinner} {display_text}</code>"
        
        full_text = f"{header}\n\n{status_line}"
        
        if full_text == self._last_text:
            return
            
        self._last_text = full_text
        self._last_update = now
        
        try:
            await self.message.edit_text(full_text, parse_mode="HTML")
        except Exception:
            # Common errors: message not modified, or message deleted.
            pass

    def log(self, text: str):
        print(f"[Progress] {text}")
