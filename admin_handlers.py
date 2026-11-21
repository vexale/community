"""Owner-only mobile administration for welcome copy, channels, and broadcasts."""

import asyncio
from html import escape
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import OWNER_IDS
from database import (
    add_channel, delete_channel, get_setting, get_users, list_channels,
    set_setting, update_channel,
)

router = Router(name="community-admin")
BACK = "🔙 رجوع / Back"


class AdminFlow(StatesGroup):
    welcome = State()
    channel_title = State()
    channel_url = State()
    channel_edit_value = State()
    broadcast_content = State()
    broadcast_confirm = State()


def _owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _back_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(BACK, "admin:back")]])


def _main_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("تعديل الرسالة الترحيبية / Edit Welcome", "admin:welcome")],
        [_button("إدارة القنوات / Manage Channels", "admin:channels")],
        [_button("إذاعة للجميع / Broadcast", "admin:broadcast")],
    ])


async def _show_admin(message: Message) -> None:
    await message.edit_text("<b>لوحة الإدارة / Admin Panel</b>", reply_markup=_main_markup())


async def _show_channels(message: Message) -> None:
    await message.edit_text(
        "<b>إدارة القنوات / Manage Channels</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_button("إضافة قناة / Add channel", "admin:channel:add")],
            [_button("تعديل قناة / Edit channel", "admin:channel:edit")],
            [_button("حذف قناة / Delete channel", "admin:channel:delete")],
            [_button(BACK, "admin:back")],
        ]),
    )


async def _channel_picker(message: Message, action: str) -> None:
    channels = await list_channels()
    rows = [[_button(f"{escape(title)} · #{channel_id}", f"admin:{action}:{channel_id}")]
            for channel_id, title, _url, _position in channels]
    rows.append([_button(BACK, "admin:channels")])
    await message.edit_text(
        "اختر القناة / Select a channel:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _save_prompt(message: Message, state: FSMContext, prompt: str) -> None:
    await message.edit_text(prompt, reply_markup=_back_markup())
    await state.update_data(prompt_chat_id=message.chat.id, prompt_message_id=message.message_id)


async def _replace_prompt(state: FSMContext, bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    data = await state.get_data()
    await bot.edit_message_text(
        text, chat_id=data["prompt_chat_id"], message_id=data["prompt_message_id"],
        reply_markup=markup or _back_markup(),
    )


@router.message(F.text == "/admin", F.chat.type == "private")
async def admin_command(message: Message, state: FSMContext) -> None:
    if not _owner(message.from_user.id):
        return
    await state.clear()
    await message.answer("<b>لوحة الإدارة / Admin Panel</b>", reply_markup=_main_markup())


@router.callback_query(F.data.startswith("admin:"))
async def admin_navigation(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _owner(callback.from_user.id):
        return
    data = callback.data
    message = callback.message

    if data == "admin:back":
        await state.clear()
        await callback.answer()
        await _show_admin(message)
        return
    if data == "admin:channels":
        await state.clear()
        await callback.answer()
        await _show_channels(message)
        return
    if data == "admin:welcome":
        await state.clear()
        await callback.answer()
        await message.edit_text(
            "اختر لغة الرسالة / Choose welcome language:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_button("العربية", "admin:welcome:ar"), _button("English", "admin:welcome:en")],
                [_button(BACK, "admin:back")],
            ]),
        )
        return
    if data in {"admin:welcome:ar", "admin:welcome:en"}:
        language = data.rsplit(":", 1)[1]
        await state.set_state(AdminFlow.welcome)
        await state.update_data(language=language)
        await callback.answer()
        current = await get_setting(f"welcome_{language}", "")
        current_text = escape(current) if current else "(empty)"
        await _save_prompt(message, state, f"Current / الحالي:\n{current_text}\n\nSend the new welcome text:")
        return
    if data == "admin:channel:add":
        await state.set_state(AdminFlow.channel_title)
        await callback.answer()
        await _save_prompt(message, state, "أرسل اسم القناة / Send the channel title:")
        return
    if data == "admin:channel:edit":
        await callback.answer()
        await _channel_picker(message, "edit")
        return
    if data == "admin:channel:delete":
        await callback.answer()
        await _channel_picker(message, "delete")
        return
    if data.startswith("admin:edit:"):
        channel_id = int(data.rsplit(":", 1)[1])
        await state.update_data(channel_id=channel_id)
        await callback.answer()
        await message.edit_text(
            "اختر ما تريد تعديله / Choose a field:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_button("العنوان / Title", f"admin:editfield:{channel_id}:title")],
                [_button("الرابط / URL", f"admin:editfield:{channel_id}:url")],
                [_button(BACK, "admin:channels")],
            ]),
        )
        return
    if data.startswith("admin:editfield:"):
        _, _, raw_id, field = data.split(":")
        await state.set_state(AdminFlow.channel_edit_value)
        await state.update_data(channel_id=int(raw_id), channel_field=field)
        await callback.answer()
        prompt = "أرسل العنوان الجديد / Send the new title:" if field == "title" else "أرسل الرابط الجديد / Send the new URL:"
        await _save_prompt(message, state, prompt)
        return
    if data.startswith("admin:delete:"):
        channel_id = int(data.rsplit(":", 1)[1])
        await delete_channel(channel_id)
        await callback.answer("Deleted / تم الحذف")
        await _show_channels(message)
        return
    if data == "admin:broadcast":
        await state.set_state(AdminFlow.broadcast_content)
        await callback.answer()
        await _save_prompt(message, state, "أرسل نصًا أو صورة مع تعليق / Send text or a photo with caption:")
        return
    if data == "admin:broadcast:cancel":
        await state.clear()
        await callback.answer()
        await _show_admin(message)
        return
    if data == "admin:broadcast:confirm":
        await callback.answer("Broadcasting…")
        await _send_broadcast(callback, state, bot)
        return


@router.message(AdminFlow.welcome, F.text)
async def save_welcome(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id):
        return
    data = await state.get_data()
    await set_setting(f"welcome_{data['language']}", message.text)
    await _replace_prompt(state, bot, "تم حفظ الرسالة الترحيبية / Welcome message saved.", _back_markup())
    await state.clear()


@router.message(AdminFlow.channel_title, F.text)
async def receive_channel_title(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id):
        return
    title = message.text.strip()
    if not title:
        await _replace_prompt(state, bot, "العنوان لا يمكن أن يكون فارغًا / Title cannot be empty.")
        return
    await state.update_data(channel_title=title)
    await state.set_state(AdminFlow.channel_url)
    await _replace_prompt(state, bot, "أرسل رابط القناة (https://...) / Send the channel URL (https://...):")


@router.message(AdminFlow.channel_url, F.text)
async def receive_channel_url(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id):
        return
    url = message.text.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        await _replace_prompt(state, bot, "رابط غير صالح. أرسل رابطًا يبدأ بـ https:// / Invalid URL; send a valid https:// link.")
        return
    data = await state.get_data()
    await add_channel(data["channel_title"], url)
    await _replace_prompt(state, bot, "تمت إضافة القناة / Channel added.", _back_markup())
    await state.clear()


@router.message(AdminFlow.channel_edit_value, F.text)
async def save_channel_edit(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id):
        return
    data = await state.get_data()
    value = message.text.strip()
    if not value:
        await _replace_prompt(state, bot, "القيمة لا يمكن أن تكون فارغة / Value cannot be empty.")
        return
    if data["channel_field"] == "url":
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            await _replace_prompt(state, bot, "رابط غير صالح / Invalid URL. Send a valid http(s) URL.")
            return
    await update_channel(data["channel_id"], data["channel_field"], value)
    await _replace_prompt(state, bot, "تم تحديث القناة / Channel updated.", _back_markup())
    await state.clear()


@router.message(AdminFlow.broadcast_content)
async def receive_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id):
        return
    if not message.text and not (message.photo and message.caption):
        await _replace_prompt(state, bot, "أرسل نصًا أو صورة مع تعليق / Send text or a photo with a caption.")
        return
    users = await get_users()
    await state.update_data(source_chat_id=message.chat.id, source_message_id=message.message_id, user_count=len(users))
    await state.set_state(AdminFlow.broadcast_confirm)
    await _replace_prompt(
        state, bot,
        f"سيتم الإرسال إلى {len(users)} مستخدم. تأكيد؟ / Send to {len(users)} users. Confirm?",
        InlineKeyboardMarkup(inline_keyboard=[
            [_button("تأكيد / Confirm", "admin:broadcast:confirm")],
            [_button("إلغاء / Cancel", "admin:broadcast:cancel")],
        ]),
    )


async def _send_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    users = await get_users()
    delivered = 0
    failed = 0
    for user_id in users:
        try:
            await bot.copy_message(
                chat_id=user_id, from_chat_id=data["source_chat_id"],
                message_id=data["source_message_id"],
            )
            delivered += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id, from_chat_id=data["source_chat_id"],
                    message_id=data["source_message_id"],
                )
                delivered += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.04)
    await state.clear()
    await callback.message.edit_text(
        f"اكتمل الإرسال. تم التسليم: {delivered}، فشل: {failed}.\n"
        f"Broadcast complete. Delivered: {delivered}; failed: {failed}.",
        reply_markup=_back_markup(),
    )
