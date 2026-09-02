import aiosqlite
from contextlib import asynccontextmanager

from bot.config import DB_PATH, ADMIN_ID

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lang TEXT DEFAULT NULL,
    captcha_passed INTEGER DEFAULT 0,
    has_access INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    session_name TEXT NOT NULL,
    is_running INTEGER DEFAULT 0,
    UNIQUE(owner_id, phone)
);

CREATE TABLE IF NOT EXISTS gift_ignore (
    owner_id INTEGER NOT NULL,
    gift_id TEXT NOT NULL,
    PRIMARY KEY (owner_id, gift_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- персональные настройки снайпинга: диапазон цены и вкл/выкл логов.
-- min_price/max_price NULL = использовать значения из переменных
-- окружения SNIPE_MIN_PRICE/SNIPE_MAX_PRICE по умолчанию.
CREATE TABLE IF NOT EXISTS user_settings (
    owner_id INTEGER PRIMARY KEY,
    min_price INTEGER DEFAULT NULL,
    max_price INTEGER DEFAULT NULL,
    logs_enabled INTEGER DEFAULT 0
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
        # админ сразу с доступом
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, has_access) VALUES (?, 1)",
            (ADMIN_ID,),
        )
        await db.commit()


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    try:
        yield db
    finally:
        await db.close()


# ---------- users ----------

async def ensure_user(user_id: int):
    async with get_db() as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def get_user(user_id: int):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def set_lang(user_id: int, lang: str):
    async with get_db() as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
        await db.commit()


async def set_captcha_passed(user_id: int, passed: bool = True):
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET captcha_passed=? WHERE user_id=?", (int(passed), user_id)
        )
        await db.commit()


async def set_access(user_id: int, has_access: bool):
    async with get_db() as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute(
            "UPDATE users SET has_access=? WHERE user_id=?", (int(has_access), user_id)
        )
        await db.commit()


async def has_access(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    row = await get_user(user_id)
    return bool(row and row["has_access"])


# ---------- technical mode ----------

async def set_technical(on: bool):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('technical', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if on else "0",),
        )
        await db.commit()


async def is_technical() -> bool:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT value FROM settings WHERE key='technical'")
        row = await cur.fetchone()
        return bool(row and row["value"] == "1")


# ---------- accounts ----------

async def add_account(owner_id: int, phone: str, session_name: str):
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO accounts (owner_id, phone, session_name) VALUES (?, ?, ?)",
            (owner_id, phone, session_name),
        )
        await db.commit()


async def remove_account(owner_id: int, phone: str):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM accounts WHERE owner_id=? AND phone=?", (owner_id, phone)
        )
        await db.commit()


async def list_accounts(owner_id: int):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM accounts WHERE owner_id=?", (owner_id,))
        return await cur.fetchall()


async def get_account(owner_id: int, phone: str):
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM accounts WHERE owner_id=? AND phone=?", (owner_id, phone)
        )
        return await cur.fetchone()


async def set_account_running(owner_id: int, phone: str, running: bool):
    async with get_db() as db:
        await db.execute(
            "UPDATE accounts SET is_running=? WHERE owner_id=? AND phone=?",
            (int(running), owner_id, phone),
        )
        await db.commit()


async def all_running_accounts():
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM accounts WHERE is_running=1")
        return await cur.fetchall()


# ---------- gift ignore list ----------

async def toggle_ignore(owner_id: int, gift_id: str) -> bool:
    """Возвращает True, если подарок теперь в игноре (красный), False если снова активен."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT 1 FROM gift_ignore WHERE owner_id=? AND gift_id=?", (owner_id, gift_id)
        )
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM gift_ignore WHERE owner_id=? AND gift_id=?",
                (owner_id, gift_id),
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO gift_ignore (owner_id, gift_id) VALUES (?, ?)",
                (owner_id, gift_id),
            )
            await db.commit()
            return True


async def get_ignored_gifts(owner_id: int) -> set:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT gift_id FROM gift_ignore WHERE owner_id=?", (owner_id,)
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


# ---------- персональные настройки снайпинга ----------

async def get_price_range(owner_id: int):
    """Возвращает (min_price, max_price) — либо кастомные значения
    пользователя, либо None, None если он их не задавал (тогда
    вызывающий код берёт значения из переменных окружения)."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT min_price, max_price FROM user_settings WHERE owner_id=?", (owner_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None, None
        return row["min_price"], row["max_price"]


async def set_price_range(owner_id: int, min_price: int, max_price: int):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO user_settings (owner_id, min_price, max_price) VALUES (?, ?, ?) "
            "ON CONFLICT(owner_id) DO UPDATE SET min_price=excluded.min_price, max_price=excluded.max_price",
            (owner_id, min_price, max_price),
        )
        await db.commit()


async def get_logs_enabled(owner_id: int) -> bool:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT logs_enabled FROM user_settings WHERE owner_id=?", (owner_id,)
        )
        row = await cur.fetchone()
        return bool(row and row["logs_enabled"])


async def set_logs_enabled(owner_id: int, enabled: bool):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO user_settings (owner_id, logs_enabled) VALUES (?, ?) "
            "ON CONFLICT(owner_id) DO UPDATE SET logs_enabled=excluded.logs_enabled",
            (owner_id, int(enabled)),
        )
        await db.commit()
