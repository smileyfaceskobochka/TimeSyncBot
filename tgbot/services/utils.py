import logging
import asyncio
import aiosqlite
from datetime import datetime, date
from typing import List, Optional
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

async def check_connection(db_path: str):
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("SELECT 1")
        logging.info(f"Database connection to {db_path} successful.")
    except Exception as e:
        logging.error(f"Failed to connect to {db_path}: {e}")
        raise

def parse_date(text: str) -> Optional[date]:
    """Парсит дату из строки форматов DD.MM или DD.MM.YYYY"""
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            dt = datetime.strptime(text, fmt).date()
            if dt.year == 1900:
                dt = dt.replace(year=date.today().year)
            return dt
        except ValueError:
            continue
    return None

async def safe_broadcast(bot: Bot, user_ids: List[int], text: str) -> int:
    count = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            count += 1
            await asyncio.sleep(0.05) # Small delay to avoid floods
        except TelegramForbiddenError:
            logging.warning(f"User {user_id} blocked the bot.")
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await bot.send_message(user_id, text)
            count += 1
        except Exception as e:
            logging.error(f"Failed to send message to {user_id}: {e}")
    return count
