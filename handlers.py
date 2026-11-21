"""User-facing bot handlers, anonymous report posts, and channel reply routing."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import REPORTS_CHANNEL_ID
from database import get_language, get_ticket_user, save_ticket, set_language
from keyboards import (
    bug_platform_keyboard,
    language_keyboard,
    main_menu_keyboard,
    wizard_keyboard,
)
from texts import TEXTS

router = Router(name="community-handlers")


class BugReport(StatesGroup):
    platform = State()
    device = State()
    description = State()


class PrivateSubmission(StatesGroup):
    content = State()


def _lang_tag(language: str) -> str:
    return "AR 🇸🇦" if language == "ar" else "EN 🇺🇸"


def _main_text(language: str) -> str:
    return f"<b>{'القائمة الرئيسية' if language == 'ar' else 'Main Menu'}</b>\n\n{TEXTS[language]['welcome']}"


def _has_media(message: Message) -> bool:
    return any(
        getattr(message, field, None)
        for field in ("photo", "document", "video", "animation", "audio", "voice", "video_note", "sticker")
    )


async def _show_main(message: Message, language: str) -> None:
    await message.edit_text(_main_text(language), reply_markup=main_menu_keyboard(language))


async def _prompt(message: Message, state: FSMContext, text: str, language: str) -> None:
    await message.edit_text(text, reply_markup=wizard_keyboard(language))
    await state.update_data(prompt_chat_id=message.chat.id, prompt_message_id=message.message_id)


async def _edit_saved_prompt(state: FSMContext, bot: Bot, text: str, language: str) -> None:
    data = await state.get_data()
    await bot.edit_message_text(
        text,
        chat_id=data["prompt_chat_id"],
        message_id=data["prompt_message_id"],
        reply_markup=wizard_keyboard(language),
    )


async def _post_anonymous_report(
    bot: Bot, message: Message, card: str, ticket_type: str
) -> None:
    """Post an anonymous report card and optional media; map each post for replies."""
    if not REPORTS_CHANNEL_ID:
        raise RuntimeError("REPORTS_CHANNEL_ID is not configured")
    posted = await bot.send_message(REPORTS_CHANNEL_ID, card)
    await save_ticket(posted.message_id, REPORTS_CHANNEL_ID, message.from_user.id, ticket_type)
    if _has_media(message):
        copied = await bot.copy_message(REPORTS_CHANNEL_ID, message.chat.id, message.message_id)
        await save_ticket(copied.message_id, REPORTS_CHANNEL_ID, message.from_user.id, ticket_type)


@router.message(F.text.startswith("/start"))
@router.message(F.text.startswith("/language"))
async def start_or_language(message: Message, state: FSMContext) -> None:
    await state.clear()
    saved = await get_language(message.from_user.id)
    await message.answer(
        "<b>اختر اللغة / Choose your language</b>",
        reply_to_message_id=message.message_id,
        reply_markup=language_keyboard(show_back=bool(saved), back_language=saved or "en"),
    )


@router.callback_query(F.data.startswith("language:"))
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    language = callback.data.split(":", 1)[1]
    if language not in {"ar", "en"}:
        await callback.answer("Invalid language", show_alert=True)
        return
    await state.clear()
    await set_language(callback.from_user.id, language)
    await callback.answer()
    await _show_main(callback.message, language)


@router.callback_query(F.data == "nav:language")
async def open_language_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    language = await get_language(callback.from_user.id) or "en"
    await callback.answer()
    await callback.message.edit_text(
        "<b>اختر اللغة / Choose your language</b>",
        reply_markup=language_keyboard(show_back=True, back_language=language),
    )


@router.callback_query(F.data == "nav:main")
async def go_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    language = await get_language(callback.from_user.id) or "en"
    await callback.answer()
    await _show_main(callback.message, language)


@router.callback_query(F.data == "report:bug")
async def begin_bug(callback: CallbackQuery, state: FSMContext) -> None:
    language = await get_language(callback.from_user.id) or "en"
    await state.clear()
    await state.set_state(BugReport.platform)
    text = "<b>1️⃣ اختر نظام التشغيل</b>" if language == "ar" else "<b>1️⃣ Choose your platform</b>"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=bug_platform_keyboard(language))


@router.callback_query(F.data.startswith("bug:"), BugReport.platform)
async def select_bug_platform(callback: CallbackQuery, state: FSMContext) -> None:
    platform = callback.data.split(":", 1)[1]
    if platform not in {"android", "ios"}:
        await callback.answer("Invalid platform", show_alert=True)
        return
    language = await get_language(callback.from_user.id) or "en"
    await state.update_data(platform=platform, language=language)
    await state.set_state(BugReport.device)
    text = (
        "<b>2️⃣ أدخل طراز الجهاز وإصدار النظام:</b>"
        if language == "ar"
        else "<b>2️⃣ Enter your device model and OS version:</b>"
    )
    await callback.answer()
    await _prompt(callback.message, state, text, language)


@router.message(BugReport.device, F.chat.type == "private")
async def receive_device(message: Message, state: FSMContext, bot: Bot) -> None:
    language = await get_language(message.from_user.id) or "en"
    if not message.text:
        await _edit_saved_prompt(
            state, bot,
            "أرسل طراز الجهاز وإصدار النظام كنص." if language == "ar" else "Please send the device model and OS version as text.",
            language,
        )
        return
    await state.update_data(device=message.text.strip())
    await state.set_state(BugReport.description)
    text = (
        "<b>3️⃣ اشرح المشكلة أو أرسل صورة توضحها:</b>"
        if language == "ar"
        else "<b>3️⃣ Describe the bug or send a photo showing it:</b>"
    )
    await _edit_saved_prompt(state, bot, text, language)


@router.message(BugReport.description, F.chat.type == "private")
async def receive_bug_description(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    language = data.get("language") or await get_language(message.from_user.id) or "en"
    if not (message.text or message.caption or _has_media(message)):
        await _edit_saved_prompt(
            state, bot,
            "أرسل وصفًا نصيًا أو صورة/ملفًا." if language == "ar" else "Please send text, a photo, or a file.",
            language,
        )
        return
    if not REPORTS_CHANNEL_ID:
        await _edit_saved_prompt(state, bot, "وجهة التقارير غير مضبوطة." if language == "ar" else "The reports channel is not configured.", language)
        await state.clear()
        return

    platform = data["platform"]
    header = (
        "🐞 𝐁𝐮𝐠 𝐑𝐞𝐩𝐨𝐫𝐭 | 🤖 𝐀𝐧𝐝𝐫𝐨𝐢𝐝"
        if platform == "android"
        else "🐞 𝐁𝐮𝐠 𝐑𝐞𝐩𝐨𝐫𝐭 | 🍎 𝐢𝐎𝐒"
    )
    description = escape(message.text or message.caption or "(media attached)")
    device_label = "طراز الجهاز / النظام" if language == "ar" else "Device / OS"
    description_label = "الوصف" if language == "ar" else "Description"
    card = (
        f"<b>{header}</b>\n[Lang: {_lang_tag(language)}]\n"
        f"<b>{device_label}:</b> {escape(data['device'])}\n"
        f"<b>{description_label}:</b> {description}"
    )
    await _post_anonymous_report(bot, message, card, f"bug_{platform}")
    done = "تم إرسال البلاغ إلى فريق الدعم. شكرًا لك." if language == "ar" else "Your bug report was sent to the support team. Thank you."
    await _edit_saved_prompt(state, bot, f"<b>{done}</b>", language)
    await state.clear()


@router.callback_query(F.data.in_({"report:confidential", "report:suggestion"}))
async def begin_private_submission(callback: CallbackQuery, state: FSMContext) -> None:
    language = await get_language(callback.from_user.id) or "en"
    kind = callback.data.split(":", 1)[1]
    await state.clear()
    await state.set_state(PrivateSubmission.content)
    await state.update_data(ticket_type=kind, language=language)
    if kind == "confidential":
        text = "<b>أرسل البلاغ السري نصًا أو صورة/ملفًا.</b>" if language == "ar" else "<b>Send your confidential report as text, photo, or file.</b>"
    else:
        text = "<b>أرسل اقتراحك نصًا أو صورة/ملفًا.</b>" if language == "ar" else "<b>Send your suggestion as text, photo, or file.</b>"
    await callback.answer()
    await _prompt(callback.message, state, text, language)


@router.message(PrivateSubmission.content, F.chat.type == "private")
async def receive_private_submission(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    language = data.get("language") or await get_language(message.from_user.id) or "en"
    if not (message.text or message.caption or _has_media(message)):
        await _edit_saved_prompt(state, bot, "أرسل نصًا أو صورة/ملفًا." if language == "ar" else "Please send text, a photo, or a file.", language)
        return
    if not REPORTS_CHANNEL_ID:
        await _edit_saved_prompt(state, bot, "وجهة التقارير غير مضبوطة." if language == "ar" else "The reports channel is not configured.", language)
        await state.clear()
        return

    kind = data["ticket_type"]
    if kind == "confidential":
        header = "🔒 𝐂𝐨𝐧𝐟𝐢𝐝𝐞𝐧𝐭𝐢𝐚𝐥 𝐑𝐞𝐩𝐨𝐫𝐭"
        title_ar = "بلاغ سري"
    else:
        header = "💡 𝐒𝐮𝐠𝐠𝐞𝐬𝐭𝐢𝐨𝐧"
        title_ar = "اقتراح"
    content_label = "المحتوى" if language == "ar" else "Content"
    content = escape(message.text or message.caption or "(media attached)")
    card = f"<b>{header}</b>\n[Lang: {_lang_tag(language)}]\n<b>{content_label}:</b> {content}"
    await _post_anonymous_report(bot, message, card, kind)
    done = f"تم إرسال {title_ar} بنجاح. شكرًا لك." if language == "ar" else "Sent successfully. Thank you."
    await _edit_saved_prompt(state, bot, f"<b>{done}</b>", language)
    await state.clear()


@router.channel_post()
async def relay_channel_reply(message: Message, bot: Bot) -> None:
    """Relay a direct reply to a mapped report post without exposing channel admins."""
    if not REPORTS_CHANNEL_ID or message.chat.id != REPORTS_CHANNEL_ID:
        return
    if message.reply_to_message is None:
        return
    ticket = await get_ticket_user(message.reply_to_message.message_id, REPORTS_CHANNEL_ID)
    if not ticket:
        return
    target_user_id, _ticket_type = ticket
    if message.text:
        await bot.send_message(
            target_user_id,
            f"<b>Support Team</b>\n{escape(message.text)}",
        )
    else:
        await bot.send_message(target_user_id, "<b>Support Team</b>")
        await bot.copy_message(target_user_id, REPORTS_CHANNEL_ID, message.message_id)
