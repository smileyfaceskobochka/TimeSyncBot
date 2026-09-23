import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import List, Dict, Tuple
from urllib.parse import urljoin

import aiohttp
from selectolax.parser import HTMLParser
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Lesson
from tgbot.services.parser.site_to_pdf import check_website_status

TEACHER_URL = config.TEACHER_URL
BASE_URL = config.VYATSU_BASE_URL
HEADERS = config.HTTP_HEADERS

async def get_teacher_navigation_data() -> List[Dict]:
    """
    Scrapes the teacher occupancy main page to get the hierarchy:
    Institute -> Faculty -> Department -> Report Links
    Uses fast selectolax parser.
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

    tree = HTMLParser(html)
    institutes = []
    
    # The structure on the page uses div.fak_name for Faculties/Institutes
    # and div.kafPeriod for nested departments, with listPeriod holding the reports.
    for fak_div in tree.css('div.fak_name'):
        inst_name = fak_div.text(strip=True)
        
        current_inst = {
            "name": inst_name,
            "faculties": [{"name": "Все кафедры", "departments": []}] 
        }
        institutes.append(current_inst)
        
        fak_id = fak_div.attributes.get('data-fak_id')
        block_content = tree.css_first(f"#fak_id_{fak_id}") if fak_id else None
        
        if block_content:
            for kaf_div in block_content.css('div.kafPeriod'):
                dept_name = kaf_div.text(strip=True)
                
                kaf_period_id = kaf_div.attributes.get('data-kaf_period_id')
                list_period = block_content.css_first(f"#listPeriod_{kaf_period_id}") if kaf_period_id else None
                
                reports = []
                if list_period:
                    for a in list_period.css('a[href]'):
                        href = a.attributes.get('href', '')
                        if href and href.endswith('.html'):
                            reports.append({
                                "period": a.text(strip=True),
                                "url": urljoin(BASE_URL, href)
                            })
                
                if reports:
                    current_inst["faculties"][0]["departments"].append({
                        "name": dept_name,
                        "reports": reports
                    })

    return institutes

def find_active_teacher_reports(nav_data: List[Dict]) -> List[Tuple[str, str]]:
    """Returns a list of (dept_name, report_url) for the current active period."""
    today = date.today()
    active_reports = []
    
    for inst in nav_data:
        for fac in inst.get("faculties", []):
            for dept in fac.get("departments", []):
                dept_name = dept.get("name", "")
                reports = dept.get("reports", [])
                if not reports:
                    continue
                
                selected_url = None
                for rep in reports:
                    m = re.search(r'c\s+(\d{2})\s+(\d{2})\s+(\d{4})\s+по\s+(\d{2})\s+(\d{2})\s+(\d{4})', rep.get("period", ""))
                    if m:
                        try:
                            start_d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                            end_d = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
                            if start_d <= today <= end_d:
                                selected_url = rep["url"]
                                break
                        except ValueError:
                            pass
                
                if not selected_url and reports:
                    selected_url = reports[0]["url"]
                    
                if selected_url:
                    active_reports.append((dept_name, selected_url))
                    
    return active_reports

def parse_teacher_cell_entry(raw_line: str) -> Dict:
    """Parses a single line from a teacher report cell into structured components."""
    # 1. Room: e.g. '2-209', '1-535_', '4-302', 'ФОК-1', 'Гл.-204'
    room_match = re.search(r'(\d{1,2}|ФОК|Гл\.[^\s_]*)\s*-\s*([^\s_]+)', raw_line)
    bld, aud = '', ''
    clean_line = raw_line
    if room_match:
        bld = room_match.group(1).strip()
        aud = room_match.group(2).strip(' _')
        clean_line = clean_line[:room_match.start()] + ' ' + clean_line[room_match.end():]
    
    clean_line = clean_line.strip(' _')
    
    # 2. Known lesson types
    type_pattern = r'\b(Лекция|Практическое занятие|Лабораторная работа|Семинар|Консультация|Дифференцированный зачет|Дифференцированный зачёт|Зачет|Зачёт|Экзамен|Курсовая работа|Курсовой проект)\b'
    m_type = re.search(type_pattern, clean_line, re.IGNORECASE)
    
    if m_type:
        subject = clean_line[:m_type.start()].strip(' ,')
        class_type = m_type.group(1).strip()
        rest = clean_line[m_type.end():].strip(' ,')
    else:
        m_grp = re.search(r'\b([А-Яа-яЁёA-Za-z]+-[0-9]{3,4})', clean_line)
        if m_grp:
            subject = clean_line[:m_grp.start()].strip(' ,')
            class_type = ''
            rest = clean_line[m_grp.start():].strip(' ,')
        else:
            subject = clean_line
            class_type = ''
            rest = ''
            
    # 3. Extract groups and subgroups from rest
    parts = re.findall(r'([А-Яа-яЁёA-Za-z]+-[0-9]{3,4}(?:-[0-9]{2}-[0-9]{2})?)(?:,\s*(\d{1,2})\s*подгруппа)?', rest)
    groups_dict = {}
    for grp, sub in parts:
        if grp not in groups_dict:
            groups_dict[grp] = set()
        if sub:
            groups_dict[grp].add(int(sub))
            
    group_strs = []
    is_lecture = 'лек' in class_type.lower()
    for grp, subs in groups_dict.items():
        if not is_lecture and len(subs) == 1:
            group_strs.append(f'{grp} ({next(iter(subs))} подгр.)')
        else:
            group_strs.append(grp)
            
    return {
        'building': bld or None,
        'room': aud or None,
        'subject': subject or "Занятие",
        'class_type': class_type or None,
        'groups_str': ', '.join(group_strs) if group_strs else None
    }


def parse_teacher_html_report(html: bytes | str, dept_name: str) -> List[Lesson]:
    """
    Parses a department teacher report using fast selectolax parser.
    Structure:
    - Row 0: Date spans (headers)
    - Row 1: Teachers names (headers)
    - Rows 2+: Time intervals and lesson data
    """
    tree = HTMLParser(html)
    table = tree.css_first('table')
    if not table:
        return []

    rows = table.css('tr')
    if len(rows) < 3:
        return []

    # Row 0: Date headers (col0=blank, col1=blank, col2+=date)
    # Row 1: Teachers (col0=blank, col1=Интервал, col2+=teacher name)
    teachers = []
    teacher_cols = [] # Map column index to teacher name
    
    # Process Row 1 to find teachers. They start from col 2 (idx 2)
    header_cells = rows[1].css('td, th')
    for idx, cell in enumerate(header_cells):
        txt = cell.text(strip=True).replace('\xa0', ' ')
        if idx >= 2 and txt:
            teachers.append(txt)
            teacher_cols.append((idx, txt))

    current_date = None
    results = []
    
    # Map pair numbers to time slots
    TIME_SLOTS = config.TIME_SLOTS
    
    for row in rows[2:]:
        cells = row.css('td, th')
        if not cells:
            continue
            
        time_cell_idx = 0
        
        # Check if first cell has a date
        day_text = cells[0].text(strip=True)
        date_match = re.search(r'(\d{2}\.\d{2}\.\d{2,4})', day_text)
        
        if date_match:
            try:
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
        time_cell = cells[time_cell_idx].text(strip=True)
        if not re.match(r'\d{2}:\d{2}-\d{2}:\d{2}', time_cell):
            continue
            
        start_time = time_cell.split('-')[0]
        end_time = time_cell.split('-')[1] if '-' in time_cell else None
        pair_num = TIME_SLOTS.get(start_time)

        # Process teachers columns
        for col_idx, teacher_name in teacher_cols:
            if col_idx >= len(cells):
                continue
                
            cell = cells[col_idx]
            cell_html = cell.html or ""
            # Replace <br> tags with newline to separate multiple items inside a single cell
            cell_text = re.sub(r'<br\s*/?>', '\n', cell_html)
            cell_text = re.sub(r'<[^>]+>', '', cell_text).replace('\xa0', ' ')
            lines = [l.strip() for l in cell_text.split('\n') if l.strip()]
            if not lines:
                continue
            
            for line in lines:
                entry = parse_teacher_cell_entry(line)
                results.append(Lesson(
                    group_name=entry['groups_str'] or "Не указана",
                    date=current_date.isoformat(),
                    pair_number=pair_num,
                    start_time=start_time,
                    end_time=end_time,
                    teacher=teacher_name,
                    building=entry['building'],
                    room=entry['room'],
                    class_type=entry['class_type'],
                    subject=entry['subject'],
                    raw_info=line
                ))

    return results

async def update_all_teachers_data():
    """
    (Optional/Internal) Scans all reports and caches teacher names.
    Since reports are dynamic, we perform on-demand lookup instead.
    """
    pass
