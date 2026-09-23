import logging
from datetime import date, timedelta
from typing import List, Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ChatMemberUpdated, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgbot.config import config
from tgbot.database.models import GroupChat
from tgbot.database.repositories import GroupChatRepository, ScheduleRepository, AnalyticsRepository
from tgbot.keyboards.callback_data import GroupChatCb, GroupSelectCb
from tgbot.keyboards.inline import get_group_chat_settings_kb
from tgbot.services.services import ScheduleService

group_chat_router = Router()
# Filter all message events in this router to only apply to group and supergroup chats
group_chat_router.message.filter(F.chat.type.in_({"group", "supergroup"}))
group_chat_router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))

TIME_OPTIONS = ["06:30", "07:00", "07:30", "08:00", "19:00", "20:00", "21:00"]


async def _is_admin(
    bot: Bot, 
    chat_id: int, 
    user_id: int, 
    sender_chat_id: Optional[int] = None
) -> bool:
    """Checks if a user is an administrator of the Telegram group or a global bot admin"""
    if user_id in config.ADMIN_IDS:
        return True
    # Anonymous admin sending on behalf of the group itself
    if sender_chat_id and sender_chat_id == chat_id:
        return True
    # Telegram GroupAnonymousBot user ID
    if user_id == 1087968824:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ["creator", "administrator"]
    except Exception as e:
        logging.error(f"Error checking chat admin status for user {user_id} in chat {chat_id}: {e}")
        return False


# ================= ПРИВЕТСТВИЕ ПРИ ДОБАВЛЕНИИ В ЧАТ =================
@group_chat_router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def bot_added_to_group(event: ChatMemberUpdated):
    """Срабатывает при добавлении бота в группу или повышении прав"""
    welcome_text = (
        "👋 <b>Привет! Я бот расписания ВятГУ для студенческих групп.</b>\n\n"
        "Я могу ежедневно автоматически присылать расписание в этот чат и отвечать на команды участников.\n\n"
        "🔧 <b>Настройка для администратора:</b>\n"
        "Привяжите учебную группу командой:\n"
        "<code>/setgroup ИВТб-1302</code>\n\n"
        "<b>Команды в чате:</b>\n"
        "• /today — расписание на сегодня\n"
        "• /tomorrow — расписание на завтра\n"
        "• /week — расписание на неделю\n"
        "• /chat_settings — настройки времени и авторассылки"
    )
    await event.bot.send_message(chat_id=event.chat.id, text=welcome_text)


@group_chat_router.message(Command("start", "help"))
async def group_cmd_help(message: Message, group_chat_repo: GroupChatRepository):
    chat = await group_chat_repo.get_chat(message.chat.id)
    bound_str = f"<b>{chat.group_name}</b>" if chat else "<i>не привязана</i>"
    
    text = (
        f"🤖 <b>Бот расписания ВятГУ в чате</b>\n"
        f"Привязанная группа: {bound_str}\n\n"
        f"<b>Команды:</b>\n"
        f"• <code>/today</code> — расписание на сегодня\n"
        f"• <code>/tomorrow</code> — расписание на завтра\n"
        f"• <code>/week</code> — расписание на текущую неделю\n\n"
        f"<b>Для администраторов группы:</b>\n"
        f"• <code>/setgroup Название</code> — привязать группу (например, <code>/setgroup ИВТб-1302</code>)\n"
        f"• <code>/settopic</code> — привязать рассылку к теме супергруппы\n"
        f"• <code>/chat_settings</code> — настроить время авторассылки, тему и закрепление"
    )
    await message.answer(text)


# ================= ПРИВЯЗКА ГРУППЫ =================
@group_chat_router.message(Command("setgroup", "bind"))
async def cmd_set_group(
    message: Message, 
    bot: Bot, 
    schedule_repo: ScheduleRepository, 
    group_chat_repo: GroupChatRepository
):
    # Проверка прав администратора
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await _is_admin(bot, message.chat.id, message.from_user.id, sender_chat_id):
        return await message.reply("⛔ Привязывать учебную группу к чату могут только администраторы.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply(
            "ℹ️ <b>Укажите название группы</b>\n\n"
            "Пример: <code>/setgroup ИВТб-1302</code> или <code>/setgroup ЮРб-1901</code>"
        )

    query = args[1].strip()
    # Ищем в базе и в общем списке ВятГУ
    fast_results = await schedule_repo.search_tracked_groups(query)
    results = await schedule_repo.search_groups(query)
    all_matches = []
    for g in (fast_results + results):
        if g not in all_matches:
            all_matches.append(g)

    if not all_matches:
        return await message.reply(
            f"❌ Группа «{query}» не найдена в каталоге ВятГУ. Проверьте правильность написания."
        )

    # Если точное совпадение или ровно 1 результат
    exact_match = next((g for g in all_matches if g.lower() == query.lower()), None)
    if exact_match:
        chosen_group = exact_match
    elif len(all_matches) == 1:
        chosen_group = all_matches[0]
    else:
        # Несколько вариантов: выводим кнопки администратору
        builder = InlineKeyboardBuilder()
        for g in all_matches[:8]:
            builder.button(
                text=g,
                callback_data=GroupChatCb(action="bind_exact", value=g).pack()
            )
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=GroupChatCb(action="close").pack()))
        return await message.reply(
            f"🔍 По запросу «{query}» найдено несколько групп. Выберите нужную:",
            reply_markup=builder.as_markup()
        )

    await _finalize_bind_group(message, chosen_group, group_chat_repo, schedule_repo)


async def _finalize_bind_group(
    message: Message, 
    chosen_group: str, 
    group_chat_repo: GroupChatRepository, 
    schedule_repo: ScheduleRepository
):
    # Проверяем наличие занятий в БД, при необходимости загружаем
    has_lessons = await schedule_repo.has_lessons_for_group(chosen_group)
    if not has_lessons:
        await schedule_repo.set_group_tracked(chosen_group, is_tracked=True)
        from tgbot.services.parser.progress import ProgressReporter
        progress = ProgressReporter(message)
        await progress.report(f"⏳ Расписание для <b>{chosen_group}</b> загружается с сайта ВятГУ...", 0.1)
        try:
            from tgbot.services.parser.runner import run_pipeline
            from tgbot.database.repositories import DatabaseManager
            db_manager = DatabaseManager(config.DB_NAME)
            await run_pipeline(db_manager=db_manager, group_keywords=[chosen_group], progress=progress)
        except Exception as e:
            logging.error(f"Error fetching schedule on-demand for group chat: {e}")

    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        chat = GroupChat(
            chat_id=message.chat.id,
            title=message.chat.title or "Группа",
            group_name=chosen_group,
            auto_post=True,
            post_time="07:00",
            post_target="today",
            pin_message=False,
            topic_id=message.message_thread_id,
            pin_replies=False
        )
    else:
        chat.group_name = chosen_group
        chat.title = message.chat.title or chat.title
        chat.auto_post = True
        if message.message_thread_id and not chat.topic_id:
            chat.topic_id = message.message_thread_id

    await group_chat_repo.upsert_chat(chat)

    topic_str = f"\n💬 <b>Тема (топик):</b> привязано к этой теме (#{chat.topic_id})." if chat.topic_id else ""

    await message.answer(
        f"✅ <b>Группа {chosen_group} успешно привязана к чату!</b>\n\n"
        f"⏰ <b>Авторассылка:</b> включена каждое утро в <b>{chat.post_time}</b>.{topic_str}\n"
        f"📌 <b>Команды для участников:</b>\n"
        f"• <code>/today</code> — пары на сегодня\n"
        f"• <code>/tomorrow</code> — пары на завтра\n"
        f"• <code>/week</code> — расписание на неделю\n"
        f"• <code>/chat_settings</code> — изменить время или отключить рассылку"
    )


# ================= ПРИВЯЗКА ТЕМЫ (ТОПИКА) =================
@group_chat_router.message(Command("settopic", "topic"))
async def cmd_set_topic(
    message: Message,
    bot: Bot,
    group_chat_repo: GroupChatRepository
):
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await _is_admin(bot, message.chat.id, message.from_user.id, sender_chat_id):
        return await message.reply("⛔ Привязывать тему могут только администраторы чата.")

    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        return await message.reply(
            "⚠️ К этому чату ещё не привязана учебная группа.\n"
            "Сначала привяжите её: <code>/setgroup НазваниеГруппы</code>"
        )

    args = message.text.split(maxsplit=1)
    subcmd = args[1].lower().strip() if len(args) > 1 else ""

    if subcmd in ["off", "remove", "reset", "clear", "сброс", "откл"]:
        chat.topic_id = None
        await group_chat_repo.upsert_chat(chat)
        return await message.reply("ℹ️ Привязка к теме снята. Расписание будет отправляться в основной чат.")

    if not message.message_thread_id:
        return await message.reply(
            "ℹ️ <b>Как привязать тему (топик) для расписания:</b>\n\n"
            "1. Зайдите в нужную тему (топик) супергруппы.\n"
            "2. Отправьте в ней команду: <code>/settopic</code>\n\n"
            "Для снятия привязки: <code>/settopic off</code>"
        )

    chat.topic_id = message.message_thread_id
    await group_chat_repo.upsert_chat(chat)
    await message.reply(
        f"✅ <b>Тема успешно привязана!</b> (ID: <code>#{message.message_thread_id}</code>)\n"
        f"Ежедневная авторассылка и закрепление расписания будут происходить в этой теме."
    )


# ================= КОМАНДЫ РАСПИСАНИЯ В ГРУППЕ =================
@group_chat_router.message(Command("today", "schedule", "сегодня", "пары"))
async def cmd_group_today(
    message: Message, 
    group_chat_repo: GroupChatRepository, 
    schedule_repo: ScheduleRepository
):
    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        return await message.reply(
            "⚠️ К этому чату ещё не привязана учебная группа.\n"
            "Администратор может привязать её командой:\n<code>/setgroup НазваниеГруппы</code>"
        )

    service = ScheduleService()
    today = date.today()
    lessons, is_predicted = await schedule_repo.get_lessons_with_status(chat.group_name, today)
    text = service.format_day(lessons, today, chat.group_name, is_predicted=is_predicted)
    sent_msg = await message.answer(text)
    if chat and getattr(chat, 'pin_replies', False):
        try:
            await message.bot.pin_chat_message(
                chat_id=message.chat.id,
                message_id=sent_msg.message_id,
                disable_notification=True
            )
        except Exception as pin_err:
            logging.debug(f"Не удалось закрепить ответ в {message.chat.id}: {pin_err}")


@group_chat_router.message(Command("tomorrow", "завтра"))
async def cmd_group_tomorrow(
    message: Message, 
    group_chat_repo: GroupChatRepository, 
    schedule_repo: ScheduleRepository
):
    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        return await message.reply(
            "⚠️ К этому чату ещё не привязана учебная группа.\n"
            "Администратор может привязать её командой:\n<code>/setgroup НазваниеГруппы</code>"
        )

    service = ScheduleService()
    tmrw = date.today() + timedelta(days=1)
    lessons, is_predicted = await schedule_repo.get_lessons_with_status(chat.group_name, tmrw)
    text = service.format_day(lessons, tmrw, chat.group_name, is_predicted=is_predicted)
    sent_msg = await message.answer(text)
    if chat and getattr(chat, 'pin_replies', False):
        try:
            await message.bot.pin_chat_message(
                chat_id=message.chat.id,
                message_id=sent_msg.message_id,
                disable_notification=True
            )
        except Exception as pin_err:
            logging.debug(f"Не удалось закрепить ответ в {message.chat.id}: {pin_err}")


@group_chat_router.message(Command("week", "неделя"))
async def cmd_group_week(
    message: Message, 
    group_chat_repo: GroupChatRepository, 
    schedule_repo: ScheduleRepository
):
    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        return await message.reply(
            "⚠️ К этому чату ещё не привязана учебная группа.\n"
            "Администратор может привязать её командой:\n<code>/setgroup НазваниеГруппы</code>"
        )

    service = ScheduleService()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    text_parts = [
        f"📆 <b>Расписание на неделю ({monday.strftime('%d.%m')} — {sunday.strftime('%d.%m')})</b>\nГруппа: {chat.group_name}\n"
    ]

    has_any = False
    for i in range(7):
        day_date = monday + timedelta(days=i)
        lessons, is_predicted = await schedule_repo.get_lessons_with_status(chat.group_name, day_date)
        if lessons:
            has_any = True
            day_text = service.format_day(lessons, day_date, chat.group_name, is_predicted=is_predicted)
            text_parts.append(day_text)

    if not has_any:
        text_parts.append("🎉 На эту неделю занятий нет!")

    await message.answer("\n\n".join(text_parts))


def _get_settings_text(chat: GroupChat) -> str:
    topic_str = f"#{chat.topic_id}" if chat.topic_id else "Основной чат"
    pin_broadcast_str = "Да" if chat.pin_message else "Нет"
    pin_replies_str = "Да" if getattr(chat, 'pin_replies', False) else "Нет"
    return (
        f"⚙️ <b>Настройки расписания в группе:</b>\n"
        f"🔒 <i>Управление доступно только администраторам чата</i>\n\n"
        f"• <b>Учебная группа:</b> {chat.group_name}\n"
        f"• <b>Авторассылка:</b> {'Включена' if chat.auto_post else 'Выключена'}\n"
        f"• <b>Время рассылки:</b> {chat.post_time}\n"
        f"• <b>Отправлять:</b> {'на сегодня' if chat.post_target == 'today' else 'на завтра (вечером)'}\n"
        f"• <b>Тема (топик):</b> {topic_str}\n"
        f"• <b>Закреплять рассылку:</b> {pin_broadcast_str}\n"
        f"• <b>Закреплять ответы /today:</b> {pin_replies_str}\n\n"
        f"Используйте кнопки ниже для изменения параметров:"
    )


# ================= НАСТРОЙКИ ЧАТА =================
@group_chat_router.message(Command("chat_settings", "groupsettings", "settings"))
async def cmd_group_settings(
    message: Message, 
    bot: Bot, 
    group_chat_repo: GroupChatRepository
):
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    if not await _is_admin(bot, message.chat.id, message.from_user.id, sender_chat_id):
        return await message.reply("⛔ Настройки группы могут открывать только администраторы.")

    chat = await group_chat_repo.get_chat(message.chat.id)
    if not chat:
        return await message.reply(
            "⚠️ К этому чату ещё не привязана учебная группа.\n"
            "Сначала привяжите её: <code>/setgroup НазваниеГруппы</code>"
        )

    is_supergroup = (message.chat.type == "supergroup")
    await message.answer(
        _get_settings_text(chat), 
        reply_markup=get_group_chat_settings_kb(chat, is_supergroup=is_supergroup)
    )


# ================= CALLBACKS НАСТРОЕК =================
@group_chat_router.callback_query(GroupChatCb.filter())
async def handle_group_chat_callbacks(
    callback: CallbackQuery,
    callback_data: GroupChatCb,
    bot: Bot,
    group_chat_repo: GroupChatRepository,
    schedule_repo: ScheduleRepository
):
    sender_chat_id = callback.message.sender_chat.id if callback.message.sender_chat else None
    if not await _is_admin(bot, callback.message.chat.id, callback.from_user.id, sender_chat_id):
        logging.warning(
            f"Unauthorized settings change attempt by user {callback.from_user.id} in chat {callback.message.chat.id}"
        )
        return await callback.answer("⛔ Доступ запрещён: только администраторы группы могут изменять настройки.", show_alert=True)

    action = callback_data.action
    chat_id = callback.message.chat.id

    if action == "close":
        await callback.message.delete()
        return

    if action == "bind_exact":
        chosen_group = callback_data.value
        await callback.message.delete()
        await _finalize_bind_group(callback.message, chosen_group, group_chat_repo, schedule_repo)
        return

    chat = await group_chat_repo.get_chat(chat_id)
    if not chat:
        return await callback.answer("Чат не найден в базе.", show_alert=True)

    if action == "toggle_auto":
        chat.auto_post = not chat.auto_post
        await group_chat_repo.upsert_chat(chat)
        await callback.answer(f"Авторассылка: {'Включена' if chat.auto_post else 'Выключена'}")

    elif action == "cycle_time":
        current_idx = TIME_OPTIONS.index(chat.post_time) if chat.post_time in TIME_OPTIONS else 1
        next_idx = (current_idx + 1) % len(TIME_OPTIONS)
        chat.post_time = TIME_OPTIONS[next_idx]
        
        # Автоматически адаптируем цель отправки: вечернее время -> расписание на завтра
        if chat.post_time >= "19:00":
            chat.post_target = "tomorrow"
        else:
            chat.post_target = "today"
            
        await group_chat_repo.upsert_chat(chat)
        await callback.answer(f"Время рассылки: {chat.post_time}")

    elif action == "toggle_target":
        chat.post_target = "tomorrow" if chat.post_target == "today" else "today"
        await group_chat_repo.upsert_chat(chat)
        target_name = "на сегодня" if chat.post_target == "today" else "на завтра"
        await callback.answer(f"Отправка: {target_name}")

    elif action == "toggle_pin":
        chat.pin_message = not chat.pin_message
        await group_chat_repo.upsert_chat(chat)
        await callback.answer(f"Закрепление рассылки: {'Включено' if chat.pin_message else 'Выключено'}")

    elif action == "toggle_topic":
        thread_id = callback.message.message_thread_id
        if thread_id:
            if chat.topic_id == thread_id:
                chat.topic_id = None
                await group_chat_repo.upsert_chat(chat)
                await callback.answer("Тема сброшена. Сообщения будут приходить в основной чат.", show_alert=True)
            else:
                chat.topic_id = thread_id
                await group_chat_repo.upsert_chat(chat)
                await callback.answer(f"Рассылка привязана к этой теме (#{thread_id})!", show_alert=True)
        else:
            if chat.topic_id:
                chat.topic_id = None
                await group_chat_repo.upsert_chat(chat)
                await callback.answer("Привязка темы снята. Сообщения идут в основной чат.", show_alert=True)
            else:
                await callback.answer(
                    "ℹ️ Чтобы привязать топик: откройте /chat_settings внутри нужной темы или отправьте команду /settopic в ней.",
                    show_alert=True
                )

    elif action == "toggle_pin_replies":
        chat.pin_replies = not getattr(chat, 'pin_replies', False)
        await group_chat_repo.upsert_chat(chat)
        await callback.answer(f"Закрепление /today: {'Включено' if chat.pin_replies else 'Выключено'}")

    elif action == "send_now":
        service = ScheduleService()
        target_date = date.today()
        if chat.post_target == "tomorrow":
            target_date += timedelta(days=1)
            
        lessons, is_predicted = await schedule_repo.get_lessons_with_status(chat.group_name, target_date)
        text = service.format_day(lessons, target_date, chat.group_name, is_predicted=is_predicted)
        target_thread = chat.topic_id or callback.message.message_thread_id
        sent_msg = await bot.send_message(
            chat_id=chat.chat_id,
            message_thread_id=target_thread,
            text=f"📢 <b>Расписание:</b>\n\n{text}"
        )
        if chat.pin_message:
            try:
                await bot.pin_chat_message(
                    chat_id=chat.chat_id,
                    message_id=sent_msg.message_id,
                    disable_notification=True
                )
            except Exception as pin_err:
                logging.debug(f"Не удалось закрепить сообщение: {pin_err}")
        await callback.answer("Расписание отправлено!")
        return

    # Обновляем текст и клавиатуру настроек
    is_supergroup = (callback.message.chat.type == "supergroup")
    await callback.message.edit_text(
        _get_settings_text(chat), 
        reply_markup=get_group_chat_settings_kb(chat, is_supergroup=is_supergroup)
    )
