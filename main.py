import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.database import init_db, all_running_accounts
from bot.middlewares.access import AccessMiddleware
from bot.services import session_manager, gift_sniper

from bot.handlers import start, accounts, gifts, settings, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("main")


async def _resume_running_accounts():
    """После рестарта бота снова запускает мониторинг для аккаунтов,
    у которых is_running=1 в базе (например, бот перезапустился на хостинге).
    start_sniper сам подключается через connect_with_retry, поэтому
    временная блокировка файла сессии от ещё не закрывшегося старого
    процесса не приводит к падению."""
    rows = await all_running_accounts()
    for r in rows:
        owner_id, phone = r["owner_id"], r["phone"]
        try:
            client = session_manager.make_client(owner_id, phone)
            await gift_sniper.start_sniper(owner_id, phone, client)
            log.info("Восстановлен мониторинг для %s / %s", owner_id, phone)
        except Exception as e:
            log.error("Не удалось восстановить сессию %s/%s: %s", owner_id, phone, e)


async def main():
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(gifts.router)
    dp.include_router(settings.router)
    dp.include_router(admin.router)

    await _resume_running_accounts()

    log.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        # Важно при передеплое/остановке на хостинге: если процесс убьют
        # без этого блока, MTProto-подключения останутся "подвешенными",
        # а файлы сессий — не до конца освобождёнными для следующего
        # запуска (отсюда "database is locked" и "Task was destroyed but
        # it is pending" в логах при рестарте).
        log.info("Останавливаю активные подключения перед выходом...")
        await gift_sniper.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
