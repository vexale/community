"""Inline-only keyboard builders for the community bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import LINKS
from texts import TEXTS


def language_keyboard(show_back: bool = True, back_language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇸🇦 العربية", callback_data="language:ar"),
        InlineKeyboardButton(text="🇺🇸 English", callback_data="language:en"),
    )
    if show_back:
        back_text = "• رجوع •" if back_language == "ar" else "• Back •"
        builder.row(InlineKeyboardButton(text=back_text, callback_data="nav:main"))
    return builder.as_markup()


def main_menu_keyboard(language: str) -> InlineKeyboardMarkup:
    t = TEXTS[language]["buttons"]
    builder = InlineKeyboardBuilder()
    for key, text_key in (
        ("folder_link", "folder"),
        ("new_updates_link", "updates"),
        ("rules_guide_link", "rules_guide"),
        ("polls_link", "polls"),
    ):
        url = LINKS.get(key, "")
        if url:
            builder.row(InlineKeyboardButton(text=f"{text_key_index(key)} {t[text_key]}", url=url))
    builder.row(InlineKeyboardButton(text=f"5️⃣ {t['report_bug']}", callback_data="report:bug"))
    builder.row(InlineKeyboardButton(text=f"6️⃣ {t['confidential_report']}", callback_data="report:confidential"))
    builder.row(InlineKeyboardButton(text=f"7️⃣ {t['suggestion']}", callback_data="report:suggestion"))
    builder.row(InlineKeyboardButton(text=f"8️⃣ {t['language']}", callback_data="nav:language"))
    return builder.as_markup()


def text_key_index(key: str) -> str:
    return {
        "folder_link": "1️⃣",
        "new_updates_link": "2️⃣",
        "rules_guide_link": "3️⃣",
        "polls_link": "4️⃣",
    }[key]


def back_keyboard(language: str, extra_buttons: list[tuple[str, str]] | None = None) -> InlineKeyboardMarkup:
    """Return a submenu keyboard with the required localized styled back button."""
    builder = InlineKeyboardBuilder()
    for text, callback_data in extra_buttons or []:
        builder.row(InlineKeyboardButton(text=text, callback_data=callback_data))
    back_text = "• رجوع •" if language == "ar" else "• Back •"
    builder.row(InlineKeyboardButton(text=back_text, callback_data="nav:main"))
    return builder.as_markup()


def bug_platform_keyboard(language: str) -> InlineKeyboardMarkup:
    t = TEXTS[language]["buttons"]
    return back_keyboard(
        language,
        [(f"🤖 {t['report_android']}", "bug:android"), (f"🍎 {t['report_ios']}", "bug:ios")],
    )


def wizard_keyboard(language: str) -> InlineKeyboardMarkup:
    return back_keyboard(language, [(TEXTS[language]["buttons"]["cancel"], "nav:main")])
