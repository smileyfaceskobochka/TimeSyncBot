import re
import hashlib

def calculate_hash(content: bytes) -> str:
    """Calculates MD5 hash for binary file content."""
    return hashlib.md5(content).hexdigest()

def clean_string(text):
    if not text: return ""
    text = str(text).replace('_', '').replace('\xa0', ' ').replace('\n', ' ').replace('\r', '')
    return ' '.join(text.split())

# Pre-compiled regexes for maximum parsing speed
RE_SUBGROUP = re.compile(r'\b(\d{1,2})\s*(?:подгруппа|п/г)', re.IGNORECASE)
RE_TEACHER = re.compile(r'\b([А-ЯЁ][а-яё]+(?:\-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?)')
RE_LOCATION = re.compile(r'\b(\d{1,2}|ФОК|Гл\.|Спорт\.зал)\s*-\s*(\d{3,4}[а-яА-Я]?|[А-Яа-я]+)\b')
RE_SHORT_CLASS_TYPES = re.compile(r'\b(лаб\.|пр\.|лек\.)', re.IGNORECASE)

CLASS_TYPES = [
    ("Лекция", re.compile(re.escape("Лекция"), re.IGNORECASE)),
    ("Практическое занятие", re.compile(re.escape("Практическое занятие"), re.IGNORECASE)),
    ("Лабораторная работа", re.compile(re.escape("Лабораторная работа"), re.IGNORECASE)),
    ("Зачет", re.compile(re.escape("Зачет"), re.IGNORECASE)),
    ("Экзамен", re.compile(re.escape("Экзамен"), re.IGNORECASE)),
    ("Консультация", re.compile(re.escape("Консультация"), re.IGNORECASE)),
]

def parse_lesson_details(raw_info, group_name):
    """
    Парсит строку с информацией о паре. Старается не ломать названия предметов типа 'Промпт-инжиниринг'.
    """
    if not raw_info:
        return (None, None, None, None, None, None)

    text = clean_string(raw_info)
    
    # 1. Удаляем название группы (и мусор после него: ", ")
    if group_name:
        clean_group = clean_string(group_name)
        text = re.sub(re.escape(clean_group) + r'[\s,]*', ' ', text, flags=re.IGNORECASE)

    # 2. Подгруппа (01 подгруппа, 1 п/г)
    subgroup = None
    subgroup_match = RE_SUBGROUP.search(text)
    if subgroup_match:
        subgroup = subgroup_match.group(1)
        text = text.replace(subgroup_match.group(0), ' ')

    # 3. Преподаватель (Фамилия И.О.)
    teacher = None
    teachers = RE_TEACHER.findall(text)
    if teachers:
        valid_teachers = [t for t in teachers if "Лекция" not in t and "Лаб" not in t]
        if valid_teachers:
            teacher = ", ".join(valid_teachers)
            for t in valid_teachers:
                text = text.replace(t, ' ')

    # 4. Аудитория (Корпус-Кабинет)
    building = None
    room = None
    loc_match = RE_LOCATION.search(text)
    if loc_match:
        building = loc_match.group(1)
        room = loc_match.group(2)
        text = text.replace(loc_match.group(0), ' ')

    # 5. Тип занятия
    class_type = None
    for ct_name, ct_re in CLASS_TYPES:
        if ct_re.search(text):
            class_type = ct_name
            text = ct_re.sub(' ', text)
            break
            
    if not class_type:
        text_lower = text.lower()
        if "лаб." in text_lower: class_type = "Лабораторная работа"
        elif "пр." in text_lower: class_type = "Практическое занятие"
        elif "лек." in text_lower: class_type = "Лекция"
        text = RE_SHORT_CLASS_TYPES.sub(' ', text)

    # 6. Предмет - всё, что осталось
    subject = text.strip(" .,;").strip()
    subject = ' '.join(subject.split()) # Убрать двойные пробелы
    
    if len(subject) < 2: subject = None

    return (subject, class_type, teacher, building, room, subgroup)
