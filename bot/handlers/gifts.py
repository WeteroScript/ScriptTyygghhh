from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_user, list_accounts, get_ignored_gifts, toggle_ignore
from bot.locales import t
from bot.keyboards import gifts_kb
from bot.services import session_manager, gift_sniper

router = Router()


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


async def _any_client(owner_id: int):
    """Берём первый добавленный аккаунт пользователя, чтобы просто прочитать список подарков."""
    accounts = await list_accounts(owner_id)
    if not accounts:
        return None
    phone = accounts[0]["phone"]
    client = session_manager.make_client(owner_id, phone)
    if not client.is_connected:
        await client.start()
    return client


@router.callback_query(F.data == "menu:gifts")
async def open_gifts(call: CallbackQuery):
    lang = await _lang_of(call.from_user.id)
    owner_id = call.from_user.id

    client = await _any_client(owner_id)
    if client is None:
        await call.answer(t(lang, "no_gifts_found"), show_alert=True)
        return

    gifts = await gift_sniper.fetch_gifts(client)
    if not gifts:
        await call.answer(t(lang, "no_gifts_found"), show_alert=True)
        return

    gifts_sorted = sorted(gifts, key=gift_sniper.effective_price)
    cheapest = gifts_sorted[0]
    ignored = await get_ignored_gifts(owner_id)

    text = t(lang, "gifts_title") + "\n\n" + t(
        lang, "cheapest_gift", name=cheapest.name, price=gift_sniper.effective_price(cheapest)
    )
    kb_items = [
        {"id": g.gift_id, "name": g.name, "price": gift_sniper.effective_price(g)}
        for g in gifts_sorted
    ]
    await call.message.edit_text(text, reply_markup=gifts_kb(kb_items, ignored))
    await call.answer()


@router.callback_query(F.data.startswith("gift:toggle:"))
async def toggle_gift(call: CallbackQuery):
    owner_id = call.from_user.id
    gift_id = call.data.split(":", 2)[2]
    await toggle_ignore(owner_id, gift_id)
    # перерисовываем список
    await open_gifts(call)
