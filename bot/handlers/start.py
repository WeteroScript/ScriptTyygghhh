import random

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import ADMIN_ID
from bot.database import ensure_user, get_user, set_lang, set_captcha_passed
from bot.locales import t
from bot.keyboards import lang_kb, main_menu_kb
from bot.utils import safe_edit_text

router = Router()


class CaptchaState(StatesGroup):
    waiting_answer = State()


def _new_captcha():
    a, b = random.randint(2, 9), random.randint(2, 9)
    op = random.choice(["+", "-", "*"])
    answer = {"+": a + b, "-": a - b, "*": a * b}[op]
    return a, op, b, answer


async def _send_main_menu(message: Message, lang: str):
    await message.answer(t(lang, "main_menu"), reply_markup=main_menu_kb(lang))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await ensure_user(user_id)

    if user_id == ADMIN_ID:
        await _send_main_menu(message, "ru")
        return

    row = await get_user(user_id)

    if not row["lang"]:
        await message.answer(t("en", "choose_lang"), reply_markup=lang_kb())
        return

    lang = row["lang"]
    if not row["captcha_passed"]:
        await _ask_captcha(message, state, lang)
        return

    await _send_main_menu(message, lang)


@router.callback_query(F.data.startswith("lang:"))
async def on_lang_chosen(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":")[1]
    await set_lang(call.from_user.id, lang)
    await safe_edit_text(call.message, t(lang, "lang_set"))
    await _ask_captcha(call.message, state, lang)
    await call.answer()


async def _ask_captcha(message: Message, state: FSMContext, lang: str):
    a, op, b, answer = _new_captcha()
    await state.set_state(CaptchaState.waiting_answer)
    await state.update_data(answer=answer, lang=lang)
    await message.answer(t(lang, "captcha_ask", a=a, op=op, b=b))


@router.message(CaptchaState.waiting_answer)
async def on_captcha_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    try:
        user_answer = int(message.text.strip())
    except (ValueError, AttributeError):
        user_answer = None

    if user_answer == data.get("answer"):
        await set_captcha_passed(message.from_user.id, True)
        await state.clear()
        await message.answer(t(lang, "captcha_ok"))
        await _send_main_menu(message, lang)
    else:
        a, op, b, answer = _new_captcha()
        await state.update_data(answer=answer)
        await message.answer(t(lang, "captcha_wrong") + f"\n\n{a} {op} {b} = ?")


@router.callback_query(F.data == "menu:main")
async def back_to_main(call: CallbackQuery):
    row = await get_user(call.from_user.id)
    lang = row["lang"] if row and row["lang"] else "ru"
    await safe_edit_text(call.message, t(lang, "main_menu"), reply_markup=main_menu_kb(lang))
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    """Кнопка-индикатор (например, номер страницы) — просто гасит "часики"."""
    await call.answer()
