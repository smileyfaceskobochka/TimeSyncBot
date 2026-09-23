from datetime import date
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from tgbot.config import config
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from typing import Union
from tgbot.database.models import User
from tgbot.database.repositories import (
    UserRepository,
    ScheduleRepository,
    AnalyticsRepository,
)
from tgbot.services.parser.runner import run_pipeline
from tgbot.services.services import ScheduleService
from tgbot.services.utils import parse_date
from tgbot.states.states import RegState, FavState
from tgbot.keyboards.inline import get_main_menu, get_group_selection_kb, get_schedule_hub_kb
from tgbot.keyboards.callback_data import GroupSelectCb
from tgbot.services.rate_limiter import parser_rate_limiter

user_router = Router()

@user_router.message(Command("meet"))
async def cmd_meet(
    message: Message, 
    schedule_repo: ScheduleRepository, 
    service: ScheduleService
):
    """
    Использование: /meet Группа1 Группа2 [Группа3...] [Дата]
    Пример: /meet ИВТб ПИб
    Пример 2: /meet ИВТб ПИб 25.10
    """
    args = message.text.split()[1:] # Убираем саму команду /meet
    
    if len(args) < 2:
        return await message.answer(
            "⚠️ Использование: <code>/meet Группа1 Группа2 [Дата]</code>\n"
            "Пример: <code>/meet ИВТб ПИб</code>"
        )
    
    # Пытаемся понять, является ли последний аргумент датой
    target_date = parse_date(args[-1])
    
    if target_date:
        # Если последний аргумент — дата, группы — это всё, что до него
        group_names = args[:-1]
    else:
        # Иначе дата = сегодня, а все аргументы — это группы
        target_date = date.today()
        group_names = args

    # Проверяем, существуют ли такие группы в базе
    valid_groups = []
    for g in group_names:
        # Используем уже существующий метод поиска групп (чтобы ИВТб находило ИВТб-1201-01-00)
        found = await schedule_repo.search_groups(g)
        if found:
            # Берем самое точное совпадение
            valid_groups.append(found[0]) 
        else:
            return await message.answer(f"❌ Группа <b>{g}</b> не найдена в базе.")

    if len(valid_groups) < 2:
         return await message.answer("⚠️ Необходимо минимум 2 группы для сравнения.")

    # Вызываем нашу новую функцию
    result_text = await service.find_common_free_slots(schedule_repo, valid_groups, target_date)
    
    await message.answer(result_text)
# ================= БАЗОВАЯ ЛОГИКА ГЛАВНОГО МЕНЮ =================
async def show_main_menu(
    target: Union[Message, CallbackQuery],
    user: User,
    bot_settings: dict,
    state: FSMContext
):
    """Универсальная функция для показа главного меню"""
    await state.clear()

    if user and user.group_name:

        text = f"Главное меню\nГруппа: {user.group_name}"
        reply_markup = get_main_menu(user, bot_settings)

        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)
        else:  # CallbackQuery
            try:
                await target.message.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
            await target.answer()
    else:
        text = "👋 Привет! Я умный бот, помогающий жизни студентам и кураторам ВятГУ.\n\nВведите название вашей группы (например: <b>ИВТб-1201-01-00</b> или просто <b>ИВТб</b>):"

        if isinstance(target, Message):
            await target.answer(text)
        else:  # CallbackQuery
            try:
                await target.message.edit_text(text)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
            await target.answer()

        await state.set_state(RegState.search_group)


HELP_TEXT = (
    "<b>Возможности бота:</b>\n"
    "• Просмотр расписания на день/неделю\n"
    "• Поиск свободных аудиторий\n"
    "• Поиск преподавателей\n"
    "• Общие окна (Встречи)\n"
    "• Избранные группы и преподаватели\n"
    "• Отзывы и предложения\n"
    "• Настройки отображения\n\n"
    "Техническая поддержка: <a href='https://t.me/VNech3kcs'>@VNech3kcs</a>\n\n"
)

# ================= ОБРАБОТЧИК КОМАНДЫ /start =================
@user_router.message(Command("start"))
async def cmd_start(
    message: Message,
    user_repo: UserRepository,
    state: FSMContext,
):
    user = await user_repo.get_user(message.from_user.id)
    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        await user_repo.upsert_user(user)
        
    bot_settings = await user_repo.get_settings()
    await show_main_menu(message, user, bot_settings, state)

# ================= ОБРАБОТЧИК КОМАНДЫ /help =================
@user_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)

@user_router.callback_query(F.data == "cmd_help")
async def callback_cmd_help(callback: CallbackQuery, user_repo: UserRepository):
    user = await user_repo.get_user(callback.from_user.id)
    try:
        await callback.message.edit_text(HELP_TEXT, reply_markup=get_main_menu(user, {}))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Message already shows the help text, just acknowledge the click
            await callback.answer("ℹ️ Это справка о возможностях бота")
        else:
            raise
    else:
        await callback.answer()

# ================= ОБРАБОТЧИК КНОПКИ "Главное меню" =================
@user_router.callback_query(F.data == "cmd_start")
async def callback_cmd_start(
    callback: CallbackQuery,
    user_repo: UserRepository,
    state: FSMContext,
):
    user = await user_repo.get_user(callback.from_user.id)
    bot_settings = await user_repo.get_settings()
    await show_main_menu(callback, user, bot_settings, state)


# ================= ПОИСК И СМЕНА ГРУППЫ =================
@user_router.message(Command("search"))
async def cmd_search_start(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Отмена", callback_data="cmd_start"))
    await message.answer(
        "🔎 <b>Поиск расписания группы</b>\n\n"
        "Введите название или часть названия группы (например: <b>ИВТб-4301</b> или просто <b>ИВТб</b>):",
        reply_markup=builder.as_markup()
    )
    await state.set_state(RegState.search_group)


@user_router.callback_query(F.data == "search_start")
async def search_start(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Отмена", callback_data="cmd_start"))
    try:
        await callback.message.edit_text(
            "🔎 <b>Поиск расписания группы</b>\n\n"
            "Введите название или часть названия группы (например: <b>ИВТб-4301</b> или просто <b>ИВТб</b>):",
            reply_markup=builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await state.set_state(RegState.search_group)


@user_router.message(RegState.search_group)
async def process_group_search(
    message: Message,
    schedule_repo: ScheduleRepository,
    state: FSMContext,
    analytics_repo: AnalyticsRepository,
):
    await analytics_repo.log_action(
        message.from_user.id, "search_group", message.text.strip()
    )
    results = await schedule_repo.search_groups(message.text.strip())
    
    # Fallback: if no active lessons found, search in general university list
    fast_results = await schedule_repo.search_tracked_groups(message.text.strip())
    
    if not results and not fast_results:
        # Auto-recovery: If DB is empty because startup sync failed, try to sync now
        tracked_count = await schedule_repo.get_tracked_groups_count()
        if tracked_count == 0:
            from tgbot.services.parser.site_to_pdf import sync_groups_list
            sync_msg = await message.answer("🔄 Загрузка списка групп с сайта ВятГУ, пожалуйста, подождите...")
            sync_ok = await sync_groups_list() # Uses default config.DB_NAME 
            await sync_msg.delete()
            if sync_ok:
                fast_results = await schedule_repo.search_tracked_groups(message.text.strip())
                
        if not results and not fast_results:
            # Проверяем, не связано ли это с недоступностью сайта
            from tgbot.services.parser.site_to_pdf import check_website_status
            is_available, status_code, error_msg = await check_website_status()
            if not is_available:
                return await message.answer(
                    f"🌐 Сайт ВятГУ временно недоступен ({error_msg}).\n"
                    "Поиск групп сейчас невозможен. Попробуйте позже."
                )
            return await message.answer(
                "⚠️ Группы не найдены. Попробуйте ввести название точнее (например: ИВТб)."
            )
    
    # Show all matching groups from university catalogue with pagination
    groups_to_show = fast_results if fast_results else results
    await state.update_data(search_results=groups_to_show, search_action="change_group", current_page=1)
    await message.answer(
        f"🔎 Найдено групп: <b>{len(groups_to_show)}</b>. Выберите вашу группу:",
        reply_markup=get_group_selection_kb(groups_to_show, action="change_group", page=1),
    )

@user_router.callback_query(GroupSelectCb.filter(F.action == "page"))
async def paginate_groups(
    callback: CallbackQuery,
    callback_data: GroupSelectCb,
    state: FSMContext,
):
    """Перелистывание страниц в списке найденных групп"""
    data = await state.get_data()
    groups = data.get("search_results", [])
    if not groups:
        return await callback.answer("Список устарел. Выполните поиск заново.", show_alert=True)
    
    action = data.get("search_action", "change_group")
    selected_groups = data.get("selected_groups", [])
    new_page = callback_data.page
    
    await state.update_data(current_page=new_page)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_group_selection_kb(
                groups, 
                action=action, 
                selected_groups=selected_groups, 
                page=new_page
            )
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()

@user_router.callback_query(GroupSelectCb.filter(F.action == "change_group"))
async def change_group(
    callback: CallbackQuery,
    callback_data: GroupSelectCb,
    user_repo: UserRepository,
    schedule_repo: ScheduleRepository,
    analytics_repo: AnalyticsRepository,
    state: FSMContext,
):
    group_name = callback_data.name
    await analytics_repo.log_action(
        callback.from_user.id, "set_group", group_name
    )
    
    # Check if lessons exist for this group. If not, auto-download on demand!
    has_lessons = await schedule_repo.has_lessons_for_group(group_name)
    if not has_lessons:
        await schedule_repo.set_group_tracked(group_name, is_tracked=True)
        from tgbot.services.parser.progress import ProgressReporter
        progress = ProgressReporter(callback.message)
        await progress.report(f"⏳ Расписание для <b>{group_name}</b> загружается с сайта ВятГУ...", 0.1)
        try:
            from tgbot.services.parser.runner import run_pipeline
            from tgbot.database.repositories import DatabaseManager
            db_manager = DatabaseManager(config.DB_NAME)
            await run_pipeline(db_manager=db_manager, group_keywords=[group_name], progress=progress)
        except Exception as e:
            logging.error(f"Error fetching schedule on-demand for {group_name}: {e}")
            await callback.message.answer(f"⚠️ Не удалось загрузить расписание: {e}")

    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        user = User(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )

    # If first-time user (no primary group), set it as their primary group
    if not user.group_name:
        user.group_name = group_name
        await user_repo.upsert_user(user)

    await state.clear()

    # Show schedule for the selected group directly
    from datetime import date
    from tgbot.services.services import ScheduleService
    service = ScheduleService()
    today = date.today()
    lessons, is_predicted = await schedule_repo.get_lessons_with_status(group_name, today)
    settings = user.settings if user else None
    is_fav = bool(user and group_name in user.favorites)
    is_my = bool(user and user.group_name == group_name)

    await callback.message.edit_text(
        service.format_day(lessons, today, group_name, settings, is_predicted=is_predicted),
        reply_markup=get_schedule_hub_kb(group_name, is_favorite=is_fav, is_my_group=is_my),
    )


@user_router.callback_query(GroupSelectCb.filter(F.action == "toggle_parse"))
async def toggle_group_for_parsing(
    callback: CallbackQuery,
    callback_data: GroupSelectCb,
    state: FSMContext,
):
    """
    Тумблер для выбора групп в списке ВятГУ.
    """
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    
    group_name = callback_data.name
    if group_name in selected:
        selected.remove(group_name)
    else:
        selected.append(group_name)
    
    await state.update_data(selected_groups=selected)
    
    results = data.get("search_results", [])
    current_page = callback_data.page or data.get("current_page", 1)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_group_selection_kb(results, action="toggle_parse", selected_groups=selected, page=current_page)
    )
    await callback.answer()

@user_router.callback_query(GroupSelectCb.filter(F.action == "confirm_parse"))
async def confirm_multi_parse(
    callback: CallbackQuery,
    user_repo: UserRepository,
    schedule_repo: ScheduleRepository,
    state: FSMContext,
):
    """
    Запуск пакетной загрузки для всех выбранных групп.
    """
    data = await state.get_data()
    selected_groups = data.get("selected_groups", [])
    
    if not selected_groups:
        return await callback.answer("⚠️ Выберите хотя бы одну группу!", show_alert=True)
    
    # 1. Check rate limit
    is_allowed, remaining = parser_rate_limiter.check_limit(callback.from_user.id)
    if not is_allowed:
        minutes = remaining // 60
        seconds = remaining % 60
        return await callback.answer(
            f"⏳ Пожалуйста, подождите {minutes} мин {seconds} сек перед следующим запросом расписания.", 
            show_alert=True
        )

    # 1. Помечаем группы как отслеживаемые
    for group_name in selected_groups:
        await schedule_repo.set_group_tracked(group_name, is_tracked=True)
    
    # 2. Инициализируем прогресс-репортер
    from tgbot.services.parser.progress import ProgressReporter
    progress = ProgressReporter(callback.message)
    
    # 3. Запускаем пайплайн для списка групп
    num = len(selected_groups)
    await progress.report(f"⏳ Начинаю загрузку расписания для {num} групп...", 0.0)
    
    try:
        from tgbot.services.parser.runner import run_pipeline
        from tgbot.database.repositories import DatabaseManager
        db_manager = DatabaseManager(config.DB_NAME)
        # Мы обновим run_pipeline чтобы он принимал список
        await run_pipeline(db_manager=db_manager, group_keywords=selected_groups, progress=progress)
        
        # 4. Если выбрана была только одна группа, установим её как основную
        user = await user_repo.get_user(callback.from_user.id)
        if not user:
             from tgbot.database.models import User
             user = User(telegram_id=callback.from_user.id, username=callback.from_user.username, full_name=callback.from_user.full_name)
        
        if len(selected_groups) == 1:
            user.group_name = selected_groups[0]
            await user_repo.upsert_user(user)
            text = f"✅ Расписание для группы <b>{selected_groups[0]}</b> успешно загружено и установлено!"
        else:
            # Для нескольких групп просто уведомляем
            text = f"✅ Расписание для {len(selected_groups)} групп успешно загружено!"
            if not user.group_name:
                text += "\n\nНе забудьте установить свою основную группу через поиск."

        await state.clear()
        bot_settings = await user_repo.get_settings()
        await callback.message.edit_text(text, reply_markup=get_main_menu(user, bot_settings))

        parser_rate_limiter.record_usage(callback.from_user.id)

    except Exception as e:
        logging.error(f"Error in multi-group parsing: {e}")
        await callback.message.edit_text(f"❌ Произошла ошибка при загрузке: {e}")

@user_router.callback_query(GroupSelectCb.filter(F.action == "parse_ondemand"))
async def parse_group_ondemand(
    callback: CallbackQuery,
    callback_data: GroupSelectCb,
    user_repo: UserRepository,
    schedule_repo: ScheduleRepository, # FIX: use injected repo
    state: FSMContext,
):
    # Одиночный парсинг теперь тоже может идти через тумблеры, 
    # но если нажали конкретную кнопку "Загрузить его сейчас" из быстрого ответа,
    # мы можем либо сразу его запустить, либо перевести в режим выбора.
    # Для простоты - запустим сразу.
    
    # Check rate limit
    is_allowed, remaining = parser_rate_limiter.check_limit(callback.from_user.id)
    if not is_allowed:
        minutes = remaining // 60
        seconds = remaining % 60
        return await callback.answer(
            f"⏳ Пожалуйста, подождите {minutes} мин {seconds} сек перед следующим запросом расписания.", 
            show_alert=True
        )
        
    group_name = callback_data.name
    await schedule_repo.set_group_tracked(group_name, is_tracked=True)
    
    from tgbot.services.parser.progress import ProgressReporter
    progress = ProgressReporter(callback.message)
    
    await progress.report(f"⏳ Начинаю загрузку расписания для {group_name}...", 0.0)
    
    try:
        from tgbot.services.parser.runner import run_pipeline
        from tgbot.database.repositories import DatabaseManager
        db_manager = DatabaseManager(config.DB_NAME)
        await run_pipeline(db_manager=db_manager, group_keywords=[group_name], progress=progress)
        
        user = await user_repo.get_user(callback.from_user.id)
        if not user:
             from tgbot.database.models import User
             user = User(telegram_id=callback.from_user.id, username=callback.from_user.username, full_name=callback.from_user.full_name)
        
        user.group_name = group_name
        await user_repo.upsert_user(user)
        
        await state.clear()
        await callback.message.edit_text(
            f"✅ Расписание для группы <b>{group_name}</b> успешно загружено и установлено!",
            reply_markup=get_schedule_hub_kb(group_name)
        )
        parser_rate_limiter.record_usage(callback.from_user.id)
        
    except Exception as e:
        logging.error(f"Error in on-demand parsing: {e}")
        await callback.message.edit_text(f"❌ Произошла ошибка при загрузке: {e}")