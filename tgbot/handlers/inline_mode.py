import asyncio
import hashlib
import logging
from datetime import date, timedelta
from typing import List

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from tgbot.database.repositories import ScheduleRepository, UserRepository
from tgbot.services.services import ScheduleService
from tgbot.handlers.teacher import fetch_teacher_lessons, _format_teacher_day

inline_router = Router()

logger = logging.getLogger(__name__)


@inline_router.inline_query()
async def handle_inline_query(
    inline_query: InlineQuery,
    schedule_repo: ScheduleRepository,
    user_repo: UserRepository,
    service: ScheduleService
):
    """
    Handles inline queries like:
    @vyatsuts_bot
    @vyatsuts_bot ИВТб-1301
    @vyatsuts_bot Долженкова
    """
    query = inline_query.query.strip()
    logger.info(f"Inline query from {inline_query.from_user.id}: '{query}'")
    results = []
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # 1. Если запрос пустой — показываем персональное расписание пользователя
    if not query:
        user = await user_repo.get_user(inline_query.from_user.id)
        if user and user.group_name:
            # Сегодня
            lessons, is_pred = await schedule_repo.get_lessons_with_status(user.group_name, today)
            text_today = service.format_day(lessons, today, user.group_name, user.settings, is_predicted=is_pred)
            results.append(
                InlineQueryResultArticle(
                    id=f"my_today_{today.isoformat()}",
                    title=f"📅 {user.group_name} — Сегодня",
                    description="Отправить расписание вашей группы на сегодня",
                    input_message_content=InputTextMessageContent(
                        message_text=text_today,
                        parse_mode="HTML"
                    )
                )
            )
            # Завтра
            lessons_tmrw, is_pred_tmrw = await schedule_repo.get_lessons_with_status(user.group_name, tomorrow)
            text_tmrw = service.format_day(lessons_tmrw, tomorrow, user.group_name, user.settings, is_predicted=is_pred_tmrw)
            results.append(
                InlineQueryResultArticle(
                    id=f"my_tmrw_{tomorrow.isoformat()}",
                    title=f"📅 {user.group_name} — Завтра",
                    description="Отправить расписание вашей группы на завтра",
                    input_message_content=InputTextMessageContent(
                        message_text=text_tmrw,
                        parse_mode="HTML"
                    )
                )
            )

        results.append(
            InlineQueryResultArticle(
                id="help_hint",
                title="🔍 Поиск группы или преподавателя",
                description="Начните вводить название группы (ИВТб-1301) или фамилию преподавателя",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "🎓 <b>TimeSyncBot</b> — расписание ВятГУ прямо в этом чате!\n\n"
                        "Используйте: <code>@vyatsuts_bot [группа или преподаватель]</code>"
                    ),
                    parse_mode="HTML"
                )
            )
        )
        return await inline_query.answer(results, cache_time=10, is_personal=True)

    # 2. Поиск совпадений по группам
    found_groups = await schedule_repo.search_groups(query)
    logger.info(f"Found groups for '{query}': {found_groups}")
    for grp in found_groups[:3]:
        # Сегодня
        lessons, is_pred = await schedule_repo.get_lessons_with_status(grp, today)
        text_today = service.format_day(lessons, today, grp, None, is_predicted=is_pred)
        results.append(
            InlineQueryResultArticle(
                id=hashlib.md5(f"{grp}_today_{today.isoformat()}".encode()).hexdigest(),
                title=f"📅 {grp} — Сегодня",
                description=f"Расписание группы {grp} на сегодня",
                input_message_content=InputTextMessageContent(
                    message_text=text_today,
                    parse_mode="HTML"
                )
            )
        )

        # Завтра
        lessons_tmrw, is_pred_tmrw = await schedule_repo.get_lessons_with_status(grp, tomorrow)
        text_tmrw = service.format_day(lessons_tmrw, tomorrow, grp, None, is_predicted=is_pred_tmrw)
        results.append(
            InlineQueryResultArticle(
                id=hashlib.md5(f"{grp}_tmrw_{tomorrow.isoformat()}".encode()).hexdigest(),
                title=f"📅 {grp} — Завтра",
                description=f"Расписание группы {grp} на завтра",
                input_message_content=InputTextMessageContent(
                    message_text=text_tmrw,
                    parse_mode="HTML"
                )
            )
        )

    # 3. Поиск преподавателя
    # Сначала ищем по локальной базе данных (мгновенный ответ < 10 мс)
    found_teachers = await schedule_repo.search_teachers(query)
    logger.info(f"Found teachers in DB for '{query}': {found_teachers}")
    
    for t_name in found_teachers[:3]:
        if len(results) >= 8:
            break
        t_lessons = await schedule_repo.get_lessons_for_teacher(t_name)
        dict_lessons = [{
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
        } for l in t_lessons]

        # Сегодня
        text_today = _clip(_format_teacher_day(t_name, dict_lessons, today))
        results.append(
            InlineQueryResultArticle(
                id=hashlib.md5(f"teach_{t_name}_today_{today.isoformat()}".encode()).hexdigest(),
                title=f"👨‍🏫 {t_name} — Сегодня",
                description=f"Расписание преподавателя {t_name} на сегодня",
                input_message_content=InputTextMessageContent(
                    message_text=text_today,
                    parse_mode="HTML"
                )
            )
        )
        # Завтра
        text_tmrw = _clip(_format_teacher_day(t_name, dict_lessons, tomorrow))
        results.append(
            InlineQueryResultArticle(
                id=hashlib.md5(f"teach_{t_name}_tmrw_{tomorrow.isoformat()}".encode()).hexdigest(),
                title=f"👨‍🏫 {t_name} — Завтра",
                description=f"Расписание преподавателя {t_name} на завтра",
                input_message_content=InputTextMessageContent(
                    message_text=text_tmrw,
                    parse_mode="HTML"
                )
            )
        )

    # Если в базе преподаватель не найден и результатов мало — пробуем кэш и быстрый онлайн-поиск (до 1.5 сек)
    if not found_teachers and len(query) >= 3 and len(results) < 8:
        from tgbot.handlers.teacher import _teacher_lessons_cache
        cached_matches = [
            (name, data[1]) for name, data in _teacher_lessons_cache.items()
            if query.lower() in name.lower()
        ]
        if cached_matches:
            for teacher_name, t_lessons in cached_matches[:3]:
                if len(results) >= 8:
                    break
                text_teach = _clip(_format_teacher_day(teacher_name, t_lessons, today))
                results.append(
                    InlineQueryResultArticle(
                        id=hashlib.md5(f"teach_cache_{teacher_name}_{today.isoformat()}".encode()).hexdigest(),
                        title=f"👨‍🏫 {teacher_name} — Сегодня",
                        description=f"Расписание преподавателя {teacher_name} на сегодня (из кэша)",
                        input_message_content=InputTextMessageContent(
                            message_text=text_teach,
                            parse_mode="HTML"
                        )
                    )
                )
        else:
            try:
                teacher_lessons = await asyncio.wait_for(
                    fetch_teacher_lessons(query), timeout=1.8
                )
                if teacher_lessons:
                    by_teacher = {}
                    for lesson in teacher_lessons:
                        name = (lesson.get("teacher") or query).strip() or query
                        by_teacher.setdefault(name, []).append(lesson)
                    for teacher_name in sorted(by_teacher.keys())[:3]:
                        if len(results) >= 8:
                            break
                        text_teach = _clip(_format_teacher_day(teacher_name, by_teacher[teacher_name], today))
                        results.append(
                            InlineQueryResultArticle(
                                id=hashlib.md5(f"teach_net_{teacher_name}_{today.isoformat()}".encode()).hexdigest(),
                                title=f"👨‍🏫 {teacher_name} — Сегодня",
                                description=f"Расписание преподавателя {teacher_name} на сегодня",
                                input_message_content=InputTextMessageContent(
                                    message_text=text_teach,
                                    parse_mode="HTML"
                                )
                            )
                        )
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Quick teacher network search skipped/timed out: {e}")

    # 4. Никогда не отвечаем пустотой: иначе клиент показывает «нет результатов»
    # и кажется, что инлайн «не работает» (кейс @vyatsuts_bot Долженкова).
    if not results:
        results.append(
            InlineQueryResultArticle(
                id=hashlib.md5(f"nores_{query}_{today.isoformat()}".encode()).hexdigest(),
                title="😕 Ничего не найдено",
                description="Попробуйте уточнить группу или фамилию, либо откройте бота для поиска",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"🔍 По запросу <b>{query}</b> ничего не найдено.\n\n"
                        "Попробуйте ввести название группы (например, <code>ИВТб-1301</code>) "
                        "или фамилию преподавателя точнее, либо откройте бота и используйте /teacher."
                    ),
                    parse_mode="HTML"
                )
            )
        )
        logger.info(f"Returning fallback inline result for query: '{query}'")
        return await inline_query.answer(results, cache_time=5, is_personal=True)

    logger.info(f"Returning {len(results)} inline results for query: '{query}'")
    try:
        await inline_query.answer(results[:10], cache_time=30, is_personal=False)
    except Exception as e:
        # Чаще всего — слишком длинный текст статьи. Урезаем и пробуем ещё раз,
        # чтобы инлайн в любом случае что-то показал.
        logger.error(f"Inline answer failed, retrying truncated: {e}", exc_info=True)
        truncated = []
        for r in results[:10]:
            content = r.input_message_content
            if isinstance(content, InputTextMessageContent):
                truncated.append(
                    InlineQueryResultArticle(
                        id=r.id,
                        title=r.title,
                        description=r.description,
                        input_message_content=InputTextMessageContent(
                            message_text=_clip(content.message_text),
                            parse_mode="HTML"
                        )
                    )
                )
            else:
                truncated.append(r)
        await inline_query.answer(truncated, cache_time=10, is_personal=True)


def _clip(text: str, limit: int = 4000) -> str:
    """Обрезает текст статьи до лимита Telegram (4096 символов)."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n<i>…текст обрезан</i>"
