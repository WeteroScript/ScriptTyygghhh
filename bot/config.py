import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default=None):
    val = os.getenv(name, default)
    return int(val) if val is not None else None


BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH")
ADMIN_ID = _int("ADMIN_ID")

def _float(name: str, default=None):
    val = os.getenv(name, default)
    return float(val) if val is not None else None


# Покупаем любой лот на перепродаже, чья цена попадает в этот диапазон
# (включительно), независимо от обычной цены подарка и его истории.
SNIPE_MIN_PRICE = _int("SNIPE_MIN_PRICE", "125")
SNIPE_MAX_PRICE = _int("SNIPE_MAX_PRICE", "275")

POLL_INTERVAL = _int("POLL_INTERVAL", "5")

# Пауза между проверкой лотов КАЖДОГО отдельного подарка внутри одного
# цикла опроса (payments.GetResaleStarGifts дёргается по одному подарку
# за раз). Без этой паузы Telegram быстро включает антифлуд
# (FLOOD_WAIT на GetResaleStarGiftsRequest), если подарков с активной
# перепродажей много.
GIFT_CHECK_DELAY = _float("GIFT_CHECK_DELAY", "1.5")

DB_PATH = os.getenv("DB_PATH", "bot/database.sqlite3")
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")
if not API_ID or not API_HASH:
    raise RuntimeError("API_ID / API_HASH не заданы в переменных окружения")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не задан в переменных окружения")
