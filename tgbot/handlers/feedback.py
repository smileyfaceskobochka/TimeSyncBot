import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from tgbot.config import config
from tgbot.database.models import User
from tgbot.database.repositories import UserRepository, AnalyticsRepository
from tgbot.states.states import FeedbackState
from tgbot.keyboards.callback_data import FeedbackCb
from tgbot.keyboards.inline import get_feedback_cancel_kb, get_feedback_admin_kb

feedback_router = Router()


# ================= НАЧАЛО ДИАЛОГА ОТЗЫВА =================
@feedback_router.callback_query(F.data == "feedback_start")
async def feedback_start_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FeedbackState.waiting_for_feedback)
    text = (
        "✍️ <b>Отзывы и предложения</b>\n\n"
        "Напишите ваше сообщение, отзыв, идею или опишите проблему.\n"
        "Вы также можете прикрепить скриншот или документ.\n\n"
        "<i>Все сообщения передаются напрямую администрации и разработчикам бота.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_feedback_cancel_kb())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=get_feedback_cancel_kb())
    await callback.answer()


@feedback_router.message(Command("feedback"))
@feedback_router.message(Command("suggest"))
async def feedback_start_cmd(message: Message, state: FSMContext):
    await state.set_state(FeedbackState.waiting_for_feedback)
    text = (
        "✍️ <b>Отзывы и предложения</b>\n\n"
        "Напишите ваше сообщение, отзыв, идею или опишите проблему.\n"
        "Вы также можете прикрепить скриншот или документ.\n\n"
        "<i>Все сообщения передаются напрямую администрации и разработчикам бота.</i>"
    )
    await message.answer(text, reply_markup=get_feedback_cancel_kb())


# ================= ПРИЕМ И ПЕРЕНАПРАВЛЕНИЕ АДМИНИСТРАТОРАМ =================
@feedback_router.message(FeedbackState.waiting_for_feedback)
async def process_feedback(
    message: Message, 
    state: FSMContext, 
    bot: Bot, 
    user_repo: UserRepository,
    analytics_repo: AnalyticsRepository
):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    username = message.from_user.username
    username_str = f"@{username}" if username else "нет"

    user = await user_repo.get_user(user_id)
    group_str = user.group_name if user and user.group_name else "Не выбрана"

    # Текущее московское время
    msk_tz = timezone(timedelta(hours=3))
    now_str = datetime.now(msk_tz).strftime("%d.%m.%Y %H:%M")

    feedback_text = message.text or message.caption or "<i>[Без текста / прикреплено медиа]</i>"

    admin_header = (
        "📬 <b>Новый отзыв / предложение!</b>\n\n"
        f"👤 <b>От:</b> <a href=\"tg://user?id={user_id}\">{user_name}</a> ({username_str})\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"👥 <b>Группа:</b> {group_str}\n"
        f"🕒 <b>Время:</b> {now_str} MSK\n\n"
        f"💬 <b>Сообщение:</b>\n{feedback_text}"
    )

    admin_kb = get_feedback_admin_kb(user_id=user_id, username=username)
    admin_ids = config.ADMIN_IDS
    delivered_count = 0

    for admin_id in admin_ids:
        try:
            if message.text:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_header,
                    reply_markup=admin_kb
                )
            elif message.photo:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=message.photo[-1].file_id,
                    caption=admin_header[:1024],
                    reply_markup=admin_kb
                )
            elif message.document:
                await bot.send_document(
                    chat_id=admin_id,
                    document=message.document.file_id,
                    caption=admin_header[:1024],
                    reply_markup=admin_kb
                )
            elif message.video:
                await bot.send_video(
                    chat_id=admin_id,
                    video=message.video.file_id,
                    caption=admin_header[:1024],
                    reply_markup=admin_kb
                )
            elif message.voice:
                await bot.send_voice(
                    chat_id=admin_id,
                    voice=message.voice.file_id,
                    caption=admin_header[:1024],
                    reply_markup=admin_kb
                )
            else:
                await bot.send_message(chat_id=admin_id, text=admin_header, reply_markup=admin_kb)
                await message.copy_to(chat_id=admin_id)
            delivered_count += 1
        except Exception as e:
            logging.warning(f"Could not forward feedback to admin {admin_id}: {e}")

    await state.clear()
    await analytics_repo.log_action(user_id, "send_feedback", f"delivered:{delivered_count}")

    try:
        from aiogram.types import ReactionTypeEmoji
        await message.react([ReactionTypeEmoji(emoji="✍️")])
    except Exception:
        pass

    builder = InlineKeyboardBuilder()
    builder.button(text="« Главное меню", callback_data="cmd_start")

    await message.answer(
        "✅ <b>Спасибо за обратную связь!</b>\n\n"
        "Ваше сообщение успешно отправлено администрации и разработчикам бота. "
        "Мы ценим ваше участие в улучшении сервиса!",
        reply_markup=builder.as_markup()
    )


# ================= ОТВЕТ АДМИНИСТРАТОРА ПОЛЬЗОВАТЕЛЮ =================
@feedback_router.callback_query(FeedbackCb.filter(F.action == "reply"))
async def admin_reply_start(callback: CallbackQuery, callback_data: FeedbackCb, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        return await callback.answer("⛔ Только администраторы могут отвечать на отзывы.", show_alert=True)

    target_user_id = callback_data.user_id
    await state.set_state(FeedbackState.waiting_for_admin_reply)
    await state.update_data(reply_target_user_id=target_user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="feedback_admin_cancel")

    await callback.message.reply(
        f"✍️ <b>Ответ пользователю (ID: <code>{target_user_id}</code>)</b>\n\n"
        "Напишите текст ответа, и он будет доставлен пользователю от имени бота:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@feedback_router.callback_query(F.data == "feedback_admin_cancel")
async def admin_reply_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Ответ пользователю отменён.")
    await callback.answer()


@feedback_router.message(FeedbackState.waiting_for_admin_reply)
async def admin_reply_process(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return

    data = await state.get_data()
    target_user_id = data.get("reply_target_user_id")
    if not target_user_id:
        await state.clear()
        return await message.answer("⚠️ Ошибка: получатель не определен. Попробуйте снова через кнопку 'Ответить'.")

    admin_text = message.text or message.caption or ""
    if not admin_text:
        return await message.answer("⚠️ Введите текстовое сообщение для ответа пользователю.")

    msg_to_user = (
        "💬 <b>Ответ от администрации / разработчиков:</b>\n\n"
        f"{admin_text}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="« Главное меню", callback_data="cmd_start")

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=msg_to_user,
            reply_markup=builder.as_markup()
        )
        await message.answer(f"✅ Ответ успешно доставлен пользователю <code>{target_user_id}</code>!")
    except TelegramForbiddenError:
        await message.answer("❌ Не удалось доставить сообщение: пользователь заблокировал бота.")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки сообщения пользователю: {e}")

    await state.clear()
