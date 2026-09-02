from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import SNIPE_MIN_PRICE, SNIPE_MAX_PRICE
from bot.database import get_user, set_lang, get_price_range, set_price_range
from bot.locales import t
from bot.keyboards import settings_kb, lang_kb_settings, main_menu_kb
from bot.utils import safe_edit_text

router = Router()


class PriceSettings(StatesGroup):
    waiting_min = State()
    waiting_max = State()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


@router.callback_query(F.data == "menu:settings")
async def open_settings(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    await safe_edit_text(call.message, t(lang, "settings_title"), reply_markup=settings_kb(lang))
    await call.answer()


@router.callback_query(F.data == "settings:lang")
async def change_lang(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    await safe_edit_text(call.message, t(lang, "choose_lang"), reply_markup=lang_kb_settings())
    await call.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def set_lang_from_settings(call: CallbackQuery):
    new_lang = call.data.split(":")[1]
    await set_lang(call.from_user.id, new_lang)
    await safe_edit_text(call.message, t(new_lang, "lang_set"))
    await call.message.answer(t(new_lang, "main_menu"), reply_markup=main_menu_kb(new_lang))
    await call.answer()


@router.callback_query(F.data == "settings:price")
async def change_price(call: CallbackQuery, state: FSMContext):
    lang = await _lang_of(call.from_user.id)
    owner_id = call.from_user.id
    custom_min, custom_max = await get_price_range(owner_id)
    current_min = custom_min if custom_min is not None else SNIPE_MIN_PRICE
    current_max = custom_max if custom_max is not None else SNIPE_MAX_PRICE

    await state.set_state(PriceSettings.waiting_min)
    await state.update_data(lang=lang)
    text = t(lang, "price_current", min=current_min, max=current_max) + "\n\n" + t(lang, "price_ask_min")
    await call.message.answer(text)
    await call.answer()


@router.message(PriceSettings.waiting_min)
async def price_min_entered(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    try:
        value = int(message.text.strip())
        if value < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(t(lang, "price_invalid_number"))
        return

    await state.update_data(min_price=value)
    await state.set_state(PriceSettings.waiting_max)
    await message.answer(t(lang, "price_ask_max"))


@router.message(PriceSettings.waiting_max)
async def price_max_entered(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    min_price = data.get("min_price")

    try:
        value = int(message.text.strip())
        if value < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(t(lang, "price_invalid_number"))
        return

    if value < min_price:
        await message.answer(t(lang, "price_invalid_range"))
        return

    await set_price_range(message.from_user.id, min_price, value)
    await state.clear()
    await message.answer(t(lang, "price_saved", min=min_price, max=value))
