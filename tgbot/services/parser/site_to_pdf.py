import asyncio
import logging
from pathlib import Path
from typing import List, Tuple
import re
from datetime import datetime
from urllib.parse import urljoin
import hashlib

import aiohttp
import aiofiles
from bs4 import BeautifulSoup
from sqlalchemy import select, update, create_engine
from sqlalchemy.orm import sessionmaker, Session

from tgbot.config import config
from tgbot.services.parser.progress import ProgressReporter
from tgbot.database.models import TrackedGroup, ProcessedFile
from tgbot.database.repositories import DatabaseManager

# Константы (centralized in config)
SCHEDULE_URL = config.SCHEDULE_URL
BASE_URL = config.VYATSU_BASE_URL
HEADERS = config.HTTP_HEADERS
OUTPUT_DIR = Path(config.DATA_DIR) / "pdf"

MAX_CONCURRENT_DOWNLOADS = 5
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


async def check_website_status(url: str = None, timeout: int = 10) -> tuple:
    """
    Проверяет доступность сайта ВятГУ.
    Returns: (is_available: bool, status_code: int, error: str | None)
    """
    if url is None:
        url = SCHEDULE_URL
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return (True, resp.status, None)
                else:
                    return (False, resp.status, f"HTTP {resp.status}")
    except asyncio.TimeoutError:
        return (False, 0, "Таймаут соединения")
    except aiohttp.ClientConnectorError as e:
        return (False, 0, f"Ошибка подключения: {e}")
    except Exception as e:
        return (False, 0, f"Неизвестная ошибка: {e}")


def calculate_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()

def _sync_check_hash(session_factory, filename, new_hash, file_path):
    with session_factory() as db_session:
        stmt = select(ProcessedFile).where(ProcessedFile.filename == filename)
        db_file = db_session.execute(stmt).scalar_one_or_none()
        
        if db_file and db_file.file_hash == new_hash and Path(file_path).exists():
            return True, None
        return False, new_hash

async def download_pdf_if_needed(session: aiohttp.ClientSession, url: str, group_name: str, session_factory):
    """
    Скачивает PDF если хеш изменился. Возвращает (путь, группа, имя_файла, новый_хеш).
    """
    filename = Path(url).name
    safe_group = group_name.replace('/', '_')
    group_dir = OUTPUT_DIR / safe_group
    group_dir.mkdir(parents=True, exist_ok=True)
    file_path = group_dir / filename

    max_retries = 3
    async with DOWNLOAD_SEMAPHORE:
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=45) as resp:
                    if resp.status != 200:
                        logging.warning(f"⚠️ Failed to download {url}: HTTP {resp.status}")
                        if resp.status in [429, 503, 504] and attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return None
                    
                    content = await resp.read()
                    new_hash = calculate_hash(content)
                    
                    skip, hash_to_return = await asyncio.to_thread(_sync_check_hash, session_factory, filename, new_hash, file_path)
                    
                    if skip:
                        return (str(file_path), safe_group, filename, None)

                    # Сохраняем файл
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(content)
                    
                    return (str(file_path), safe_group, filename, hash_to_return)
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"🔄 Retry {attempt+1} for {url} after error: {e}")
                    await asyncio.sleep(2 ** attempt)
                    continue
                logging.error(f"❌ Final failure downloading {url}: {e}")
                return None

def _sync_add_groups(engine, groups_list):
    from sqlalchemy.orm import Session
    with Session(engine) as session:
        for group_name in groups_list:
            stmt = select(TrackedGroup).where(TrackedGroup.group_name == group_name)
            if not session.execute(stmt).scalar_one_or_none():
                session.add(TrackedGroup(group_name=group_name, is_tracked=False))
        session.commit()

async def sync_groups_list(engine=None, progress=None):
    """
    Сканирует основную страницу и сохраняет ВСЕ группы в БД для последующего выбора пользователем.
    """
    logging.info("🔍 Syncing groups list from university page...")
    
    if engine is None:
        engine = create_engine(f"sqlite:///{config.DB_NAME}")

    # Проверяем доступность сайта
    is_available, status_code, error_msg = await check_website_status()
    if not is_available:
        logging.warning(f"🌐 Сайт ВятГУ недоступен: {error_msg}")
        if progress:
            await progress.report(f"🌐 Сайт ВятГУ недоступен: {error_msg}", 1.0)
        return False

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(SCHEDULE_URL) as resp:
                if resp.status != 200:
                    logging.warning(f"🌐 Сайт ВятГУ вернул HTTP {resp.status}")
                    return False
                text = await resp.text()
        
        soup = BeautifulSoup(text, 'html.parser')
        group_elements = soup.find_all('div', class_='grpPeriod')
        groups_list = [g.get_text(strip=True) for g in group_elements]
        
        await asyncio.to_thread(_sync_add_groups, engine, groups_list)
            
        logging.info(f"✅ Discovered {len(groups_list)} groups.")
        return True
    except Exception as e:
        logging.error(f"Error syncing groups: {e}")
        return False

def _sync_get_tracked_groups(session_factory, group_keywords=None):
    with session_factory() as session:
        if group_keywords:
            # Ensure keywords is a list
            if isinstance(group_keywords, str):
                group_keywords = [group_keywords]
                
            for kw in group_keywords:
                stmt = update(TrackedGroup).where(TrackedGroup.group_name == kw).values(is_tracked=True)
                session.execute(stmt)
            session.commit()
            return group_keywords
        else:
            stmt = select(TrackedGroup.group_name).where(TrackedGroup.is_tracked == True)
            return list(session.execute(stmt).scalars().all())

def _sync_update_processed_file(session_factory, f_name, f_hash):
    with session_factory() as session:
        stmt = select(ProcessedFile).where(ProcessedFile.filename == f_name)
        db_file = session.execute(stmt).scalar_one_or_none()
        if db_file:
            db_file.file_hash = f_hash
        else:
            session.add(ProcessedFile(filename=f_name, file_hash=f_hash, file_type='schedule'))
        session.commit()

async def main_downloader(db_manager: DatabaseManager = None, group_keywords: List[str] = None, progress=None):
    """
    Main function for downloading and processing groups.
    If group_keywords is provided, downloads ONLY those groups.
    """
    def is_schedule_actual(link_text: str) -> bool:
        """
        Extracts dates from format "c 16 02 2026 по 01 03 2026"
        and returns True if schedule is not older than 5 weeks.
        """
        match = re.search(r'c\s+(\d{2})\s+(\d{2})\s+(\d{4})\s+по\s+(\d{2})\s+(\d{2})\s+(\d{4})', link_text)
        if not match: return True
        
        try:
            end_date = datetime(int(match.group(6)), int(match.group(5)), int(match.group(4)))
            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            return end_date >= cutoff - timedelta(weeks=5)
        except Exception as e:
            logging.error(f"Error parsing date in link: {e}")
            return True

    files_to_parse = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if db_manager:
        session_factory = db_manager.session_factory
    else:
        engine = create_engine(f"sqlite:///{config.DB_NAME}")
        session_factory = sessionmaker(engine, expire_on_commit=False, class_=Session)
    
    if progress: await progress.report("🔍 Checking groups list...", 0.1)
    
    tracked_groups_list = await asyncio.to_thread(_sync_get_tracked_groups, session_factory, group_keywords)
    
    if not tracked_groups_list:
        logging.warning("⚠️ No groups to download.")
        return []
    
    logging.info(f"🎯 Fetching PDFs for {len(tracked_groups_list)} groups...")

    # Проверяем доступность сайта
    is_available, status_code, error_msg = await check_website_status()
    if not is_available:
        logging.warning(f"🌐 Сайт ВятГУ недоступен при загрузке PDF: {error_msg}")
        if progress:
            await progress.report(f"🌐 Сайт ВятГУ недоступен: {error_msg}", 1.0)
        return []

    async with aiohttp.ClientSession(headers=HEADERS) as http_session:
        async with http_session.get(SCHEDULE_URL) as resp:
            if resp.status != 200: return []
            main_text = await resp.text()
        
        soup = BeautifulSoup(main_text, 'html.parser')
        group_elements = soup.find_all('div', class_='grpPeriod')
        tasks = []
        
        for group_div in group_elements:
            group_name = group_div.get_text(strip=True)
            if group_name not in tracked_groups_list:
                continue
            
            period_id = group_div.get('data-grp_period_id')
            list_div = soup.find('div', id=f"listPeriod_{period_id}")
            if not list_div: continue
            
            links = list_div.find_all('a', href=True)
            for link in links:
                link_text = link.get_text(strip=True)
                if not is_schedule_actual(link_text):
                    logging.info(f"⏩ Skipping outdated schedule: {link_text}")
                    continue
                
                href = link['href']
                if href.endswith('.pdf'):
                    full_url = urljoin(BASE_URL, href)
                    tasks.append(download_pdf_if_needed(http_session, full_url, group_name, session_factory))
        
        if not tasks:
            return []
            
        results = await asyncio.gather(*tasks)
        processed_files = []
        for res in results:
            if res:
                f_path, g_name, f_name, f_hash = res
                if f_hash:  # New or changed
                    processed_files.append((f_path, g_name))
                    await asyncio.to_thread(_sync_update_processed_file, session_factory, f_name, f_hash)
                else:
                    processed_files.append((f_path, g_name))
        
        return processed_files
