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
    "• Избранные группы\n"
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
@user_router.callback_query(F.data == "search_start")
async def search_start(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "🔎 Введите название группы для поиска (например: <b>ИВТб</b> или <b>ЮРб</b>):"
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
    
    if fast_results and not results:
        # Save results for toggles
        await state.update_data(search_results=fast_results, selected_groups=[])
        await message.answer(
            f"🔎 Группа <b>{message.text}</b> найдена в общем списке, но расписание ещё не загружено.\n"
            "Вы можете выбрать группы для загрузки:",
            reply_markup=get_group_selection_kb(fast_results, action="parse_ondemand")
        )
        return

    await message.answer(
        "🔎 Выберите вашу группу из списка:",
        reply_markup=get_group_selection_kb(results, action="change_group"),
    )

@user_router.callback_query(GroupSelectCb.filter(F.action == "change_group"))
async def change_group(
    callback: CallbackQuery,
    callback_data: GroupSelectCb,
    user_repo: UserRepository,
    analytics_repo: AnalyticsRepository,
    state: FSMContext,
):
    await analytics_repo.log_action(
        callback.from_user.id, "set_group", callback_data.name
    )
    
    user = await user_repo.get_user(callback.from_user.id)
    if not user:
        user = User(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )

    user.group_name = callback_data.name
    await user_repo.upsert_user(user)
    await state.clear()

    bot_settings = await user_repo.get_settings()
    await callback.message.edit_text(
        f"✅ Ваша группа успешно установлена: <b>{callback_data.name}</b>",
        reply_markup=get_main_menu(user, bot_settings),
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
    
    # Обновляем клавиатуру
    # Нам нужно знать исходный список результатов поиска. 
    # Сохраним его в стейте при первом поиске.
    results = data.get("search_results", [])
    
    await callback.message.edit_reply_markup(
        reply_markup=get_group_selection_kb(results, action="toggle_parse", selected_groups=selected)
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