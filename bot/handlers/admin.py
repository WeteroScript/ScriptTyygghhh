from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import ADMIN_ID
from bot.database import (
    get_user, set_access, is_technical, set_technical,
)
from bot.locales import t
from bot.services import gift_sniper
from bot.database import all_running_accounts
from bot.utils import safe_edit_text

router = Router()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


def _admin_only(message_or_call) -> bool:
    return message_or_call.from_user.id == ADMIN_ID


@router.callback_query(F.data == "menu:admin")
async def open_admin(call: CallbackQuery):
    if not _admin_only(call):
        await call.answer(t(await _lang_of(call.from_user.id), "no_access"), show_alert=True)
        return
    lang = await _lang_of(call.from_user.id)
    await safe_edit_text(call.message, t(lang, "admin_title"))
    await call.answer()


async def _resolve_target(bot: Bot, raw: str):
    raw = raw.strip()
    if raw.startswith("@"):
        chat = await bot.get_chat(raw)
        return chat.id
    return int(raw)


@router.message(Command("giveaccess"))
async def cmd_giveaccess(message: Message, bot: Bot):
    if not _admin_only(message):
        return
    lang = await _lang_of(message.from_user.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /giveaccess <id|@username>")
        return
    try:
        target_id = await _resolve_target(bot, args[1])
    except Exception as e:
        await message.answer(f"Не удалось найти пользователя: {e}")
        return
    await set_access(target_id, True)
    await message.answer(t(lang, "access_given", who=args[1]))


@router.message(Command("unaccess"))
async def cmd_unaccess(message: Message, bot: Bot):
    if not _admin_only(message):
        return
    lang = await _lang_of(message.from_user.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /unaccess <id|@username>")
        return
    try:
        target_id = await _resolve_target(bot, args[1])
    except Exception as e:
        await message.answer(f"Не удалось найти пользователя: {e}")
        return
    await set_access(target_id, False)
    await message.answer(t(lang, "access_removed", who=args[1]))


@router.message(Command("technical"))
async def cmd_technical(message: Message):
    if not _admin_only(message):
        return
    lang = await _lang_of(message.from_user.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or args[1].strip().lower() not in ("on", "off"):
        await message.answer("Использование: /technical on|off")
        return
    state = args[1].strip().lower() == "on"
    await set_technical(state)
    await message.answer(t(lang, "technical_set", state="ON" if state else "OFF"))


@router.message(Command("sessions"))
async def cmd_sessions(message: Message):
    if not _admin_only(message):
        return
    lang = await _lang_of(message.from_user.id)
    rows = await all_running_accounts()
    if not rows:
        await message.answer(t(lang, "no_sessions"))
        return
    lines = [t(lang, "sessions_title")]
    for r in rows:
        running = gift_sniper.is_running(r["owner_id"], r["phone"])
        lines.append(f"• owner={r['owner_id']} phone={r['phone']} running={'✅' if running else '❌'}")
    await message.answer("\n".join(lines))
