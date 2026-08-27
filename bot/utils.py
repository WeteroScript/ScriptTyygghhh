"""Общие мелкие утилиты для хендлеров."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, InlineKeyboardMarkup

log = logging.getLogger("utils")


async def safe_edit_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """
    Обёртка над message.edit_text, которая не падает, если Telegram
    отвечает "message is not modified" (это происходит, когда текст и
    клавиатура не изменились — например, пользователь дважды подряд нажал
    одну и ту же кнопку меню). Без этой обёртки такое исключение валит
    весь хендлер и выглядит как "кнопка не работает".
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        log.exception("Не удалось отредактировать сообщение")
        raise


async def safe_edit_reply_markup(message: Message, reply_markup: InlineKeyboardMarkup | None = None):
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        log.exception("Не удалось обновить клавиатуру сообщения")
        raise
