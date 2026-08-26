import os
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from bot.config import API_ID, API_HASH, SESSIONS_DIR

os.makedirs(SESSIONS_DIR, exist_ok=True)

# активные Client'ы, которые сейчас логинятся пошагово: {telegram_user_id: Client}
_pending_clients: dict[int, Client] = {}


def _session_name(owner_id: int, phone: str) -> str:
    clean = phone.replace("+", "").replace(" ", "")
    return f"{owner_id}_{clean}"


async def start_login(owner_id: int, phone: str) -> str:
    """Шаг 1: отправляет код на телефон, возвращает phone_code_hash."""
    session_name = _session_name(owner_id, phone)
    client = Client(
        name=session_name,
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=SESSIONS_DIR,
    )
    await client.connect()
    sent = await client.send_code(phone)
    _pending_clients[owner_id] = client
    return sent.phone_code_hash


async def submit_code(owner_id: int, phone: str, phone_code_hash: str, code: str):
    """Шаг 2: подтверждает код. Может бросить SessionPasswordNeeded."""
    client = _pending_clients[owner_id]
    await client.sign_in(phone, phone_code_hash, code)
    await client.disconnect()
    del _pending_clients[owner_id]


async def submit_password(owner_id: int, password: str):
    """Шаг 3 (если включена 2FA)."""
    client = _pending_clients[owner_id]
    await client.check_password(password)
    await client.disconnect()
    del _pending_clients[owner_id]


def cancel_pending(owner_id: int):
    _pending_clients.pop(owner_id, None)


def get_session_name(owner_id: int, phone: str) -> str:
    return _session_name(owner_id, phone)


def delete_session_file(owner_id: int, phone: str):
    session_name = _session_name(owner_id, phone)
    path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if os.path.exists(path):
        os.remove(path)


def make_client(owner_id: int, phone: str) -> Client:
    """Создаёт (но не запускает) Client для уже сохранённой сессии."""
    session_name = _session_name(owner_id, phone)
    return Client(
        name=session_name,
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=SESSIONS_DIR,
    )
