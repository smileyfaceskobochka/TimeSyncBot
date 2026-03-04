import logging
import asyncio
import time
from typing import Dict

class RateLimiter:
    """
    A simple in-memory rate limiter to prevent abuse of heavy operations like parsing.
    Requires passing `user_id` and implements a cooldown period.
    """
    def __init__(self, cooldown_seconds: int = 300):
        self.cooldown_seconds = cooldown_seconds
        self._last_used: Dict[int, float] = {}

    def check_limit(self, user_id: int) -> tuple[bool, int]:
        """
        Check if the user is allowed to perform the action.
        Returns (is_allowed: bool, remaining_seconds: int)
        """
        now = time.time()
        last_time = self._last_used.get(user_id, 0.0)
        elapsed = now - last_time
        
        if elapsed < self.cooldown_seconds:
            remaining = int(self.cooldown_seconds - elapsed)
            return False, remaining
            
        return True, 0

    def record_usage(self, user_id: int):
        """Record that the user just performed the action."""
        self._last_used[user_id] = time.time()

# Global limiters
# 5 minutes cooldown per user for triggering full schedule sync
parser_rate_limiter = RateLimiter(cooldown_seconds=300)
