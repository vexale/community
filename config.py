"""Environment-backed configuration for the community support bot."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env file when present; hosting platforms may inject variables directly.
load_dotenv(Path(__file__).with_name(".env"))


def _owner_ids() -> list[int]:
    """Parse OWNER_IDS as a comma-separated list of Telegram numeric IDs."""
    return [int(value.strip()) for value in os.getenv("OWNER_IDS", "").split(",") if value.strip()]


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PROXY_URL = os.getenv("PROXY_URL", "").strip()
OWNER_IDS = _owner_ids()
REPORTS_CHANNEL_ID = _optional_int("REPORTS_CHANNEL_ID")

# Provide full Telegram URLs in the corresponding environment variables.
LINKS = {
    "folder_link": os.getenv("FOLDER_LINK", "").strip(),
    "new_updates_link": os.getenv("NEW_UPDATES_LINK", "").strip(),
    "rules_guide_link": os.getenv("RULES_GUIDE_LINK", "").strip(),
    "polls_link": os.getenv("POLLS_LINK", "").strip(),
}
