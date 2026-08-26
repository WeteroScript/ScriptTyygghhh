"""
Мониторинг NFT-маркета подарков Telegram и автопокупка.

Логика простая: бот смотрит на самый дешёвый лот перепродажи каждого
подарка, и если его цена попадает в диапазон [SNIPE_MIN_PRICE,
SNIPE_MAX_PRICE] (включительно) — покупает его немедленно.

ВАЖНО: используются raw MTProto функции через Pyrogram (payments.GetStarGifts /
payments.GetResaleStarGifts / payments.GetPaymentForm / payments.SendStarsForm с
InputInvoiceStarGiftResale, payments.GetStarsStatus для баланса). Telegram
время от времени меняет схему этих функций — если что-то перестало
работать, свериться с https://core.telegram.org/api/gifts и поправить
raw-вызовы (номера конструкторов, поля).
"""

import asyncio
import logging
from dataclasses import dataclass

from pyrogram import Client
from pyrogram.raw import functions, types as raw_types

from bot.config import SNIPE_MIN_PRICE, SNIPE_MAX_PRICE, POLL_INTERVAL
from bot.database import get_ignored_gifts

log = logging.getLogger("gift_sniper")

# ключ: (owner_id, phone) -> asyncio.Task
_running_tasks: dict[tuple[int, str], asyncio.Task] = {}
# ключ: (owner_id, phone) -> активный Client (пока задача мониторинга жива).
# Нужен, чтобы другие части бота (раздел "Подарки") переиспользовали ЭТО ЖЕ
# подключение вместо того, чтобы открывать второе на тот же файл сессии —
# два одновременных Client на одну .session сессию ломают её (peer storage
# начинает противоречить сама себе, отсюда "Peer id invalid" и т.п.).
_active_clients: dict[tuple[int, str], Client] = {}


@dataclass
class GiftListing:
    gift_id: str
    name: str
    base_price: int           # обычная (не резельная) цена подарка в звёздах
    resale_price: int | None   # текущая минимальная цена лота на перепродаже (если есть)
    resale_slug: str | None     # идентификатор конкретного лота (нужен для покупки)
    input_invoice: object        # объект, который передаём в оплату (raw type)


async def fetch_gifts(client: Client) -> list[GiftListing]:
    """Список подарков с их актуальной минимальной ценой."""
    result: list[GiftListing] = []
    try:
        gifts_resp = await client.invoke(functions.payments.GetStarGifts(hash=0))
    except Exception:
        log.exception("Не удалось получить список подарков (payments.GetStarGifts)")
        return result

    gifts = getattr(gifts_resp, "gifts", [])
    for g in gifts:
        gift_id = str(g.id)
        name = getattr(g, "title", None) or f"Gift #{gift_id}"
        base_price = getattr(g, "stars", 0)

        resale_price = None
        resale_slug = None
        input_invoice = raw_types.InputInvoiceStarGift(
            peer=raw_types.InputPeerSelf(), gift_id=g.id
        )

        if getattr(g, "availability_resale", None):
            try:
                resale_resp = await client.invoke(
                    functions.payments.GetResaleStarGifts(
                        gift_id=g.id,
                        sort_by_price=True,
                        offset="",
                        limit=1,
                    )
                )
                resale_gifts = getattr(resale_resp, "gifts", [])
                if resale_gifts:
                    cheapest = resale_gifts[0]
                    resale_price = getattr(cheapest, "resell_stars", None) or getattr(
                        cheapest, "stars", None
                    )
                    resale_slug = getattr(cheapest, "slug", None)
                    input_invoice = raw_types.InputInvoiceStarGiftResale(
                        peer=raw_types.InputPeerSelf(),
                        slug=resale_slug,
                        to_id=raw_types.InputPeerSelf(),
                    )
            except Exception as e:
                log.debug("Resale недоступен для %s: %s", gift_id, e)

        result.append(
            GiftListing(
                gift_id=gift_id,
                name=name,
                base_price=base_price,
                resale_price=resale_price,
                resale_slug=resale_slug,
                input_invoice=input_invoice,
            )
        )

    return result


def effective_price(g: GiftListing) -> int:
    return g.resale_price if g.resale_price is not None else g.base_price


def cheapest_gift(gifts: list[GiftListing]) -> GiftListing | None:
    if not gifts:
        return None
    return min(gifts, key=effective_price)


async def get_stars_balance(client: Client) -> int | None:
    """Баланс звёзд на подключённом аккаунте. None, если не удалось получить."""
    try:
        status = await client.invoke(
            functions.payments.GetStarsStatus(peer=raw_types.InputPeerSelf())
        )
        return getattr(status, "balance", None) and getattr(status.balance, "amount", None)
    except Exception as e:
        log.debug("Не удалось получить баланс звёзд: %s", e)
        return None


def should_snipe(g: GiftListing) -> bool:
    """Покупаем только лоты на перепродаже с ценой в диапазоне [MIN, MAX]."""
    if g.resale_price is None:
        return False
    return SNIPE_MIN_PRICE <= g.resale_price <= SNIPE_MAX_PRICE


async def buy_gift(client: Client, g: GiftListing) -> bool:
    try:
        form = await client.invoke(
            functions.payments.GetPaymentForm(invoice=g.input_invoice)
        )
        await client.invoke(
            functions.payments.SendStarsForm(
                form_id=form.form_id,
                invoice=g.input_invoice,
            )
        )
        log.info("Куплен подарок %s (%s) за %s звёзд", g.name, g.gift_id, effective_price(g))
        return True
    except Exception as e:
        log.error("Не удалось купить подарок %s: %s", g.gift_id, e)
        return False


async def _monitor_loop(owner_id: int, phone: str, client: Client):
    log.info("Старт мониторинга для %s / %s", owner_id, phone)
    try:
        while True:
            ignored = await get_ignored_gifts(owner_id)
            gifts = await fetch_gifts(client)
            balance = await get_stars_balance(client)

            for g in gifts:
                if g.gift_id in ignored:
                    continue
                if not should_snipe(g):
                    continue

                price = effective_price(g)
                if balance is not None and balance < price:
                    log.warning(
                        "Недостаточно звёзд на аккаунте %s: нужно %s, есть %s. Пропуск %s",
                        phone, price, balance, g.name,
                    )
                    continue

                bought = await buy_gift(client, g)
                if bought and balance is not None:
                    balance -= price  # чтобы не пытаться купить два подарка подряд без баланса

            await asyncio.sleep(POLL_INTERVAL)
    except asyncio.CancelledError:
        log.info("Мониторинг остановлен для %s / %s", owner_id, phone)
        raise


def is_running(owner_id: int, phone: str) -> bool:
    task = _running_tasks.get((owner_id, phone))
    return bool(task and not task.done())


def get_running_client(owner_id: int, phone: str) -> Client | None:
    """Возвращает уже подключённый Client, если для этого аккаунта запущен
    мониторинг. Используй это вместо создания нового Client на тот же
    файл сессии — иначе два подключения начнут конфликтовать."""
    if is_running(owner_id, phone):
        return _active_clients.get((owner_id, phone))
    return None


async def start_sniper(owner_id: int, phone: str, client: Client):
    key = (owner_id, phone)
    if is_running(owner_id, phone):
        return
    if not client.is_connected:
        await client.start()
    _active_clients[key] = client
    task = asyncio.create_task(_monitor_loop(owner_id, phone, client))
    _running_tasks[key] = task


async def stop_sniper(owner_id: int, phone: str):
    key = (owner_id, phone)
    task = _running_tasks.pop(key, None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    client = _active_clients.pop(key, None)
    if client and client.is_connected:
        try:
            await client.stop()
        except Exception:
            log.exception("Ошибка при остановке клиента %s/%s", owner_id, phone)
