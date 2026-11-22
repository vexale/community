"""Owner-only administration for welcome copy, channels, custom links, and broadcasts."""

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
    add_channel, add_custom_branch, add_custom_item, delete_channel,
    delete_custom_branch, delete_custom_item, get_custom_item, get_setting, get_users,
    list_channels, list_custom_branches, list_custom_items, move_order,
    set_setting, update_channel, update_custom_branch, update_custom_item,
)

router = Router(name="community-admin")
BACK = "• رجوع •"


class AdminFlow(StatesGroup):
    welcome = State()
    channel_title = State()
    channel_url = State()
    channel_edit_value = State()
    item_title = State()
    item_direct_url = State()
    branch_title = State()
    branch_url = State()
    item_edit_value = State()
    branch_edit_value = State()
    broadcast_content = State()
    broadcast_confirm = State()


def _owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_markup(destination: str = "admin:back") -> InlineKeyboardMarkup:
    return _markup([[_button(BACK, destination)]])


def _main_markup() -> InlineKeyboardMarkup:
    return _markup([
        [_button("تعديل الترحيب / Edit Welcome", "admin:welcome")],
        [_button("إدارة القنوات / Manage Channels", "admin:channels")],
        [_button("إدارة العناصر والأوامر / Manage Items", "admin:items")],
        [_button("إذاعة للجميع / Broadcast", "admin:broadcast")],
    ])


def _channels_markup() -> InlineKeyboardMarkup:
    return _markup([
        [_button("إضافة قناة / Add channel", "admin:channel:add")],
        [_button("ترتيب وتعديل القنوات / Order & edit", "admin:channel:list")],
        [_button(BACK, "admin:back")],
    ])


async def _show_admin(message: Message) -> None:
    await message.edit_text("<b>لوحة الإدارة / Admin Panel</b>", reply_markup=_main_markup())


async def _show_channels(message: Message) -> None:
    await message.edit_text("<b>إدارة القنوات / Manage Channels</b>", reply_markup=_channels_markup())


async def _channel_list(message: Message) -> None:
    channels = await list_channels()
    rows = []
    for channel_id, title, _url, _order in channels:
        rows.append([
            _button(f"⬆️ {title[:22]}", f"admin:move:channels:{channel_id}:up"),
            _button("⬇️", f"admin:move:channels:{channel_id}:down"),
            _button("✏️", f"admin:edit:{channel_id}"),
            _button("🗑", f"admin:delete:{channel_id}"),
        ])
    rows.append([_button(BACK, "admin:channels")])
    await message.edit_text("اختر قناة للتعديل أو غيّر ترتيبها / Edit or reorder a channel:", reply_markup=_markup(rows))


async def _items_list(message: Message) -> None:
    items = await list_custom_items()
    rows = [[_button("➕ إضافة عنصر / Add item", "admin:item:add")]]
    for item_id, title, mode, _url, _order in items:
        rows.append([
            _button(f"⬆️ {title[:16]}", f"admin:move:items:{item_id}:up"),
            _button("⬇️", f"admin:move:items:{item_id}:down"),
            _button("✏️", f"admin:item:edit:{item_id}"),
            _button("🗑", f"admin:item:delete:{item_id}"),
        ])
        if mode == "branches":
            rows.append([_button(f"↳ إدارة الفروع / Branches: {title[:20]}", f"admin:branches:{item_id}")])
    rows.append([_button(BACK, "admin:back")])
    await message.edit_text("<b>إدارة العناصر والأوامر / Manage Items</b>", reply_markup=_markup(rows))


async def _branches_list(message: Message, item_id: int) -> None:
    branches = await list_custom_branches(item_id)
    rows = [[_button("➕ إضافة زر فرعي / Add branch", f"admin:branch:add:{item_id}")]]
    for branch_id, _parent, title, _url, _order in branches:
        rows.append([
            _button(f"⬆️ {title[:16]}", f"admin:move:branches:{item_id}:{branch_id}:up"),
            _button("⬇️", f"admin:move:branches:{item_id}:{branch_id}:down"),
            _button("✏️", f"admin:branch:edit:{item_id}:{branch_id}"),
            _button("🗑", f"admin:branch:delete:{item_id}:{branch_id}"),
        ])
    rows.append([_button(BACK, "admin:items")])
    await message.edit_text("إدارة الأزرار الفرعية / Manage sub-buttons:", reply_markup=_markup(rows))


async def _save_prompt(message: Message, state: FSMContext, prompt: str, markup: InlineKeyboardMarkup | None = None) -> None:
    await message.edit_text(prompt, reply_markup=markup or _back_markup())
    await state.update_data(prompt_chat_id=message.chat.id, prompt_message_id=message.message_id)


async def _replace_prompt(state: FSMContext, bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    data = await state.get_data()
    await bot.edit_message_text(text, chat_id=data["prompt_chat_id"], message_id=data["prompt_message_id"], reply_markup=markup or _back_markup())


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@router.message(F.text == "/admin", F.chat.type == "private")
async def admin_command(message: Message, state: FSMContext) -> None:
    if not _owner(message.from_user.id):
        return
    await state.clear()
    await message.answer("<b>لوحة الإدارة / Admin Panel</b>", reply_markup=_main_markup())


@router.callback_query(F.data.startswith("admin:"))
async def admin_navigation(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _owner(callback.from_user.id):
        await callback.answer()
        return
    data, message = callback.data, callback.message
    if data == "admin:back":
        await state.clear(); await callback.answer(); await _show_admin(message); return
    if data == "admin:channels":
        await state.clear(); await callback.answer(); await _show_channels(message); return
    if data == "admin:channel:list":
        await callback.answer(); await _channel_list(message); return
    if data == "admin:items":
        await state.clear(); await callback.answer(); await _items_list(message); return
    if data == "admin:welcome":
        await state.clear(); await callback.answer()
        await message.edit_text("اختر لغة الرسالة / Choose welcome language:", reply_markup=_markup([
            [_button("العربية", "admin:welcome:ar"), _button("English", "admin:welcome:en")],
            [_button(BACK, "admin:back")],
        ])); return
    if data in {"admin:welcome:ar", "admin:welcome:en"}:
        language = data.rsplit(":", 1)[1]
        await state.set_state(AdminFlow.welcome); await state.update_data(language=language)
        await callback.answer()
        current = escape(await get_setting(f"welcome_{language}", "") or "(empty)")
        await _save_prompt(message, state, f"Current / الحالي:\n{current}\n\nSend the new welcome text:"); return
    if data == "admin:channel:add":
        await state.set_state(AdminFlow.channel_title); await callback.answer()
        await _save_prompt(message, state, "أرسل اسم القناة / Send the channel title:"); return
    if data.startswith("admin:edit:"):
        channel_id = int(data.rsplit(":", 1)[1]); await callback.answer()
        await message.edit_text("اختر ما تريد تعديله / Choose a field:", reply_markup=_markup([
            [_button("العنوان / Title", f"admin:editfield:{channel_id}:title")],
            [_button("الرابط / URL", f"admin:editfield:{channel_id}:url")],
            [_button(BACK, "admin:channel:list")],
        ])); return
    if data.startswith("admin:editfield:"):
        _, _, raw_id, field = data.split(":")
        await state.set_state(AdminFlow.channel_edit_value); await state.update_data(channel_id=int(raw_id), channel_field=field)
        await callback.answer(); await _save_prompt(message, state, "أرسل القيمة الجديدة / Send the new value:"); return
    if data.startswith("admin:delete:"):
        await delete_channel(int(data.rsplit(":", 1)[1])); await callback.answer("Deleted / تم الحذف")
        await _channel_list(message); return
    if data.startswith("admin:move:"):
        parts = data.split(":")
        if parts[2] == "branches":
            _, _, table, raw_parent, raw_id, direction = parts
            await move_order(table, int(raw_id), direction, int(raw_parent))
            await callback.answer(); await _branches_list(message, int(raw_parent)); return
        _, _, table, raw_id, direction = parts
        await move_order(table, int(raw_id), direction)
        await callback.answer()
        if table == "channels": await _channel_list(message)
        else: await _items_list(message)
        return
    if data == "admin:item:add":
        await state.set_state(AdminFlow.item_title); await callback.answer()
        await _save_prompt(message, state, "أرسل اسم العنصر / Send the item button label:"); return
    if data.startswith("admin:item:mode:"):
        _, _, _, mode = data.split(":")
        await callback.answer()
        if mode == "direct":
            await state.update_data(item_mode=mode); await state.set_state(AdminFlow.item_direct_url)
            await _save_prompt(message, state, "أرسل الرابط المباشر / Send the direct URL:")
        else:
            item_id = await add_custom_item((await state.get_data())["item_title"], "branches")
            await state.update_data(item_id=item_id); await state.set_state(AdminFlow.branch_title)
            await _save_prompt(message, state, "أرسل اسم أول زر فرعي / Send the first sub-button label:")
        return
    if data.startswith("admin:branches:"):
        item_id = int(data.rsplit(":", 1)[1]); await callback.answer(); await _branches_list(message, item_id); return
    if data.startswith("admin:branch:add:"):
        item_id = int(data.rsplit(":", 1)[1]); await state.set_state(AdminFlow.branch_title)
        await state.update_data(item_id=item_id); await callback.answer()
        await _save_prompt(message, state, "أرسل اسم الزر الفرعي / Send sub-button label:"); return
    if data.startswith("admin:branch:added:"):
        item_id = int(data.rsplit(":", 1)[1]); await callback.answer()
        await state.set_state(AdminFlow.branch_title); await state.update_data(item_id=item_id)
        await _save_prompt(message, state, "أرسل اسم الزر الفرعي التالي / Send next sub-button label:"); return
    if data.startswith("admin:branch:edit:"):
        _, _, _, raw_parent, raw_id = data.split(":"); await callback.answer()
        await message.edit_text("اختر الحقل / Choose field:", reply_markup=_markup([
            [_button("الاسم / Label", f"admin:branchfield:{raw_parent}:{raw_id}:title")],
            [_button("الرابط / URL", f"admin:branchfield:{raw_parent}:{raw_id}:url")],
            [_button(BACK, f"admin:branches:{raw_parent}")],
        ])); return
    if data.startswith("admin:branchfield:"):
        _, _, raw_parent, raw_id, field = data.split(":")
        await state.set_state(AdminFlow.branch_edit_value); await state.update_data(branch_id=int(raw_id), item_id=int(raw_parent), branch_field=field)
        await callback.answer(); await _save_prompt(message, state, "أرسل القيمة الجديدة / Send the new value:"); return
    if data.startswith("admin:branch:delete:"):
        _, _, _, raw_parent, raw_id = data.split(":"); await delete_custom_branch(int(raw_id))
        await callback.answer("Deleted / تم الحذف"); await _branches_list(message, int(raw_parent)); return
    if data.startswith("admin:item:edit:"):
        item_id = int(data.rsplit(":", 1)[1]); item = await get_custom_item(item_id); await callback.answer()
        rows = [[_button("الاسم / Label", f"admin:itemfield:{item_id}:title")]]
        if item and item[2] == "direct":
            rows.append([_button("الرابط / URL", f"admin:itemfield:{item_id}:direct_url")])
        if item and item[2] == "branches":
            rows.append([_button("إدارة الفروع / Manage branches", f"admin:branches:{item_id}")])
        rows.append([_button(BACK, "admin:items")])
        await message.edit_text("اختر ما تريد تعديله / Choose what to edit:", reply_markup=_markup(rows)); return
    if data.startswith("admin:itemfield:"):
        _, _, raw_id, field = data.split(":"); await state.set_state(AdminFlow.item_edit_value)
        await state.update_data(item_id=int(raw_id), item_field=field); await callback.answer()
        await _save_prompt(message, state, "أرسل القيمة الجديدة / Send the new value:"); return
    if data.startswith("admin:item:delete:"):
        await delete_custom_item(int(data.rsplit(":", 1)[1])); await callback.answer("Deleted / تم الحذف")
        await _items_list(message); return
    if data == "admin:broadcast":
        await state.set_state(AdminFlow.broadcast_content); await callback.answer()
        await _save_prompt(message, state, "أرسل نصًا أو صورة مع تعليق / Send text or a photo with caption:"); return
    if data == "admin:broadcast:cancel":
        await state.clear(); await callback.answer(); await _show_admin(message); return
    if data == "admin:broadcast:confirm":
        await callback.answer("Broadcasting…"); await _send_broadcast(callback, state, bot); return


@router.message(AdminFlow.welcome, F.text)
async def save_welcome(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    data = await state.get_data(); await set_setting(f"welcome_{data['language']}", message.text)
    await _replace_prompt(state, bot, "تم حفظ الرسالة الترحيبية / Welcome message saved."); await state.clear()


@router.message(AdminFlow.channel_title, F.text)
async def receive_channel_title(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    title = message.text.strip()
    if not title:
        await _replace_prompt(state, bot, "العنوان لا يمكن أن يكون فارغًا / Title cannot be empty."); return
    await state.update_data(channel_title=title); await state.set_state(AdminFlow.channel_url)
    await _replace_prompt(state, bot, "أرسل رابط القناة (https://...) / Send the channel URL:")


@router.message(AdminFlow.channel_url, F.text)
async def receive_channel_url(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    url = message.text.strip()
    if not _valid_url(url):
        await _replace_prompt(state, bot, "رابط غير صالح / Invalid URL; use http(s)."); return
    await add_channel((await state.get_data())["channel_title"], url)
    await _replace_prompt(state, bot, "تمت إضافة القناة / Channel added."); await state.clear()


@router.message(AdminFlow.channel_edit_value, F.text)
async def save_channel_edit(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    data, value = await state.get_data(), message.text.strip()
    if not value or (data["channel_field"] == "url" and not _valid_url(value)):
        await _replace_prompt(state, bot, "قيمة أو رابط غير صالح / Invalid value or URL."); return
    await update_channel(data["channel_id"], data["channel_field"], value)
    await _replace_prompt(state, bot, "تم تحديث القناة / Channel updated."); await state.clear()


@router.message(AdminFlow.item_title, F.text)
async def receive_item_title(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    title = message.text.strip()
    if not title:
        await _replace_prompt(state, bot, "الاسم مطلوب / Label is required."); return
    await state.update_data(item_title=title)
    await _replace_prompt(state, bot, "اختر طريقة عمل العنصر / Choose item type:", _markup([
        [_button("رابط مباشر / Direct link", "admin:item:mode:direct")],
        [_button("تفرعات / Sub-buttons", "admin:item:mode:branches")],
        [_button(BACK, "admin:items")],
    ]))


@router.message(AdminFlow.item_direct_url, F.text)
async def receive_item_url(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    url = message.text.strip()
    if not _valid_url(url):
        await _replace_prompt(state, bot, "رابط غير صالح / Invalid URL; use http(s)."); return
    data = await state.get_data(); await add_custom_item(data["item_title"], "direct", url)
    await _replace_prompt(state, bot, "تمت إضافة العنصر / Item added."); await state.clear()


@router.message(AdminFlow.branch_title, F.text)
async def receive_branch_title(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    title = message.text.strip()
    if not title:
        await _replace_prompt(state, bot, "الاسم مطلوب / Label is required."); return
    await state.update_data(branch_title=title); await state.set_state(AdminFlow.branch_url)
    await _replace_prompt(state, bot, "أرسل رابط الزر الفرعي / Send the sub-button URL:")


@router.message(AdminFlow.branch_url, F.text)
async def receive_branch_url(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    url = message.text.strip()
    if not _valid_url(url):
        await _replace_prompt(state, bot, "رابط غير صالح / Invalid URL; use http(s)."); return
    item_id = (await state.get_data())["item_id"]
    await add_custom_branch(item_id, (await state.get_data())["branch_title"], url)
    await _replace_prompt(state, bot, "تمت إضافة الزر / Sub-button added.", _markup([
        [_button("إضافة زر آخر / Add another", f"admin:branch:added:{item_id}")],
        [_button("إنهاء / Done", f"admin:branches:{item_id}")],
    ]))
    await state.clear()


@router.message(AdminFlow.item_edit_value, F.text)
async def save_item_edit(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    data, value = await state.get_data(), message.text.strip()
    if not value or (data["item_field"] == "direct_url" and not _valid_url(value)):
        await _replace_prompt(state, bot, "قيمة أو رابط غير صالح / Invalid value or URL."); return
    await update_custom_item(data["item_id"], data["item_field"], value)
    await _replace_prompt(state, bot, "تم تحديث العنصر / Item updated."); await state.clear()


@router.message(AdminFlow.branch_edit_value, F.text)
async def save_branch_edit(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    data, value = await state.get_data(), message.text.strip()
    if not value or (data["branch_field"] == "url" and not _valid_url(value)):
        await _replace_prompt(state, bot, "قيمة أو رابط غير صالح / Invalid value or URL."); return
    await update_custom_branch(data["branch_id"], data["branch_field"], value)
    await _replace_prompt(state, bot, "تم تحديث الزر الفرعي / Sub-button updated."); await state.clear()


@router.message(AdminFlow.broadcast_content)
async def receive_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    if not _owner(message.from_user.id): return
    if not message.text and not (message.photo and message.caption):
        await _replace_prompt(state, bot, "أرسل نصًا أو صورة مع تعليق / Send text or a photo with a caption."); return
    users = await get_users()
    await state.update_data(source_chat_id=message.chat.id, source_message_id=message.message_id, user_count=len(users))
    await state.set_state(AdminFlow.broadcast_confirm)
    await _replace_prompt(state, bot, f"سيتم الإرسال إلى {len(users)} مستخدم. تأكيد؟ / Send to {len(users)} users. Confirm?", _markup([
        [_button("تأكيد / Confirm", "admin:broadcast:confirm")],
        [_button("إلغاء / Cancel", "admin:broadcast:cancel")],
    ]))


async def _send_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data(); users = await get_users(); delivered = failed = 0
    for user_id in users:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=data["source_chat_id"], message_id=data["source_message_id"])
            delivered += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=data["source_chat_id"], message_id=data["source_message_id"]); delivered += 1
            except TelegramAPIError: failed += 1
        except TelegramAPIError: failed += 1
        await asyncio.sleep(0.04)
    await state.clear()
    await callback.message.edit_text(f"اكتمل الإرسال. تم التسليم: {delivered}، فشل: {failed}.\nBroadcast complete. Delivered: {delivered}; failed: {failed}.", reply_markup=_back_markup())
