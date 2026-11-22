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
        await db.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                url TEXT,
                position INTEGER DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0
            )"""
        )
        async with db.execute("PRAGMA table_info(channels)") as cursor:
            channel_columns = {row[1] async for row in cursor}
        if "sort_order" not in channel_columns:
            await db.execute("ALTER TABLE channels ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            await db.execute("UPDATE channels SET sort_order = COALESCE(position, 0)")
        await db.execute(
            """CREATE TABLE IF NOT EXISTS custom_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('direct', 'branches')),
                direct_url TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS custom_branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES custom_items(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            )"""
        )
        await db.commit()


async def seed_channels(defaults: list[tuple[str, str]], db_path: str | Path = DB_PATH) -> None:
    """Seed configured links only when no channel rows exist."""
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT COUNT(*) FROM channels") as cursor:
            row = await cursor.fetchone()
        if row and row[0] == 0:
            await db.executemany(
                "INSERT INTO channels (title, url, position, sort_order) VALUES (?, ?, ?, ?)",
                [(title, url, index, index) for index, (title, url) in enumerate(defaults) if url],
            )
            await db.commit()


async def seed_settings(defaults: dict[str, str], db_path: str | Path = DB_PATH) -> None:
    """Insert default settings without overwriting admin-edited values."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            list(defaults.items()),
        )
        await db.commit()


async def register_user(user_id: int, language: str = "en", db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO users (user_id, language) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO NOTHING", (user_id, language)
        )
        await db.commit()


async def get_users(db_path: str | Path = DB_PATH) -> list[int]:
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT user_id FROM users ORDER BY user_id") as cursor:
            return [row[0] async for row in cursor]


async def get_setting(key: str, default: str = "", db_path: str | Path = DB_PATH) -> str:
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else default


async def set_setting(key: str, value: str, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value)
        )
        await db.commit()


async def list_channels(db_path: str | Path = DB_PATH) -> list[tuple[int, str, str, int]]:
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute(
            "SELECT id, title, url, sort_order FROM channels ORDER BY sort_order, id"
        ) as cursor:
            return [row async for row in cursor]


async def add_channel(title: str, url: str, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO channels (title, url, position, sort_order) VALUES (?, ?, "
            "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM channels), "
            "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM channels))", (title, url)
        )
        await db.commit()


async def update_channel(channel_id: int, field: str, value: str, db_path: str | Path = DB_PATH) -> None:
    if field not in {"title", "url"}:
        raise ValueError("field must be title or url")
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(f"UPDATE channels SET {field} = ? WHERE id = ?", (value, channel_id))
        await db.commit()


async def delete_channel(channel_id: int, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await db.commit()


async def list_custom_items(db_path: str | Path = DB_PATH):
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT id, title, mode, direct_url, sort_order FROM custom_items ORDER BY sort_order, id") as cursor:
            return [row async for row in cursor]


async def get_custom_item(item_id: int, db_path: str | Path = DB_PATH):
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT id, title, mode, direct_url, sort_order FROM custom_items WHERE id = ?", (item_id,)) as cursor:
            return await cursor.fetchone()


async def add_custom_item(title: str, mode: str, direct_url: str | None = None, db_path: str | Path = DB_PATH) -> int:
    if mode not in {"direct", "branches"}:
        raise ValueError("mode must be direct or branches")
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute("INSERT INTO custom_items(title, mode, direct_url, sort_order) VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM custom_items))", (title, mode, direct_url))
        await db.commit()
        return cursor.lastrowid


async def update_custom_item(item_id: int, field: str, value: str | None, db_path: str | Path = DB_PATH) -> None:
    if field not in {"title", "direct_url"}:
        raise ValueError("unsupported custom item field")
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(f"UPDATE custom_items SET {field} = ? WHERE id = ?", (value, item_id))
        await db.commit()


async def delete_custom_item(item_id: int, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM custom_items WHERE id = ?", (item_id,))
        await db.commit()


async def list_custom_branches(item_id: int, db_path: str | Path = DB_PATH):
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT id, item_id, title, url, sort_order FROM custom_branches WHERE item_id = ? ORDER BY sort_order, id", (item_id,)) as cursor:
            return [row async for row in cursor]


async def add_custom_branch(item_id: int, title: str, url: str, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("INSERT INTO custom_branches(item_id, title, url, sort_order) VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM custom_branches WHERE item_id = ?))", (item_id, title, url, item_id))
        await db.commit()


async def update_custom_branch(branch_id: int, field: str, value: str, db_path: str | Path = DB_PATH) -> None:
    if field not in {"title", "url"}:
        raise ValueError("unsupported branch field")
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(f"UPDATE custom_branches SET {field} = ? WHERE id = ?", (value, branch_id))
        await db.commit()


async def delete_custom_branch(branch_id: int, db_path: str | Path = DB_PATH) -> None:
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("DELETE FROM custom_branches WHERE id = ?", (branch_id,))
        await db.commit()


async def move_order(table: str, row_id: int, direction: str, parent_id: int | None = None, db_path: str | Path = DB_PATH) -> bool:
    specs = {"channels": ("channels", None), "items": ("custom_items", None), "branches": ("custom_branches", "item_id")}
    if table not in specs or direction not in {"up", "down"}:
        raise ValueError("invalid reorder request")
    table_name, parent_column = specs[table]
    condition = f"{parent_column} = ?" if parent_column else "1 = 1"
    params = (parent_id,) if parent_column else ()
    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute(f"SELECT id, sort_order FROM {table_name} WHERE {condition} ORDER BY sort_order, id", params) as cursor:
            rows = await cursor.fetchall()
        index = next((i for i, row in enumerate(rows) if row[0] == row_id), None)
        neighbor = None if index is None else index + (-1 if direction == "up" else 1)
        if neighbor is None or neighbor < 0 or neighbor >= len(rows):
            return False
        reordered = list(rows)
        reordered[index], reordered[neighbor] = reordered[neighbor], reordered[index]
        await db.execute("BEGIN IMMEDIATE")
        await db.executemany(
            f"UPDATE {table_name} SET sort_order = ? WHERE id = ?",
            [(order, row[0]) for order, row in enumerate(reordered)],
        )
        await db.commit()
        return True


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
