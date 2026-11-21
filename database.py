"""SQLite persistence helpers for users and forwarded support tickets."""

from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).with_name("community_bot.sqlite3")


async def init_db(db_path: str | Path = DB_PATH) -> None:
    """Create the database tables if they do not already exist."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'en'
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS tickets (
                forwarded_msg_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL,
                PRIMARY KEY (forwarded_msg_id, chat_id)
            )"""
        )
        await db.commit()


async def get_language(user_id: int, db_path: str | Path = DB_PATH) -> str | None:
    """Return the saved language for a user, or None if the user is not stored."""
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute(
            "SELECT language FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def set_language(
    user_id: int, language: str, db_path: str | Path = DB_PATH
) -> None:
    """Insert or update a user's language preference."""
    if language not in {"ar", "en"}:
        raise ValueError("language must be 'ar' or 'en'")
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            """INSERT INTO users (user_id, language) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET language = excluded.language""",
            (user_id, language),
        )
        await db.commit()


async def save_ticket(
    forwarded_msg_id: int,
    chat_id: int,
    user_id: int,
    ticket_type: str,
    db_path: str | Path = DB_PATH,
) -> None:
    """Map a report-channel post (chat ID + message ID) to its target user."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            """INSERT OR REPLACE INTO tickets
               (forwarded_msg_id, chat_id, user_id, ticket_type)
               VALUES (?, ?, ?, ?)""",
            (forwarded_msg_id, chat_id, user_id, ticket_type),
        )
        await db.commit()


async def get_ticket_user(
    forwarded_msg_id: int, chat_id: int, db_path: str | Path = DB_PATH
) -> tuple[int, str] | None:
    """Return (user_id, ticket_type) for a mapped report-channel post."""
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute(
            """SELECT user_id, ticket_type FROM tickets
               WHERE forwarded_msg_id = ? AND chat_id = ?""",
            (forwarded_msg_id, chat_id),
        ) as cursor:
            row = await cursor.fetchone()
    return (row[0], row[1]) if row else None
