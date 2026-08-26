from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.config import ADMIN_ID
from bot.database import has_access, is_technical, get_user
from bot.locales import t


class AccessMiddleware(BaseMiddleware):
    """
    Пропускает /start всегда (там своя логика языка/капчи),
    для остального — проверяет тех.режим и доступ.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        text = None
        if isinstance(event, Message):
            text = event.text
        if text and text.startswith("/start"):
            return await handler(event, data)

        if user.id != ADMIN_ID and await is_technical():
            row = await get_user(user.id)
            lang = row["lang"] if row and row["lang"] else "en"
            if isinstance(event, Message):
                await event.answer(t(lang, "technical_on"))
            elif isinstance(event, CallbackQuery):
                await event.answer(t(lang, "technical_on"), show_alert=True)
            return

        if not await has_access(user.id):
            row = await get_user(user.id)
            lang = row["lang"] if row and row["lang"] else "en"
            if isinstance(event, Message):
                await event.answer(t(lang, "no_access"))
            elif isinstance(event, CallbackQuery):
                await event.answer(t(lang, "no_access"), show_alert=True)
            return

        return await handler(event, data)
