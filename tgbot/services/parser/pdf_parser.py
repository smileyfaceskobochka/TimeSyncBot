import asyncio
import logging
from datetime import datetime, date, timedelta
import re
from typing import List, Tuple
from pathlib import Path

import pdfplumber
import fitz  # PyMuPDF
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Lesson
from tgbot.services.parser.utils import parse_lesson_details

def process_pdf_sync(file_path, group_name):
    """
    Гибридная функция: pdfplumber для детекции строк, 
    fitz (PyMuPDF) для чистого извлечения текста.
    """
    data_list = []
    filename = Path(file_path).name
    match = re.search(r'_(?:\d+)_(\d{8})_\d{8}\.pdf', filename)
    if not match:
        logging.error(f"Cannot extract start date from filename: {filename}")
        return []

    start_date_str = match.group(1)
    try:
        start_date = datetime.strptime(start_date_str, "%d%m%Y").date()
    except ValueError as e: return []

    try:
        doc_fitz = fitz.open(file_path)
        current_date = start_date
        prev_start_time = None

        with pdfplumber.open(file_path) as pdf_plumb:
            for page_idx, page_plumb in enumerate(pdf_plumb.pages):
                page_fitz = doc_fitz[page_idx]
                
                # 1. Row Separators (from pdfplumber)
                all_separators = []
                for r in page_plumb.rects:
                    if (r["x1"] - r["x0"]) > 400 and (r["bottom"] - r["top"]) <= 3:
                        all_separators.append(r["top"])
                for l in page_plumb.lines:
                    if (l["x1"] - l["x0"]) > 400:
                        all_separators.append(l["top"])
                all_separators.append(0)
                all_separators.append(page_plumb.height)
                all_separators.sort()
                
                unique_seps = []
                for s in all_separators:
                    if not unique_seps or abs(s - unique_seps[-1]) > 5:
                        unique_seps.append(s)
                
                # 2. Extract content for each row
                for i in range(len(unique_seps) - 1):
                    y0, y1 = unique_seps[i], unique_seps[i+1]
                    
                    # A. Day Column (x: 40-78)
                    day_words = page_fitz.get_text("words", clip=fitz.Rect(40, y0, 78, y1))
                    day_words.sort(key=lambda x: x[1], reverse=True) # Bottom-to-top reconstructed
                    day_text = "".join([w[4] for w in day_words]).strip()

                    m_date = re.search(r'(\d{2}\.\d{2}\.(?:20\d{2}|\d{2,4}))', day_text)
                    if m_date:
                        try:
                            d_str = m_date.group(1)
                            p = d_str.split('.')
                            dv, mv, yv = int(p[0]), int(p[1]), int(p[2])
                            if yv < 100: yv += 2000
                            elif yv > 2100: yv = yv // 100
                            new_date = date(yv, mv, dv)
                            if new_date != current_date:
                                current_date = new_date
                        except: pass
                    
                    # B. Time Column (x: 82-148)
                    time_words = page_fitz.get_text("words", clip=fitz.Rect(82, y0, 148, y1))
                    time_words.sort(key=lambda x: (x[1], x[0]))
                    time_text = " ".join([w[4] for w in time_words]).strip()
                    m_time = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', time_text)
                    
                    # C. Info Column (x: 148-565)
                    info_words = page_fitz.get_text("words", clip=fitz.Rect(148, y0, 565, y1))
                    info_words.sort(key=lambda x: (x[1], x[0]))
                    # Filter junk: single chars like 'р' from vertical labels
                    whitelist = "ивскаоу".lower()
                    filtered_info = []
                    for w in info_words:
                        txt = w[4].strip()
                        if len(txt) == 1 and txt.lower() not in whitelist and not txt.isdigit():
                            continue
                        filtered_info.append(txt)
                    info_text = " ".join(filtered_info).strip()

                    # Split info_text into individual lessons if group_name repeats
                    lesson_chunks = []
                    if group_name and group_name.lower() in info_text.lower():
                        # Split by group name while keeping it
                        split_pat = re.compile(rf'(?={re.escape(group_name)})', re.IGNORECASE)
                        lesson_chunks = [p.strip() for p in split_pat.split(info_text) if p.strip()]
                    else:
                        lesson_chunks = [info_text] if info_text else []

                    if m_time:
                        start_t = m_time.group(1)
                        end_t = m_time.group(2)
                        pair_num = config.TIME_SLOTS.get(start_t)
                        
                        if prev_start_time and start_t < prev_start_time:
                            if not m_date:
                                current_date += timedelta(days=1)
                        
                        prev_start_time = start_t
                        
                        for chunk in lesson_chunks:
                            lesson_raw = re.sub(r'^\d+\.?\s*', '', chunk).strip()
                            subj, c_type, teach, build, room, subgrp = parse_lesson_details(lesson_raw, group_name)
                            
                            if subj or c_type:
                                data_list.append(Lesson(
                                    group_name=group_name, date=current_date.isoformat(),
                                    pair_number=pair_num, start_time=start_t, end_time=end_t,
                                    subject=subj, class_type=c_type, teacher=teach,
                                    building=build, room=room, subgroup=subgrp, raw_info=lesson_raw
                                ))
                    elif lesson_chunks and data_list and (y1 - y0) < 100:
                        # Row with no time: either continuation OR new lesson if group_name is present
                        if group_name and group_name.lower() in info_text.lower():
                            # It's a new lesson (or lessons) sharing previous row's time
                            last = data_list[-1]
                            for chunk in lesson_chunks:
                                lesson_raw = re.sub(r'^\d+\.?\s*', '', chunk).strip()
                                subj, c_type, teach, build, room, subgrp = parse_lesson_details(lesson_raw, group_name)
                                if subj or c_type:
                                    data_list.append(Lesson(
                                        group_name=group_name, date=current_date.isoformat(),
                                        pair_number=last.pair_number, start_time=last.start_time, end_time=last.end_time,
                                        subject=subj, class_type=c_type, teacher=teach,
                                        building=build, room=room, subgroup=subgrp, raw_info=lesson_raw
                                    ))
                        else:
                            # Genuine continuation of last lesson
                            last = data_list[-1]
                            if last.date == current_date.isoformat():
                                last.raw_info += " " + info_text
                                s, ct, t, b, r, sg = parse_lesson_details(last.raw_info, group_name)
                                last.subject, last.class_type, last.teacher = s, ct, t
                                last.building, last.room, last.subgroup = b, r, sg
        doc_fitz.close()
    except Exception as e:
        logging.error(f"Error in hybrid parser: {e}", exc_info=True)
        return []
    return data_list

def _sync_save_lessons(engine, lessons):
    with Session(engine) as session:
        session.add_all(lessons)
        session.commit()

async def save_lessons_to_db(lessons: List[Lesson], engine=None):
    if not lessons: return
    if engine is None: engine = create_engine(f"sqlite:///{config.DB_NAME}")
    await asyncio.to_thread(_sync_save_lessons, engine, lessons)
    logging.info(f"✅ Saved {len(lessons)} lessons")

async def parse_schedule_files(files: List[Tuple[str, str]], progress=None):
    engine = create_engine(f"sqlite:///{config.DB_NAME}")
    for i, (f, g) in enumerate(files):
        if progress: await progress.report(f"📄 Parsing {g}...", i/len(files))
        lessons = await asyncio.to_thread(process_pdf_sync, f, g)
        if lessons: await save_lessons_to_db(lessons, engine)