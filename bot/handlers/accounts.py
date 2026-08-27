import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired, PasswordHashInvalid,
)

from bot.database import (
    get_user, list_accounts, add_account, remove_account,
    get_account, set_account_running,
)
from bot.locales import t
from bot.keyboards import accounts_menu_kb, accounts_remove_kb, account_control_kb
from bot.services import session_manager, gift_sniper
from bot.utils import safe_edit_text, safe_edit_reply_markup

router = Router()

# Код должен вводиться строго как "code" + сами цифры без пробела,
# например: code12345. Это же защищает от автоматической блокировки
# кода Telegram, если его "чистый" текст засветится где-то ещё.
CODE_PATTERN = re.compile(r"^code(\d{4,7})$", re.IGNORECASE)


class AddAccount(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


@router.callback_query(F.data == "menu:accounts")
async def open_accounts(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    accounts = await list_accounts(call.from_user.id)
    await safe_edit_text(call.message, t(lang, "accounts_title"), reply_markup=accounts_menu_kb(lang, accounts))
    await call.answer()


@router.callback_query(F.data == "acc:add")
async def add_account_start(call: CallbackQuery, state: FSMContext):
    lang = await _lang_of(call.from_user.id)
    await state.set_state(AddAccount.waiting_phone)
    await safe_edit_text(call.message, t(lang, "send_phone"))
    await call.answer()


@router.message(AddAccount.waiting_phone)
async def add_account_phone(message: Message, state: FSMContext):
    lang = await _lang_of(message.from_user.id)
    phone = message.text.strip()
    try:
        phone_code_hash = await session_manager.start_login(message.from_user.id, phone)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    await state.update_data(phone=phone, phone_code_hash=phone_code_hash)
    await state.set_state(AddAccount.waiting_code)
    await message.answer(t(lang, "send_code"))


@router.message(AddAccount.waiting_code)
async def add_account_code(message: Message, state: FSMContext):
    lang = await _lang_of(message.from_user.id)
    data = await state.get_data()
    phone = data["phone"]
    owner_id = message.from_user.id
    raw = (message.text or "").strip()

    match = CODE_PATTERN.match(raw)
    if not match:
        await message.answer(t(lang, "code_format_wrong"))
        return
    code = match.group(1)

    try:
        await session_manager.submit_code(owner_id, phone, data["phone_code_hash"], code)
    except SessionPasswordNeeded:
        await state.set_state(AddAccount.waiting_password)
        await message.answer(t(lang, "send_2fa"))
        return
    except (PhoneCodeInvalid, PhoneCodeExpired) as e:
        await message.answer(t(lang, "code_invalid", error=str(e)))
        session_manager.cancel_pending(owner_id)
        await state.clear()
        return

    session_name = session_manager.get_session_name(owner_id, phone)
    await add_account(owner_id, phone, session_name)
    await state.clear()
    await message.answer(t(lang, "account_added", phone=phone))


@router.message(AddAccount.waiting_password)
async def add_account_password(message: Message, state: FSMContext):
    lang = await _lang_of(message.from_user.id)
    data = await state.get_data()
    phone = data["phone"]
    owner_id = message.from_user.id
    try:
        await session_manager.submit_password(owner_id, message.text.strip())
    except PasswordHashInvalid:
        # неверный пароль 2FA — даём ввести ещё раз, не сбрасывая процесс
        await message.answer(t(lang, "password_wrong"))
        return
    except Exception as e:
        await message.answer(t(lang, "password_error", error=str(e)))
        session_manager.cancel_pending(owner_id)
        await state.clear()
        return

    session_name = session_manager.get_session_name(owner_id, phone)
    await add_account(owner_id, phone, session_name)
    await state.clear()
    await message.answer(t(lang, "account_added", phone=phone))


@router.callback_query(F.data == "acc:remove_menu")
async def remove_account_menu(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    accounts = await list_accounts(call.from_user.id)
    if not accounts:
        await call.answer(t(lang, "no_accounts"), show_alert=True)
        return
    await safe_edit_text(call.message, t(lang, "choose_account_remove"), reply_markup=accounts_remove_kb(lang, accounts))
    await call.answer()


@router.callback_query(F.data.startswith("acc:del:"))
async def remove_account_confirmed(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    phone = call.data.split(":", 2)[2]
    owner_id = call.from_user.id
    await gift_sniper.stop_sniper(owner_id, phone)
    session_manager.delete_session_file(owner_id, phone)
    await remove_account(owner_id, phone)
    await call.answer(t(lang, "account_removed", phone=phone), show_alert=True)
    accounts = await list_accounts(owner_id)
    await safe_edit_text(call.message, t(lang, "accounts_title"), reply_markup=accounts_menu_kb(lang, accounts))


@router.callback_query(F.data.startswith("acc:open:"))
async def open_account_control(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    phone = call.data.split(":", 2)[2]
    running = gift_sniper.is_running(call.from_user.id, phone)
    await safe_edit_text(call.message, 
        t(lang, "account_menu_title", phone=phone),
        reply_markup=account_control_kb(lang, phone, running),
    )
    await call.answer()


@router.callback_query(F.data.startswith("acc:start:"))
async def start_account_sniper(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    phone = call.data.split(":", 2)[2]
    owner_id = call.from_user.id
    acc = await get_account(owner_id, phone)
    if not acc:
        await call.answer(t(lang, "no_accounts"), show_alert=True)
        return
    client = session_manager.make_client(owner_id, phone)
    await gift_sniper.start_sniper(owner_id, phone, client)
    await set_account_running(owner_id, phone, True)
    await call.answer(t(lang, "sniper_started", phone=phone), show_alert=True)
    await safe_edit_reply_markup(call.message, reply_markup=account_control_kb(lang, phone, True))


@router.callback_query(F.data.startswith("acc:stop:"))
async def stop_account_sniper(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    phone = call.data.split(":", 2)[2]
    owner_id = call.from_user.id
    await gift_sniper.stop_sniper(owner_id, phone)
    await set_account_running(owner_id, phone, False)
    await call.answer(t(lang, "sniper_stopped", phone=phone), show_alert=True)
    await safe_edit_reply_markup(call.message, reply_markup=account_control_kb(lang, phone, False))
