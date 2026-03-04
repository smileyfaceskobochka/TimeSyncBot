import asyncio
import logging
from datetime import datetime
import re
from typing import List, Tuple

import pdfplumber
import pandas as pd
from sqlalchemy import delete, create_engine
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Lesson
from tgbot.services.parser.utils import parse_lesson_details

def process_pdf_sync(file_path, group_name):
    """
    Синхронная функция для обработки PDF.
    Возвращает список объектов Lesson (без id).
    """
    data_list = []
    
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            tables = []
            for page in pdf.pages:
                page_tables = page.extract_tables()
                if page_tables:
                    tables.extend(page_tables)
    except Exception as e:
        logging.error(f"Error reading PDF {file_path}: {e}")
        return []

    if not tables: 
        return []

    df_full = pd.concat([pd.DataFrame(table[1:], columns=table[0]) for table in tables], ignore_index=True)
    
    for col in df_full.columns:
        df_full[col] = df_full[col].astype(str).replace({r'\n': ' ', r'\r': ''}, regex=True).str.strip()
    
    if len(df_full.columns) < 3: 
        return []

    df_full['lesson_info_full'] = df_full.iloc[:, 2:].agg(' '.join, axis=1).str.strip()
    
    current_day = ""
    current_time = ""

    for _, row in df_full.iterrows():
        day_text = row.get(0, "").strip()
        time_text = row.get(1, "").strip()
        lesson_text = row.get('lesson_info_full', "").strip()

        if day_text: 
            current_day = day_text
        if time_text and "интервал" not in time_text.lower(): 
            current_time = time_text
        
        if not current_day and not current_time and not lesson_text: 
            continue
        if not lesson_text: 
            continue
        if "день" in current_day.lower() and "интервал" in current_time.lower(): 
            continue

        date_iso = None
        date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', current_day)
        if date_match:
            date_iso = f"20{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        else:
            continue

        start_time = None
        end_time = None
        pair_num = None
        
        if current_time:
            parts = current_time.split('-')
            start_time = parts[0].strip()
            if len(parts) > 1:
                end_time = parts[1].strip()
            pair_num = config.TIME_SLOTS.get(start_time)

        subj, c_type, teach, build, room, subgrp = parse_lesson_details(lesson_text, group_name)
        
        if subj or c_type:
            data_list.append(Lesson(
                group_name=group_name,
                date=date_iso,
                pair_number=pair_num,
                start_time=start_time,
                end_time=end_time,
                subject=subj,
                class_type=c_type,
                teacher=teach,
                building=build,
                room=room,
                subgroup=subgrp,
                raw_info=lesson_text
            ))

    return data_list

def _sync_save_lessons(engine, lessons):
    with Session(engine) as session:
        session.add_all(lessons)
        session.commit()

async def save_lessons_to_db(lessons: List[Lesson], engine=None):
    if not lessons: 
        return
    
    if engine is None:
        engine = create_engine(f"sqlite:///{config.DB_NAME}")
        
    group_name = lessons[0].group_name
    await asyncio.to_thread(_sync_save_lessons, engine, lessons)
    logging.info(f"✅ Saved {len(lessons)} lessons for {group_name}")

async def parse_schedule_files(files_to_parse: List[Tuple[str, str]], progress=None):
    """
    Разбирает список файлов (путь, название_группы) и сохраняет в БД.
    """
    engine = create_engine(f"sqlite:///{config.DB_NAME}")
    
    total = len(files_to_parse)
    for i, (f_path, g_name) in enumerate(files_to_parse):
        if progress: 
            await progress.report(f"📄 Parsing {g_name}...", (i / total if total > 0 else 0))
        
        lessons = await asyncio.to_thread(process_pdf_sync, f_path, g_name)
        if lessons:
            await save_lessons_to_db(lessons, engine)