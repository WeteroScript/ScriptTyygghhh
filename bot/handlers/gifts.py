import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import get_user, list_accounts, get_ignored_gifts, toggle_ignore
from bot.locales import t
from bot.keyboards import gifts_kb
from bot.services import session_manager, gift_sniper
from bot.utils import safe_edit_text

router = Router()
log = logging.getLogger("handlers.gifts")

# Сколько кнопок-подарков показываем на одной странице (ограничение
# Telegram на суммарный размер inline-клавиатуры одного сообщения не
# позволяет выводить сразу сотни кнопок).
PAGE_SIZE = 8


async def _lang_of(user_id: int) -> str:
    row = await get_user(user_id)
    return row["lang"] if row and row["lang"] else "ru"


async def _get_client_for_gifts(owner_id: int):
    """
    Возвращает (client, is_temporary).

    Если хотя бы один из аккаунтов пользователя уже мониторится (нажат
    "старт") — переиспользуем ЕГО подключение. Открывать второе
    подключение на тот же файл сессии нельзя: они начинают конфликтовать
    и ломают сессию (sqlite "database is locked" и т.п.).

    Если запущенных аккаунтов нет — поднимаем временное подключение на
    первом добавленном аккаунте (под блокировкой, чтобы не столкнуться с
    одновременным нажатием "старт" на тот же аккаунт), читаем подарки и
    сразу его закрываем.
    """
    accounts = await list_accounts(owner_id)
    if not accounts:
        return None, False

    for acc in accounts:
        client = gift_sniper.get_running_client(owner_id, acc["phone"])
        if client:
            return client, False

    phone = accounts[0]["phone"]
    key = (owner_id, phone)
    async with gift_sniper.get_lock(key):
        # перепроверяем — вдруг мониторинг успел запуститься, пока ждали лок
        client = gift_sniper.get_running_client(owner_id, phone)
        if client:
            return client, False

        client = session_manager.make_client(owner_id, phone)
        try:
            await gift_sniper.connect_with_retry(client)
        except Exception:
            log.exception("Не удалось временно подключиться к аккаунту %s для чтения подарков", phone)
            return None, False
        return client, True


async def _fetch_market_gifts(owner_id: int):
    """Возвращает (gifts_sorted, error) — только подарки, реально
    выставленные на маркете (не весь каталог магазина), отсортированные
    по возрастанию цены. error=True, если подключиться/получить не удалось."""
    client, temporary = await _get_client_for_gifts(owner_id)
    if client is None:
        return [], True

    try:
        all_gifts = await gift_sniper.fetch_gifts(client)
    finally:
        if temporary:
            try:
                await client.disconnect()
            except Exception:
                log.exception("Не удалось закрыть временное подключение")

    market_gifts = gift_sniper.filter_market_gifts(all_gifts)
    market_gifts.sort(key=gift_sniper.effective_price)
    return market_gifts, False


async def _render_gifts_page(call: CallbackQuery, page: int):
    lang = await _lang_of(call.from_user.id)
    owner_id = call.from_user.id

    gifts_sorted, error = await _fetch_market_gifts(owner_id)
    if error:
        await call.answer(t(lang, "no_gifts_found"), show_alert=True)
        return
    if not gifts_sorted:
        await call.answer(t(lang, "no_market_gifts"), show_alert=True)
        return

    total = len(gifts_sorted)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    page_items = gifts_sorted[start:start + PAGE_SIZE]

    cheapest = gifts_sorted[0]
    ignored = await get_ignored_gifts(owner_id)

    text = t(lang, "gifts_title") + "\n\n" + t(
        lang, "cheapest_gift", name=cheapest.name, price=gift_sniper.effective_price(cheapest)
    )
    text += "\n\n" + t(lang, "gifts_page_info", page=page + 1, total_pages=total_pages, total=total)

    kb_items = [
        {"id": g.gift_id, "name": g.name, "price": gift_sniper.effective_price(g)}
        for g in page_items
    ]
    await safe_edit_text(
        call.message,
        text,
        reply_markup=gifts_kb(kb_items, ignored, page=page, total_pages=total_pages),
    )
    await call.answer()


@router.callback_query(F.data == "menu:gifts")
async def open_gifts(call: CallbackQuery):
    await _render_gifts_page(call, page=0)


@router.callback_query(F.data.startswith("gifts:page:"))
async def paginate_gifts(call: CallbackQuery):
    page = int(call.data.split(":", 2)[2])
    await _render_gifts_page(call, page=page)


@router.callback_query(F.data.startswith("gift:toggle:"))
async def toggle_gift(call: CallbackQuery):
    owner_id = call.from_user.id
    _, _, page_str, gift_id = call.data.split(":", 3)
    await toggle_ignore(owner_id, gift_id)
    await _render_gifts_page(call, page=int(page_str))
