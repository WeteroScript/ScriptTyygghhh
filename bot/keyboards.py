from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.locales import t

# Telegram не поддерживает цвет для inline-кнопок (только текст) — единственный
# способ визуально выделить их "цветом" — эмодзи-индикаторы перед текстом.


def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])


def lang_kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang:ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang:en")],
    ])


def main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟦 " + t(lang, "menu_accounts"), callback_data="menu:accounts")],
        [InlineKeyboardButton(text="🟩 " + t(lang, "menu_gifts"), callback_data="menu:gifts")],
        [InlineKeyboardButton(text="🟧 " + t(lang, "menu_settings"), callback_data="menu:settings")],
        [InlineKeyboardButton(text="🟪 " + t(lang, "menu_logs"), callback_data="menu:logs")],
        [InlineKeyboardButton(text="🟥 " + t(lang, "menu_admin"), callback_data="menu:admin")],
    ])


def accounts_menu_kb(lang: str, accounts) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🟢 " + t(lang, "add_account"), callback_data="acc:add")],
        [InlineKeyboardButton(text="🔴 " + t(lang, "remove_account"), callback_data="acc:remove_menu")],
    ]
    for acc in accounts:
        rows.append([InlineKeyboardButton(text="🔵 " + acc["phone"], callback_data=f"acc:open:{acc['phone']}")])
    rows.append([InlineKeyboardButton(text="⬅️ " + t(lang, "back"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def accounts_remove_kb(lang: str, accounts) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔴 " + acc["phone"], callback_data=f"acc:del:{acc['phone']}")]
            for acc in accounts]
    rows.append([InlineKeyboardButton(text="⬅️ " + t(lang, "back"), callback_data="menu:accounts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_control_kb(lang: str, phone: str, running: bool) -> InlineKeyboardMarkup:
    start_stop = (
        InlineKeyboardButton(text="🔴 " + t(lang, "stop_sniper"), callback_data=f"acc:stop:{phone}")
        if running else
        InlineKeyboardButton(text="🟢 " + t(lang, "start_sniper"), callback_data=f"acc:start:{phone}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [start_stop],
        [InlineKeyboardButton(text="⬅️ " + t(lang, "back"), callback_data="menu:accounts")],
    ])


def gifts_kb(gifts, ignored: set, page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    """gifts: список dict {id, name, price} — уже нарезанный под текущую страницу.
    ✅ = бот отслеживает и может купить этот подарок, ❌ = игнорирует
    (не просматривает лоты и не покупает)."""
    rows = []
    for g in gifts:
        mark = "❌" if g["id"] in ignored else "✅"
        label = f"{g['name']} — {g['price']}⭐️ {mark}"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"gift:toggle:{page}:{g['id']}"
        )])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"gifts:page:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"gifts:page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton(text="⬅️", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 " + t(lang, "change_lang"), callback_data="settings:lang")],
        [InlineKeyboardButton(text="💰 " + t(lang, "change_price"), callback_data="settings:price")],
        [InlineKeyboardButton(text="⬅️ " + t(lang, "back"), callback_data="menu:main")],
    ])


def logs_kb(lang: str, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = ("✅ " if enabled else "❌ ") + t(lang, "logs_toggle")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_label, callback_data="logs:toggle")],
        [InlineKeyboardButton(text="⬅️ " + t(lang, "back"), callback_data="menu:main")],
    ])
