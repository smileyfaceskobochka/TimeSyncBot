import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import List, Dict, Tuple
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Lesson
from tgbot.services.parser.site_to_pdf import check_website_status

TEACHER_URL = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/teacher.html"
BASE_URL = config.VYATSU_BASE_URL
HEADERS = config.HTTP_HEADERS

async def get_teacher_navigation_data() -> List[Dict]:
    """
    Scrapes the teacher occupancy main page to get the hierarchy:
    Institute -> Faculty -> Department -> Report Links
    """
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        try:
            async with session.get(TEACHER_URL, timeout=30) as resp:
                if resp.status != 200:
                    logging.error(f"Failed to fetch teacher page: {resp.status}")
                    return []
                html = await resp.text()
        except Exception as e:
            logging.error(f"Error fetching teacher navigation: {e}")
            return []

    soup = BeautifulSoup(html, 'html.parser')
    institutes = []
    
    # The structure on the page uses div.fak_name for Faculties/Institutes
    # and div.kafPeriod for nested departments, with listPeriod holding the reports.
    for fak_div in soup.find_all('div', class_='fak_name'):
        inst_name = fak_div.text.strip()
        
        current_inst = {
            "name": inst_name,
            "faculties": [{"name": "Все кафедры", "departments": []}] 
        }
        institutes.append(current_inst)
        
        fak_id = fak_div.get('data-fak_id')
        block_content = soup.find('div', id=f"fak_id_{fak_id}")
        
        if block_content:
            for kaf_div in block_content.find_all('div', class_='kafPeriod'):
                dept_name = kaf_div.text.strip()
                
                kaf_period_id = kaf_div.get('data-kaf_period_id')
                list_period = block_content.find('div', id=f"listPeriod_{kaf_period_id}")
                
                reports = []
                if list_period:
                    for a in list_period.find_all('a'):
                        href = a.get('href')
                        if href and href.endswith('.html'):
                            reports.append({
                                "period": a.text.strip(),
                                "url": urljoin(BASE_URL, href)
                            })
                
                if reports:
                    current_inst["faculties"][0]["departments"].append({
                        "name": dept_name,
                        "reports": reports
                    })

    return institutes

def parse_teacher_html_report(html: bytes, dept_name: str) -> List[Lesson]:
    """
    Parses a department teacher report.
    Structure:
    - Row 0: Date spans (headers)
    - Row 1: Teachers names (headers)
    - Rows 2+: Time intervals and lesson data
    """
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    if not table:
        return []

    rows = table.find_all('tr')
    if len(rows) < 3:
        return []

    # Row 0: Date headers (col0=blank, col1=blank, col2+=date)
    # Row 1: Teachers (col0=blank, col1=Интервал, col2+=teacher name)
    
    teachers = []
    teacher_cols = [] # Map column index to teacher name
    
    # Process Row 1 to find teachers. They start from col 2 (idx 2)
    header_cells = rows[1].find_all(['td', 'th'])
    for idx, cell in enumerate(header_cells):
        txt = cell.get_text(strip=True).replace('\xa0', ' ')
        if idx >= 2 and txt:
            teachers.append(txt)
            teacher_cols.append((idx, txt))

    # Row 0 gives us the dates. These tables are often organized by days.
    # col0 usually has the "rotated" day name (Понедельник...)
    
    current_date = None
    results = []
    
    # Map pair numbers to time slots
    TIME_SLOTS = config.TIME_SLOTS # e.g. "08:20" -> 1
    
    for row in rows[2:]:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
            
        # Tables with rowspans mean the first cell isn't always the day.
        # But if it contains a date pattern, it's the day cell.
        date_match = None
        time_cell_idx = 0
        
        # Check if first cell has a date
        day_text = cells[0].get_text(strip=True)
        date_match = re.search(r'(\d{2}\.\d{2}\.\d{2,4})', day_text)
        
        if date_match:
            try:
                # Could be 2-digit year (e.g. 16.03.26)
                date_str = date_match.group(1)
                fmt = '%d.%m.%y' if len(date_str.split('.')[2]) == 2 else '%d.%m.%Y'
                current_date = datetime.strptime(date_str, fmt).date()
            except ValueError:
                pass
            time_cell_idx = 1 # time is in the next cell
            
        if not current_date:
            continue
            
        if time_cell_idx >= len(cells):
            continue

        # Time interval "08:20-09:50"
        time_cell = cells[time_cell_idx].get_text(strip=True)
        if not re.match(r'\d{2}:\d{2}-\d{2}:\d{2}', time_cell):
            continue
            
        start_time = time_cell.split('-')[0]
        pair_num = TIME_SLOTS.get(start_time)

        # Process teachers columns
        for col_idx, teacher_name in teacher_cols:
            if col_idx >= len(cells):
                continue
                
            cell_content = cells[col_idx].get_text(" ", strip=True)
            if not cell_content:
                continue
            
            # Cell usually contains: [Auditory] [Subject] [Type] [Groups]
            # Example: "1-236 Промпт-инжиниринг Лекция ИВТб-2301"
            # We can use our existing parse_lesson_details if we tweak it or handle it here.
            
            # Rough split: room usually looks like digits-digits
            room_match = re.search(r'(\d{1,2}|ФОК|Гл\.[^\s]*)\s*-\s*([^\s]+)', cell_content)
            room = room_match.group(0) if room_match else ""
            remaining = cell_content.replace(room, "").strip()
            
            results.append(Lesson(
                group_name="Multiple", # Teacher reports combine groups
                date=current_date.isoformat(),
                pair_number=pair_num,
                start_time=start_time,
                end_time=time_cell.split('-')[1] if '-' in time_cell else None,
                teacher=teacher_name,
                building=room_match.group(1) if room_match else None,
                room=room_match.group(2) if room_match else None,
                raw_info=cell_content,
                subject=remaining
            ))

    return results

async def update_all_teachers_data():
    """
    (Optional/Internal) Scans all reports and caches teacher names.
    Since reports are dynamic, we might perform on-demand lookup instead.
    """
    pass
