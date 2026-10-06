import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import List, Dict, Tuple, Optional, Set
from urllib.parse import urljoin

import aiohttp
from selectolax.parser import HTMLParser
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import Session

from tgbot.config import config
from tgbot.database.models import Lesson, TeacherCurriculum
from tgbot.services.parser.site_to_pdf import check_website_status

TEACHER_URL = config.TEACHER_URL
BASE_URL = config.VYATSU_BASE_URL
HEADERS = config.HTTP_HEADERS


def parse_period_dates(period_str: str) -> Tuple[Optional[date], Optional[date]]:
    """
    Parses 'c DD MM YYYY по DD MM YYYY' to (start_date, end_date).
    """
    m = re.search(r'c\s+(\d{2})\s+(\d{2})\s+(\d{4})\s+по\s+(\d{2})\s+(\d{2})\s+(\d{4})', period_str)
    if m:
        try:
            start_d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            end_d = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
            return start_d, end_d
        except ValueError:
            pass
    return None, None


async def get_teacher_navigation_data() -> List[Dict]:
    """
    Scrapes the teacher occupancy main page to get the hierarchy:
    Institute -> Faculty -> Department -> Report Links
    Extracts and pairs both HTML and XML/XLS links for each curriculum period.
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
                    html_map: Dict[str, Tuple[str, str]] = {}
                    xml_map: Dict[str, str] = {}
                    for a in list_period.css('a[href]'):
                        href = a.attributes.get('href', '')
                        if not href:
                            continue
                        clean_href = href.split('?')[0]
                        base_name = clean_href.rsplit('.', 1)[0]
                        ext = clean_href.rsplit('.', 1)[1].lower() if '.' in clean_href else ''
                        if ext == 'html':
                            html_map[base_name] = (a.text(strip=True), urljoin(BASE_URL, href))
                        elif ext in ('xls', 'xml', 'xlsx'):
                            xml_map[base_name] = urljoin(BASE_URL, href)

                    for base, (p_text, h_url) in html_map.items():
                        x_url = xml_map.get(base)
                        if not x_url:
                            x_url = urljoin(BASE_URL, base + '.xls')
                        start_d, end_d = parse_period_dates(p_text)
                        reports.append({
                            "period": p_text,
                            "start_date": start_d.isoformat() if start_d else None,
                            "end_date": end_d.isoformat() if end_d else None,
                            "html_url": h_url,
                            "xml_url": x_url,
                            "url": h_url,
                        })
                
                if reports:
                    current_inst["faculties"][0]["departments"].append({
                        "name": dept_name,
                        "reports": reports
                    })

    return institutes


def find_active_teacher_reports(nav_data: List[Dict], target_date: Optional[date] = None) -> List[Tuple[str, str]]:
    """
    Returns a list of (dept_name, report_url) for the specified or current active period.
    """
    if target_date is None:
        target_date = date.today()
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
                    s_str = rep.get("start_date")
                    e_str = rep.get("end_date")
                    if s_str and e_str:
                        try:
                            start_d = date.fromisoformat(s_str)
                            end_d = date.fromisoformat(e_str)
                            if start_d <= target_date <= end_d:
                                selected_url = rep["url"]
                                break
                        except ValueError:
                            pass
                    else:
                        start_d, end_d = parse_period_dates(rep.get("period", ""))
                        if start_d and end_d and start_d <= target_date <= end_d:
                            selected_url = rep["url"]
                            break
                
                if not selected_url and reports:
                    selected_url = reports[0]["url"]
                    
                if selected_url:
                    active_reports.append((dept_name, selected_url))
                    
    return active_reports


def parse_teacher_cell_entry(raw_line: str) -> Dict:
    """Parses a single line from a teacher report cell into structured components."""
    room_match = re.search(r'(\d{1,2}|ФОК|Гл\.[^\s_]*)\s*-\s*([^\s_]+)', raw_line)
    bld, aud = '', ''
    clean_line = raw_line
    if room_match:
        bld = room_match.group(1).strip()
        aud = room_match.group(2).strip(' _')
        clean_line = clean_line[:room_match.start()] + ' ' + clean_line[room_match.end():]
    
    clean_line = clean_line.strip(' _')
    
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


def extract_teachers_from_html_report(html: bytes | str) -> List[str]:
    """Extracts unique teacher names from Row 1 header cells of a department report."""
    tree = HTMLParser(html)
    table = tree.css_first('table')
    if not table:
        return []
    rows = table.css('tr')
    if len(rows) < 2:
        return []
    header_cells = rows[1].css('td, th')
    teachers = []
    for idx, cell in enumerate(header_cells):
        txt = cell.text(strip=True).replace('\xa0', ' ')
        if idx >= 2 and txt:
            teachers.append(txt)
    return teachers


def parse_teacher_html_report(html: bytes | str, dept_name: str) -> List[Lesson]:
    """
    Parses a department teacher report using fast selectolax parser.
    """
    tree = HTMLParser(html)
    table = tree.css_first('table')
    if not table:
        return []

    rows = table.css('tr')
    if len(rows) < 3:
        return []

    teachers = []
    teacher_cols = []
    
    header_cells = rows[1].css('td, th')
    for idx, cell in enumerate(header_cells):
        txt = cell.text(strip=True).replace('\xa0', ' ')
        if idx >= 2 and txt:
            teachers.append(txt)
            teacher_cols.append((idx, txt))

    current_date = None
    results = []
    TIME_SLOTS = config.TIME_SLOTS
    
    for row in rows[2:]:
        cells = row.css('td, th')
        if not cells:
            continue
            
        time_cell_idx = 0
        day_text = cells[0].text(strip=True)
        date_match = re.search(r'(\d{2}\.\d{2}\.\d{2,4})', day_text)
        
        if date_match:
            try:
                date_str = date_match.group(1)
                fmt = '%d.%m.%y' if len(date_str.split('.')[2]) == 2 else '%d.%m.%Y'
                current_date = datetime.strptime(date_str, fmt).date()
            except ValueError:
                pass
            time_cell_idx = 1
            
        if not current_date:
            continue
            
        if time_cell_idx >= len(cells):
            continue

        time_cell = cells[time_cell_idx].text(strip=True)
        if not re.match(r'\d{2}:\d{2}-\d{2}:\d{2}', time_cell):
            continue
            
        start_time = time_cell.split('-')[0]
        end_time = time_cell.split('-')[1] if '-' in time_cell else None
        pair_num = TIME_SLOTS.get(start_time)

        for col_idx, teacher_name in teacher_cols:
            if col_idx >= len(cells):
                continue
                
            cell = cells[col_idx]
            cell_html = cell.html or ""
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


class TeacherMappingManager:
    """
    Manages automatic, dynamic mapping of teachers to their curriculum reports (HTML and XML/XLS links).
    Automatically maps teachers after the first search, persists mapping into SQLite, and provides
    fast sub-second lookups for subsequent queries.
    """
    def __init__(self):
        self._is_mapped: bool = False
        self._mapped_at: float = 0.0
        self._lock = asyncio.Lock()
        
        # In-memory mapping structures:
        # teacher_name -> Set[department_name]
        self._teacher_to_depts: Dict[str, Set[str]] = {}
        # dept_name -> List of curriculum report dicts (period, html_url, xml_url, start_date, end_date)
        self._dept_to_reports: Dict[str, List[Dict]] = {}
        # teacher_name -> List of curriculum report dicts
        self._teacher_to_reports: Dict[str, List[Dict]] = {}
        # Sorted list of unique teacher names
        self._teacher_names: List[str] = []
        # report_url -> List[Lesson]
        self._report_lessons_cache: Dict[str, List[Lesson]] = {}
        # teacher_name -> (timestamp, List[dict])
        self._teacher_lessons_cache: Dict[str, Tuple[float, List[dict]]] = {}

    def is_mapped(self) -> bool:
        return self._is_mapped and (time.time() - self._mapped_at < 12 * 3600)

    async def load_from_db(self, engine=None) -> bool:
        """Loads cached mapping from SQLite teacher_curriculum table."""
        if engine is None:
            engine = create_engine(f"sqlite:///{config.DB_NAME}")

        def _sync_load():
            with Session(engine) as session:
                stmt = select(TeacherCurriculum)
                return list(session.execute(stmt).scalars().all())

        try:
            records = await asyncio.to_thread(_sync_load)
            if not records:
                return False

            self._teacher_to_depts.clear()
            self._teacher_to_reports.clear()
            self._dept_to_reports.clear()

            for rec in records:
                t = rec.teacher
                d = rec.department
                self._teacher_to_depts.setdefault(t, set()).add(d)
                rep = {
                    "period": rec.period,
                    "start_date": rec.start_date,
                    "end_date": rec.end_date,
                    "html_url": rec.html_url,
                    "xml_url": rec.xml_url,
                    "url": rec.html_url,
                    "department": d,
                }
                self._dept_to_reports.setdefault(d, []).append(rep)
                self._teacher_to_reports.setdefault(t, []).append(rep)

            self._teacher_names = sorted(list(self._teacher_to_depts.keys()))
            self._is_mapped = True
            self._mapped_at = time.time()
            logging.info(f"✅ Loaded {len(self._teacher_names)} mapped teachers from database.")
            return True
        except Exception as e:
            logging.debug(f"Failed to load teacher curriculum from DB: {e}")
            return False

    async def build_dynamic_mapping(self, progress=None, force: bool = False, engine=None) -> bool:
        """
        Dynamically scrapes university teacher pages, maps teachers to their
        departments and all curriculum HTML/XML reports, and persists to database.
        """
        async with self._lock:
            if not force and self.is_mapped():
                return True

            if progress:
                await progress.report("🔍 Сканирую кафедры и учебные планы ВятГУ...", 0.15)

            nav_data = await get_teacher_navigation_data()
            if not nav_data:
                logging.error("Failed to fetch teacher navigation data for mapping.")
                return False

            # 1. Populate department curriculum reports (all periods with html & xml/xls links)
            dept_reports_map: Dict[str, List[Dict]] = {}
            for inst in nav_data:
                for fac in inst.get("faculties", []):
                    for dept in fac.get("departments", []):
                        d_name = dept.get("name", "")
                        reps = dept.get("reports", [])
                        if d_name and reps:
                            for r in reps:
                                r["department"] = d_name
                            dept_reports_map[d_name] = reps

            self._dept_to_reports = dept_reports_map

            # 2. Find active reports for all departments to extract teachers and current lessons
            active_reports = find_active_teacher_reports(nav_data)
            if not active_reports:
                logging.warning("No active teacher reports found.")
                return False

            if progress:
                await progress.report(f"⏳ Сканирую {len(active_reports)} кафедр для построения карты преподавателей...", 0.35)

            sem = asyncio.Semaphore(25)
            async with aiohttp.ClientSession(
                headers=config.HTTP_HEADERS,
                connector=aiohttp.TCPConnector(limit=30)
            ) as session:
                async def fetch_dept_info(d_name: str, url: str):
                    async with sem:
                        try:
                            async with session.get(url, timeout=12) as resp:
                                if resp.status == 200:
                                    html_bytes = await resp.read()
                                    teachers = extract_teachers_from_html_report(html_bytes)
                                    lessons = parse_teacher_html_report(html_bytes, d_name)
                                    return d_name, url, teachers, lessons
                        except Exception as e:
                            logging.debug(f"Error scanning department {d_name}: {e}")
                        return d_name, url, [], []

                tasks = [fetch_dept_info(d, u) for d, u in active_reports]
                dept_results = await asyncio.gather(*tasks)

            # 3. Associate teachers with departments and curriculum reports
            teacher_to_depts: Dict[str, Set[str]] = {}
            report_lessons_cache: Dict[str, List[Lesson]] = {}
            teacher_lessons_map: Dict[str, List[dict]] = {}

            for d_name, url, teachers, lessons in dept_results:
                if lessons:
                    report_lessons_cache[url] = lessons

                for t in teachers:
                    norm_t = t.strip()
                    if norm_t:
                        teacher_to_depts.setdefault(norm_t, set()).add(d_name)

                for l in lessons:
                    t_name = (l.teacher or "").strip()
                    if not t_name:
                        continue
                    teacher_lessons_map.setdefault(t_name, []).append({
                        "date": l.date,
                        "pair_number": l.pair_number,
                        "start_time": l.start_time,
                        "end_time": l.end_time,
                        "subject": l.subject,
                        "class_type": l.class_type,
                        "building": l.building,
                        "room": l.room,
                        "groups": l.group_name,
                        "raw_info": l.raw_info,
                        "teacher": l.teacher,
                    })

            self._teacher_to_depts = teacher_to_depts
            self._report_lessons_cache.update(report_lessons_cache)

            # Build teacher curriculum reports and DB records
            teacher_to_reports: Dict[str, List[Dict]] = {}
            db_records: List[TeacherCurriculum] = []
            today_iso = date.today().isoformat()

            for t_name, depts in teacher_to_depts.items():
                seen_periods = set()
                t_reports = []
                for d in depts:
                    for rep in self._dept_to_reports.get(d, []):
                        p_key = (rep.get("period"), rep.get("html_url"))
                        if p_key not in seen_periods:
                            seen_periods.add(p_key)
                            t_reports.append(rep)
                            db_records.append(TeacherCurriculum(
                                teacher=t_name,
                                department=d,
                                period=rep.get("period", ""),
                                start_date=rep.get("start_date"),
                                end_date=rep.get("end_date"),
                                html_url=rep.get("html_url", ""),
                                xml_url=rep.get("xml_url"),
                                last_updated=today_iso
                            ))
                t_reports.sort(key=lambda x: x.get("start_date") or "")
                teacher_to_reports[t_name] = t_reports

                if t_name in teacher_lessons_map:
                    deduped = []
                    seen_l = set()
                    for l in teacher_lessons_map[t_name]:
                        key = (l["date"], l["pair_number"], l["start_time"], l["subject"], l["class_type"], l["room"], l["groups"])
                        if key not in seen_l:
                            seen_l.add(key)
                            deduped.append(l)
                    self._teacher_lessons_cache[t_name] = (time.time(), deduped)

            self._teacher_to_reports = teacher_to_reports
            self._teacher_names = sorted(list(teacher_to_depts.keys()))
            self._is_mapped = True
            self._mapped_at = time.time()

            # 4. Save to database in thread
            if engine is None:
                engine = create_engine(f"sqlite:///{config.DB_NAME}")

            def _sync_save():
                with Session(engine) as session:
                    session.execute(delete(TeacherCurriculum))
                    session.add_all(db_records)
                    session.commit()

            try:
                await asyncio.to_thread(_sync_save)
                logging.info(f"✅ Saved {len(db_records)} teacher curriculum mappings to database.")
            except Exception as e:
                logging.error(f"Error saving teacher curriculum to DB: {e}")

            if progress:
                await progress.report(f"✅ Карта построена: {len(self._teacher_names)} преподавателей!", 0.9)

            return True

    async def ensure_mapping(self, progress=None, force: bool = False, engine=None) -> bool:
        """Ensures the teacher curriculum mapping is loaded or built."""
        if not force and self.is_mapped():
            return True
        if not force:
            loaded = await self.load_from_db(engine)
            if loaded and self.is_mapped():
                return True
        return await self.build_dynamic_mapping(progress=progress, force=force, engine=engine)

    def search_teachers(self, query: str) -> List[str]:
        """Fast substring search among all mapped teachers."""
        query_clean = query.strip().lower()
        if not query_clean:
            return []
        matches = [t for t in self._teacher_names if query_clean in t.lower()]
        matches.sort(key=lambda x: (
            0 if x.lower() == query_clean
            else 1 if x.lower().startswith(query_clean)
            else 2
        ))
        return matches

    def get_all_teacher_names(self) -> List[str]:
        """Returns all unique mapped teacher names."""
        return list(self._teacher_names)

    def get_teacher_department(self, teacher_name: str) -> Optional[str]:
        """Returns the primary department name for a teacher."""
        depts = self._teacher_to_depts.get(teacher_name)
        if depts:
            return next(iter(depts))
        return None

    def get_teacher_curriculum(self, teacher_name: str) -> List[Dict]:
        """Returns the list of all curriculum reports (HTML and XML/XLS) for a teacher."""
        if teacher_name in self._teacher_to_reports:
            return self._teacher_to_reports[teacher_name]
        for t, reps in self._teacher_to_reports.items():
            if t.lower() == teacher_name.lower():
                return reps
        return []

    def get_teacher_report_for_date(self, teacher_name: str, target_date: date) -> Optional[Dict]:
        """Finds the curriculum report (HTML and XML) for a teacher that covers target_date."""
        curriculum = self.get_teacher_curriculum(teacher_name)
        if not curriculum:
            return None

        for rep in curriculum:
            s_str = rep.get("start_date")
            e_str = rep.get("end_date")
            if s_str and e_str:
                try:
                    s_d = date.fromisoformat(s_str)
                    e_d = date.fromisoformat(e_str)
                    if s_d <= target_date <= e_d:
                        return rep
                except ValueError:
                    pass
            else:
                s_d, e_d = parse_period_dates(rep.get("period", ""))
                if s_d and e_d and s_d <= target_date <= e_d:
                    return rep

        return curriculum[0] if curriculum else None

    async def fetch_teacher_lessons(self, teacher_name: str, target_date: Optional[date] = None) -> List[dict]:
        """
        Ultra-fast fetcher for teacher lessons:
        Fetches ONLY the single department report corresponding to this teacher and
        target_date (or returns directly from memory cache).
        """
        now = time.time()
        if target_date is None:
            target_date = date.today()

        # 1. Check in-memory teacher lessons cache
        if teacher_name in self._teacher_lessons_cache:
            ts, cached = self._teacher_lessons_cache[teacher_name]
            if (now - ts) < 3600:
                return cached

        # 2. Ensure mapping is built
        if not self.is_mapped():
            await self.ensure_mapping()

        # 3. Find target curriculum report for this teacher
        rep = self.get_teacher_report_for_date(teacher_name, target_date)
        if rep and rep.get("html_url"):
            url = rep["html_url"]
            dept_name = rep.get("department") or self.get_teacher_department(teacher_name) or ""
            
            lessons = self._report_lessons_cache.get(url)
            if not lessons:
                try:
                    async with aiohttp.ClientSession(headers=config.HTTP_HEADERS) as session:
                        async with session.get(url, timeout=12) as resp:
                            if resp.status == 200:
                                html = await resp.read()
                                lessons = parse_teacher_html_report(html, dept_name)
                                self._report_lessons_cache[url] = lessons
                except Exception as e:
                    logging.debug(f"Error fetching specific report for {teacher_name}: {e}")

            if lessons:
                matched = [l for l in lessons if l.teacher and teacher_name.lower() in l.teacher.lower()]
                formatted = []
                seen_keys = set()
                for l in matched:
                    key = (l.date, l.pair_number, l.start_time, l.subject, l.class_type, l.room, l.group_name)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        formatted.append({
                            "date": l.date,
                            "pair_number": l.pair_number,
                            "start_time": l.start_time,
                            "end_time": l.end_time,
                            "subject": l.subject,
                            "class_type": l.class_type,
                            "building": l.building,
                            "room": l.room,
                            "groups": l.group_name,
                            "raw_info": l.raw_info,
                            "teacher": l.teacher,
                        })
                self._teacher_lessons_cache[teacher_name] = (now, formatted)
                return formatted

        # 4. Fallback if not found in mapping: scan active reports
        nav_data = await get_teacher_navigation_data()
        active_reports = find_active_teacher_reports(nav_data, target_date)
        sem = asyncio.Semaphore(25)
        async with aiohttp.ClientSession(
            headers=config.HTTP_HEADERS,
            connector=aiohttp.TCPConnector(limit=30)
        ) as session:
            async def fetch_fallback(d_name: str, u: str) -> List[Lesson]:
                async with sem:
                    try:
                        async with session.get(u, timeout=12) as resp:
                            if resp.status == 200:
                                html_data = await resp.read()
                                l_list = parse_teacher_html_report(html_data, d_name)
                                return [l for l in l_list if l.teacher and teacher_name.lower() in l.teacher.lower()]
                    except Exception:
                        pass
                    return []

            tasks = [fetch_fallback(d, u) for d, u in active_reports]
            batch_results = await asyncio.gather(*tasks)

        all_l = [l for sublist in batch_results for l in sublist]
        formatted = []
        seen_keys = set()
        for l in all_l:
            key = (l.date, l.pair_number, l.start_time, l.subject, l.class_type, l.room, l.group_name)
            if key not in seen_keys:
                seen_keys.add(key)
                formatted.append({
                    "date": l.date,
                    "pair_number": l.pair_number,
                    "start_time": l.start_time,
                    "end_time": l.end_time,
                    "subject": l.subject,
                    "class_type": l.class_type,
                    "building": l.building,
                    "room": l.room,
                    "groups": l.group_name,
                    "raw_info": l.raw_info,
                    "teacher": l.teacher,
                })

        self._teacher_lessons_cache[teacher_name] = (now, formatted)
        return formatted


teacher_mapping_manager = TeacherMappingManager()


async def update_all_teachers_data():
    """Forces dynamic mapping of all teachers and curriculum reports."""
    await teacher_mapping_manager.build_dynamic_mapping(force=True)
