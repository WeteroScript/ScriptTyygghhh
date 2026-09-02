"""
Отправка "логов" пользователю прямо в чат бота (раздел "Логи": ✅/❌).

Отдельный Bot-инстанс (а не тот, что крутит polling в main.py) — потому
что gift_sniper работает в фоновых asyncio-задачах, ему не нужен весь
Dispatcher, только возможность слать сообщения.
"""

import logging

from aiogram import Bot

from bot.config import BOT_TOKEN
from bot.database import get_logs_enabled

log = logging.getLogger("notifier")

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=BOT_TOKEN)
    return _bot


async def send_log(owner_id: int, text: str):
    """Отправляет строку лога пользователю, если у него включены логи.
    Тихо игнорирует любые ошибки отправки (например, если пользователь
    заблокировал бота) — логи не должны ронять мониторинг подарков."""
    try:
        if not await get_logs_enabled(owner_id):
            return
        await _get_bot().send_message(owner_id, text)
    except Exception:
        log.debug("Не удалось отправить лог-сообщение пользователю %s", owner_id, exc_info=True)


async def close():
    global _bot
    if _bot is not None:
        try:
            await _bot.session.close()
        except Exception:
            pass
        _bot = None
