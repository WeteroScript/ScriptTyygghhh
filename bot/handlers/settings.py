from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_user, set_lang
from bot.locales import t
from bot.keyboards import settings_kb, lang_kb_settings, main_menu_kb

router = Router()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


@router.callback_query(F.data == "menu:settings")
async def open_settings(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    await call.message.edit_text(t(lang, "settings_title"), reply_markup=settings_kb(lang))
    await call.answer()


@router.callback_query(F.data == "settings:lang")
async def change_lang(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    await call.message.edit_text(t(lang, "choose_lang"), reply_markup=lang_kb_settings())
    await call.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def set_lang_from_settings(call: CallbackQuery):
    new_lang = call.data.split(":")[1]
    await set_lang(call.from_user.id, new_lang)
    await call.message.edit_text(t(new_lang, "lang_set"))
    await call.message.answer(t(new_lang, "main_menu"), reply_markup=main_menu_kb(new_lang))
    await call.answer()
