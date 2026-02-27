import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
import hashlib
from typing import List

import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Occupancy, ProcessedFile

# Constants
INDEX_URL = "https://www.vyatsu.ru/studentu-1/spravochnaya-informatsiya/zanyatost-auditoriy.html"
BASE_URL = "https://www.vyatsu.ru/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Maps pair number to time interval identifier from the HTML
PAIR_INTERVALS = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8
}


def calculate_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def parse_html_table(html: bytes, building: str) -> List[Occupancy]:
    """
    Parses the HTML room occupancy table from VyatSU.
    
    Structure:
    - Row 0: date spans (e.g. "26.02.2026")  
    - Row 1: headers: col0=blank, col1="Интервал", col2+= room names like "2-100"
    - Data rows: col0=rotated day text, col1="N пара", col2+= "" (free) or group text (occupied)
    """
    results = []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        if not table:
            logging.warning(f"  No table found for building {building}")
            return []
        
        rows = table.find_all('tr')
        if len(rows) < 2:
            return []
        
        # Row 1 contains room headers (0-indexed: rows[1])
        header_row = rows[1]
        header_cells = header_row.find_all('td')
        
        # Build col_index -> room_name mapping (skip first 2: "День" and "Интервал")
        col_to_room = {}
        for col_idx, cell in enumerate(header_cells):
            text = cell.get_text(strip=True)
            # Room names match pattern like "2-100", "3-204а", "2-100_" (suffix variant)
            if re.match(r'^\d+-\d+[а-яА-Я_]*$', text):
                # Normalize: strip trailing underscores (variant rooms)
                room_clean = text.rstrip('_')
                col_to_room[col_idx] = room_clean
        
        if not col_to_room:
            logging.warning(f"  No room headers found for building {building}")
            return []
        
        logging.info(f"  Building {building}: found {len(col_to_room)} rooms")
        
        # Parse data rows (rows[2:])
        current_date = None
        
        for row in rows[2:]:
            cells = row.find_all('td')
            if not cells:
                continue
            
            # Check if this row has a date cell (col 0 with day text)
            day_cell = cells[0]
            day_text = day_cell.get_text(strip=True)
            # Day text looks like "Пн 16.02.26" or contains date
            date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', day_text)
            if date_match:
                d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
                year = int(y) if len(y) == 4 else 2000 + int(y)
                current_date = date(year, int(m), int(d))
            
            if not current_date:
                continue
            
            # Find pair number from col 1 (or first cell if no date cell)
            # "1 пара", "2 пара", etc.
            pair_num = None
            for cell in cells:
                cell_text = cell.get_text(strip=True)
                pair_match = re.match(r'^(\d)\s*пара', cell_text)
                if pair_match:
                    pair_num = int(pair_match.group(1))
                    break
            
            if pair_num is None:
                continue
            
            # Now read room occupancy cells
            for col_idx, room_name in col_to_room.items():
                if col_idx >= len(cells):
                    continue
                
                cell = cells[col_idx]
                cell_text = cell.get_text(strip=True)
                is_free = not cell_text or cell_text.lower() in ('none', 'nan', '')
                group_name = cell_text if not is_free else None
                
                results.append(Occupancy(
                    building=building,
                    room=room_name,
                    date=current_date,
                    pair_number=pair_num,
                    is_free=is_free,
                    group_name=group_name
                ))
        
        logging.info(f"  Building {building}: parsed {len(results)} occupancy records")
        return results
        
    except Exception as e:
        logging.error(f"  Error parsing HTML table for building {building}: {e}", exc_info=True)
        return []


def _sync_process_report(engine, building: str, report_url: str, new_hash: str, occupancy_data: List[Occupancy]):
    """Saves occupancy data to DB if the file hash changed."""
    filename = Path(report_url).name
    with Session(engine) as session:
        stmt = select(ProcessedFile).where(ProcessedFile.filename == filename)
        db_file = session.execute(stmt).scalar_one_or_none()
        
        if db_file and db_file.file_hash == new_hash:
            logging.debug(f"  Skipping {filename} (unchanged)")
            return False  # No change
        
        # Delete old occupancy records for this building/period and insert fresh ones
        # We determine the date range from the occupancy data
        if occupancy_data:
            dates_in_data = {o.date for o in occupancy_data}
            if dates_in_data:
                from sqlalchemy import delete
                min_date = min(dates_in_data).isoformat()
                max_date = max(dates_in_data).isoformat()
                session.execute(
                    delete(Occupancy).where(
                        Occupancy.building == building,
                        Occupancy.date >= min_date,
                        Occupancy.date <= max_date
                    )
                )
            session.add_all(occupancy_data)
        
        if db_file:
            db_file.file_hash = new_hash
        else:
            session.add(ProcessedFile(filename=filename, file_hash=new_hash, file_type='occupancy'))
        
        session.commit()
        return True


async def update_occupancy(engine=None):
    """
    Fetches the occupancy index page, finds all report links grouped by building,
    downloads the most recent report for each building, and stores parsed data in DB.
    """
    logging.info("🏢 Updating room occupancy data...")
    
    if engine is None:
        engine = create_engine(f"sqlite:///{config.DB_NAME}")
    
    # 1. Fetch the index page to get all report links
    async with aiohttp.ClientSession(headers=HEADERS) as http:
        try:
            async with http.get(INDEX_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logging.error(f"  Failed to fetch index page: HTTP {resp.status}")
                    return
                html_index = await resp.text(encoding='utf-8', errors='replace')
        except Exception as e:
            logging.error(f"  Error fetching occupancy index: {e}")
            return
        
        soup = BeautifulSoup(html_index, 'html.parser')
        
        # Find all .html report links
        # URL pattern: /reports/schedule/room/BUILDING_1_STARTDATE_ENDDATE.html
        all_links = soup.find_all('a', href=re.compile(r'/reports/schedule/room/\d+_\d+_\d+_\d+\.html'))
        
        if not all_links:
            logging.warning("  No occupancy report links found on index page!")
            return
        
        # Group links by building number (first digit in filename)
        from collections import defaultdict
        building_links = defaultdict(list)
        
        today = date.today()
        
        for link in all_links:
            href = link['href']
            fname = Path(href).name  # e.g. "2_1_16022026_01032026.html"
            parts = fname.replace('.html', '').split('_')
            if len(parts) < 4:
                continue
            
            building_num = parts[0]  # e.g. "2"
            
            # Parse the start and end dates from the filename
            try:
                start_str = parts[2]  # e.g. "16022026"
                end_str = parts[3]    # e.g. "01032026"
                start_date = datetime.strptime(start_str, '%d%m%Y').date()
                end_date = datetime.strptime(end_str, '%d%m%Y').date()
            except ValueError:
                continue
            
            # Only include reports that cover today or future (within 2 weeks)
            if end_date >= today - timedelta(days=1) and start_date <= today + timedelta(weeks=2):
                building_links[building_num].append((start_date, urljoin(BASE_URL, href)))
        
        if not building_links:
            logging.warning("  No current occupancy reports found (all expired?). Trying most recent...")
            # Fallback: take the first link per building
            for link in all_links:
                href = link['href']
                fname = Path(href).name
                parts = fname.replace('.html', '').split('_')
                if len(parts) >= 2:
                    building_links[parts[0]].append((date.min, urljoin(BASE_URL, href)))
        
        logging.info(f"  Found reports for buildings: {sorted(building_links.keys())}")
        
        # 2. For each building, process reports covering current period
        for building_num, reports in sorted(building_links.items()):
            # Sort by start date, most recent first  
            reports.sort(key=lambda x: x[0], reverse=True)
            
            for start_date, report_url in reports[:3]:  # Process up to 3 most recent per building
                try:
                    async with http.get(report_url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        if r.status != 200:
                            continue
                        content = await r.read()
                    
                    new_hash = calculate_hash(content)
                    occupancy_data = parse_html_table(content, building_num)
                    
                    updated = await asyncio.to_thread(
                        _sync_process_report, engine, building_num, report_url, new_hash, occupancy_data
                    )
                    if updated:
                        logging.info(f"  ✅ Building {building_num}: updated {len(occupancy_data)} records from {Path(report_url).name}")
                    
                except Exception as e:
                    logging.error(f"  Error processing {report_url}: {e}")
