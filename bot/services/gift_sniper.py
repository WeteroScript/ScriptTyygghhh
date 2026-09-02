"""
Мониторинг NFT-маркета подарков Telegram и автопокупка (на Telethon).

Логика простая: бот смотрит на самый дешёвый лот перепродажи каждого
подарка, и если его цена попадает в диапазон [SNIPE_MIN_PRICE,
SNIPE_MAX_PRICE] (включительно) — покупает его немедленно.

ВАЖНО: используются raw MTProto функции через Telethon (payments.GetStarGifts /
payments.GetResaleStarGifts / payments.GetPaymentForm / payments.SendStarsForm с
InputInvoiceStarGiftResale, payments.GetStarsStatus для баланса). Актуальная
схема (проверено по https://core.telegram.org/api/gifts и
https://tl.telethon.dev): цена лота на перепродаже лежит в поле
`resell_amount` (список StarsAmount/StarsTonAmount), а НЕ в `stars` — это
поле только у обычных (не аукционных) позиций подарка.

Telegram время от времени меняет схему — если что-то перестало работать,
свериться с документацией выше и поправить raw-вызовы.
"""

import asyncio
import logging
from dataclasses import dataclass

from telethon import TelegramClient, functions, types

from bot.config import SNIPE_MIN_PRICE, SNIPE_MAX_PRICE, POLL_INTERVAL
from bot.database import get_ignored_gifts, get_price_range
from bot.services import notifier

log = logging.getLogger("gift_sniper")

# ключ: (owner_id, phone) -> asyncio.Task
_running_tasks: dict[tuple[int, str], asyncio.Task] = {}
# ключ: (owner_id, phone) -> активный TelegramClient (пока задача мониторинга жива).
_active_clients: dict[tuple[int, str], TelegramClient] = {}
# ключ: (owner_id, phone) -> asyncio.Lock — не даёт двум подключениям
# одновременно открыться на один и тот же файл сессии (иначе sqlite
# сессии ловит "database is locked" и session-хранилище портится).
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def get_lock(key: tuple[int, str]) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def connect_with_retry(client: TelegramClient, attempts: int = 5, delay: float = 2.0):
    """
    Подключение с повтором при "database is locked" — эта ошибка почти
    всегда временная: старый процесс бота (например, при передеплое на
    хостинге) на секунду-две ещё держит файл сессии, пока не завершится
    сам. Вместо немедленного отказа даём ему время закрыться.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            await client.connect()
            return
        except Exception as e:
            last_error = e
            if "database is locked" in str(e).lower() and attempt < attempts:
                log.warning(
                    "Файл сессии временно занят (попытка %s/%s), жду %.0fс",
                    attempt, attempts, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
    raise last_error


@dataclass
class GiftListing:
    gift_id: str
    name: str
    base_price: int            # обычная (не резельная) цена подарка в звёздах
    resale_price: int | None    # текущая минимальная цена лота на перепродаже (если есть)
    resale_slug: str | None      # идентификатор конкретного лота (нужен для покупки)
    input_invoice: object          # объект, который передаём в оплату (raw type)


def _extract_stars_amount(amounts) -> int | None:
    """
    resell_amount — список StarsAmount/StarsTonAmount. Нас интересует
    именно вариант в звёздах (StarsAmount), не в TON.
    """
    if not amounts:
        return None
    for a in amounts:
        if a.__class__.__name__ == "StarsAmount":
            return int(getattr(a, "amount", 0))
    return None


async def fetch_gifts(client: TelegramClient) -> list[GiftListing]:
    """Список подарков с их актуальной минимальной ценой."""
    result: list[GiftListing] = []
    try:
        gifts_resp = await client(functions.payments.GetStarGiftsRequest(hash=0))
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
        input_invoice = types.InputInvoiceStarGift(
            peer=types.InputPeerSelf(), gift_id=g.id
        )

        if getattr(g, "availability_resale", None):
            try:
                resale_resp = await client(
                    functions.payments.GetResaleStarGiftsRequest(
                        gift_id=g.id,
                        sort_by_price=True,
                        offset="",
                        limit=1,
                    )
                )
                resale_gifts = getattr(resale_resp, "gifts", [])
                if resale_gifts:
                    cheapest = resale_gifts[0]
                    resale_price = _extract_stars_amount(getattr(cheapest, "resell_amount", None))
                    resale_slug = getattr(cheapest, "slug", None)
                    if resale_slug:
                        input_invoice = types.InputInvoiceStarGiftResale(
                            slug=resale_slug,
                            to_id=types.InputPeerSelf(),
                        )
            except Exception:
                log.debug("Resale недоступен для %s", gift_id, exc_info=True)

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


def on_market(g: GiftListing) -> bool:
    """True, если у подарка есть реальный активный лот на перепродаже
    (маркете) — а не просто позиция в каталоге магазина."""
    return g.resale_price is not None


def filter_market_gifts(gifts: list["GiftListing"]) -> list["GiftListing"]:
    """Оставляет только те подарки, что реально выставлены на маркете."""
    return [g for g in gifts if on_market(g)]


def cheapest_gift(gifts: list[GiftListing]) -> GiftListing | None:
    if not gifts:
        return None
    return min(gifts, key=effective_price)


async def get_effective_price_range(owner_id: int) -> tuple[int, int]:
    """Диапазон цены для снайпинга этого пользователя: кастомный, если
    он его настроил в разделе "Настройки", иначе — из переменных
    окружения (значения по умолчанию для всех)."""
    custom_min, custom_max = await get_price_range(owner_id)
    min_price = custom_min if custom_min is not None else SNIPE_MIN_PRICE
    max_price = custom_max if custom_max is not None else SNIPE_MAX_PRICE
    return min_price, max_price


async def get_stars_balance(client: TelegramClient) -> int | None:
    """Баланс звёзд на подключённом аккаунте. None, если не удалось получить."""
    try:
        status = await client(
            functions.payments.GetStarsStatusRequest(peer=types.InputPeerSelf())
        )
        balance = getattr(status, "balance", None)
        if balance is None:
            return None
        return int(getattr(balance, "amount", 0))
    except Exception:
        log.debug("Не удалось получить баланс звёзд", exc_info=True)
        return None


def should_snipe(g: GiftListing, min_price: int, max_price: int) -> bool:
    """Покупаем только лоты на перепродаже с ценой в диапазоне [min, max]."""
    if g.resale_price is None:
        return False
    return min_price <= g.resale_price <= max_price


async def buy_gift(client: TelegramClient, g: GiftListing) -> bool:
    try:
        form = await client(
            functions.payments.GetPaymentFormRequest(invoice=g.input_invoice)
        )
        await client(
            functions.payments.SendStarsFormRequest(
                form_id=form.form_id,
                invoice=g.input_invoice,
            )
        )
        log.info("Куплен подарок %s (%s) за %s звёзд", g.name, g.gift_id, effective_price(g))
        return True
    except Exception as e:
        msg = str(e).upper()
        if "FORM_EXPIRED" in msg:
            # Форма оплаты живёт 10 минут — лот мог "протухнуть" между
            # тем, как мы его увидели, и попыткой купить. Это нормальная
            # ситуация при снайпинге, не ошибка кода: просто пропускаем,
            # следующий цикл опроса возьмёт актуальный лот заново.
            log.warning("Форма оплаты истекла для %s, лот больше не актуален", g.gift_id)
        elif "BALANCE_TOO_LOW" in msg:
            log.warning("Недостаточно звёзд для покупки %s (сервер отклонил платёж)", g.gift_id)
        else:
            log.exception("Не удалось купить подарок %s", g.gift_id)
        return False


async def _monitor_loop(owner_id: int, phone: str, client: TelegramClient):
    log.info("Старт мониторинга для %s / %s", owner_id, phone)
    try:
        while True:
            ignored = await get_ignored_gifts(owner_id)
            min_price, max_price = await get_effective_price_range(owner_id)
            gifts = await fetch_gifts(client)
            market_gifts = [g for g in filter_market_gifts(gifts) if g.gift_id not in ignored]

            if market_gifts:
                names = ", ".join(f"«{g.name}»" for g in market_gifts)
                await notifier.send_log(owner_id, f"🔍 Просмотр лотов подарка {names}")

            balance = await get_stars_balance(client)

            for g in market_gifts:
                if not should_snipe(g, min_price, max_price):
                    continue

                price = effective_price(g)
                await notifier.send_log(
                    owner_id, f"🎯 Найден подарок «{g.name}» за {price}⭐, покупка..."
                )

                if balance is not None and balance < price:
                    log.warning(
                        "Недостаточно звёзд на аккаунте %s: нужно %s, есть %s. Пропуск %s",
                        phone, price, balance, g.name,
                    )
                    await notifier.send_log(
                        owner_id, f"❌ Недостаточно звёзд для «{g.name}» (нужно {price}⭐)"
                    )
                    continue

                bought = await buy_gift(client, g)
                if bought:
                    await notifier.send_log(owner_id, f"✅ Куплено: «{g.name}» за {price}⭐")
                    if balance is not None:
                        balance -= price  # чтобы не пытаться купить два подарка подряд без баланса
                else:
                    await notifier.send_log(owner_id, f"❌ Не удалось купить «{g.name}»")

            await asyncio.sleep(POLL_INTERVAL)
    except asyncio.CancelledError:
        log.info("Мониторинг остановлен для %s / %s", owner_id, phone)
        raise


def is_running(owner_id: int, phone: str) -> bool:
    task = _running_tasks.get((owner_id, phone))
    return bool(task and not task.done())


def get_running_client(owner_id: int, phone: str) -> TelegramClient | None:
    """Возвращает уже подключённый Client, если для этого аккаунта запущен
    мониторинг. Используй это вместо создания нового Client на тот же
    файл сессии — иначе два подключения начнут конфликтовать."""
    if is_running(owner_id, phone):
        return _active_clients.get((owner_id, phone))
    return None


async def start_sniper(owner_id: int, phone: str, client: TelegramClient):
    key = (owner_id, phone)
    if is_running(owner_id, phone):
        return
    async with get_lock(key):
        if is_running(owner_id, phone):
            return
        if not client.is_connected():
            await connect_with_retry(client)
        _active_clients[key] = client
        task = asyncio.create_task(_monitor_loop(owner_id, phone, client))
        _running_tasks[key] = task


async def stop_sniper(owner_id: int, phone: str):
    key = (owner_id, phone)
    async with get_lock(key):
        task = _running_tasks.pop(key, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        client = _active_clients.pop(key, None)
        if client and client.is_connected():
            try:
                await client.disconnect()
            except Exception:
                log.exception("Ошибка при остановке клиента %s/%s", owner_id, phone)


async def stop_all():
    """
    Останавливает все активные подключения. Вызывается при graceful
    shutdown бота (SIGTERM от хостинга при передеплое) — чтобы файлы
    сессий гарантированно освобождались и следующий запуск не ловил
    "database is locked" из-за ещё не закрытого предыдущего процесса.
    """
    keys = list(_running_tasks.keys())
    for owner_id, phone in keys:
        try:
            await stop_sniper(owner_id, phone)
        except Exception:
            log.exception("Ошибка при остановке %s/%s во время shutdown", owner_id, phone)
