from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_user, get_logs_enabled, set_logs_enabled
from bot.locales import t
from bot.keyboards import logs_kb
from bot.utils import safe_edit_text

router = Router()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


@router.callback_query(F.data == "menu:logs")
async def open_logs(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    enabled = await get_logs_enabled(call.from_user.id)
    await safe_edit_text(call.message, t(lang, "logs_title"), reply_markup=logs_kb(lang, enabled))
    await call.answer()


@router.callback_query(F.data == "logs:toggle")
async def toggle_logs(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    owner_id = call.from_user.id
    enabled = await get_logs_enabled(owner_id)
    await set_logs_enabled(owner_id, not enabled)
    await safe_edit_text(call.message, t(lang, "logs_title"), reply_markup=logs_kb(lang, not enabled))
    await call.answer()
