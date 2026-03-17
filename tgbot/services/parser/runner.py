import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from tgbot.config import config
from tgbot.database.repositories import DatabaseManager, UserRepository
from tgbot.services.parser.site_to_pdf import main_downloader
from tgbot.services.parser.pdf_parser import parse_schedule_files
from tgbot.services.parser.occupancy_parser import update_occupancy
from tgbot.services.parser.progress import ProgressReporter

class ConsoleProgress:
    async def report(self, text: str, progress: float = None):
        p_str = f" [{int(progress*100)}%]" if progress is not None else ""
        logging.info(f"📊 {text}{p_str}")

async def run_pipeline(db_manager: DatabaseManager = None, group_keywords: list[str] = None, progress=None):
    if not progress:
        progress = ConsoleProgress()
        
    logging.info(f"🚀 Starting Pipeline... {'[Batch: ' + str(group_keywords) + ']' if group_keywords else ''}")
    
    # 1. Инциализация БД
    if not db_manager:
        db_manager = DatabaseManager(config.DB_NAME)
    
    user_repo = UserRepository(db_manager)
    await user_repo.create_tables()
    
    # 1.5. Синхронизация списка групп с сайтом ВятГУ (обновляем общий список)
    from tgbot.services.parser.site_to_pdf import sync_groups_list
    await progress.report("🔄 Updating university groups list...", 0.05)
    await sync_groups_list(engine=db_manager.engine, progress=progress)

    # 2. Скачивание PDF
    await progress.report("📥 Downloading schedules...", 0.1)
    new_files = await main_downloader(db_manager=db_manager, group_keywords=group_keywords, progress=progress) 
    
    if new_files:
        await progress.report(f"📄 Parsing {len(new_files)} files...", 0.3)
        await parse_schedule_files(new_files, progress)
    else:
        logging.info("✅ No new schedule files or no tracked groups.")

    # 3. Обновление занятости
    await progress.report("🏢 Updating occupancy...", 0.8)
    await update_occupancy(db_manager.engine)
    
    await progress.report("🏁 Pipeline Finished!", 1.0)
    logging.info("🏁 Pipeline Finished.")

async def cleanup_filesystem(weeks: int = 5):
    """
    Deletes PDF files that are older than specified weeks.
    Also cleans up temporary files in data directory.
    """
    from tgbot.config import config
    
    pdf_dir = str(Path(config.DATA_DIR) / "pdf")
    temp_dir = str(Path(config.DATA_DIR) / "temp")
    cutoff = time.time() - (weeks * 7 * 24 * 60 * 60)
    total_count = 0
    
    # Очистка PDF файлов старше указанного периода
    if os.path.exists(pdf_dir):
        count = 0
        try:
            for group_folder in os.listdir(pdf_dir):
                group_path = os.path.join(pdf_dir, group_folder)
                if not os.path.isdir(group_path):
                    continue
                    
                for filename in os.listdir(group_path):
                    if not filename.endswith(".pdf"):
                        continue
                        
                    file_path = os.path.join(group_path, filename)
                    try:
                        if os.path.getmtime(file_path) < cutoff:
                            os.remove(file_path)
                            count += 1
                    except Exception as e:
                        logging.error(f"Failed to delete {file_path}: {e}")
                        
            if count > 0:
                logging.info(f"🧹 Cleanup (PDF): Removed {count} outdated PDF files from storage.")
                total_count += count
        except Exception as e:
            logging.error(f"Error cleaning PDF directory: {e}")
    
    # Очистка временных файлов (все файлы в папке temp, независимо от возраста)
    if os.path.exists(temp_dir):
        try:
            count = 0
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        count += 1
                    elif os.path.isdir(file_path):
                        import shutil
                        shutil.rmtree(file_path)
                        count += 1
                except Exception as e:
                    logging.error(f"Failed to delete {file_path}: {e}")
            
            if count > 0:
                logging.info(f"🧹 Cleanup (Temp): Removed {count} temporary files.")
                total_count += count
        except Exception as e:
            logging.error(f"Error cleaning temp directory: {e}")
    
    if total_count > 0:
        logging.info(f"✨ Total cleanup: Removed {total_count} files.")

if __name__ == "__main__":
    asyncio.run(run_pipeline())