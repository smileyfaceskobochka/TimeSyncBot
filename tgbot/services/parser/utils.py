import re

def clean_string(text):
    if not text: return ""
    text = str(text).replace('_', '').replace('\xa0', ' ').replace('\n', ' ').replace('\r', '')
    return ' '.join(text.split())

def parse_lesson_details(raw_info, group_name):
    """
    Парсит строку. Старается не ломать названия предметов типа 'Промпт-инжиниринг'.
    """
    if not raw_info:
        return (None, None, None, None, None, None)

    text = clean_string(raw_info)
    
    # 1. Удаляем название группы (и мусор после него: ", ")
    if group_name:
        clean_group = clean_string(group_name)
        # Удаляем "Группа", "Группа, " и т.д.
        text = re.sub(re.escape(clean_group) + r'[\s,]*', ' ', text, flags=re.IGNORECASE)

    # 2. Подгруппа (01 подгруппа, 1 п/г)
    subgroup = None
    subgroup_match = re.search(r'\b(\d{1,2})\s*(?:подгруппа|п/г)', text, re.IGNORECASE)
    if subgroup_match:
        subgroup = subgroup_match.group(1)
        text = text.replace(subgroup_match.group(0), ' ')

    # 3. Преподаватель (Фамилия И.О.)
    teacher = None
    # Строгий паттерн: С большой буквы, потом инициалы.
    teacher_pattern = re.compile(r'\b([А-ЯЁ][а-яё]+(?:\-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?)')
    teachers = teacher_pattern.findall(text)
    if teachers:
        # Исключаем "Лекция Л.А." и прочие ошибки
        valid_teachers = [t for t in teachers if "Лекция" not in t and "Лаб" not in t]
        if valid_teachers:
            teacher = ", ".join(valid_teachers)
            for t in valid_teachers:
                text = text.replace(t, ' ')

    # 4. Аудитория (Корпус-Кабинет)
    # СДЕЛАНО СТРОЖЕ: Первая часть должна быть цифрой или спец. сокращением (ФОК, Гл), 
    # чтобы не кушать "Промпт-инжиниринг".
    building = None
    room = None
    
    # Паттерн: (Цифры или ФОК) - (Цифры с буквой)
    # Пример: 1-534, 14-305а, ФОК-Зал
    loc_pattern = re.compile(r'\b(\d{1,2}|ФОК|Гл\.|Спорт\.зал)\s*-\s*(\d{3,4}[а-яА-Я]?|[А-Яа-я]+)\b')
    loc_match = loc_pattern.search(text)
    if loc_match:
        building = loc_match.group(1)
        room = loc_match.group(2)
        text = text.replace(loc_match.group(0), ' ')

    # 5. Тип занятия
    class_type = None
    c_types = ["Лекция", "Практическое занятие", "Лабораторная работа", "Зачет", "Экзамен", "Консультация"]
    for ct in c_types:
        if ct.lower() in text.lower():
            class_type = ct
            text = re.sub(re.escape(ct), ' ', text, flags=re.IGNORECASE)
            break
            
    if not class_type:
        if "лаб." in text.lower(): class_type = "Лабораторная работа"
        elif "пр." in text.lower(): class_type = "Практическое занятие"
        elif "лек." in text.lower(): class_type = "Лекция"
        # Удаляем сокращения из текста
        text = re.sub(r'\b(лаб\.|пр\.|лек\.)', ' ', text, flags=re.IGNORECASE)

    # 6. Предмет - всё, что осталось
    subject = text.strip(" .,;").strip()
    subject = ' '.join(subject.split()) # Убрать двойные пробелы
    
    if len(subject) < 2: subject = None

    return (subject, class_type, teacher, building, room, subgroup)
