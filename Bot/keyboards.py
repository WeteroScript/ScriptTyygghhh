from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.locales import t


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
        [InlineKeyboardButton(text=t(lang, "menu_accounts"), callback_data="menu:accounts")],
        [InlineKeyboardButton(text=t(lang, "menu_gifts"), callback_data="menu:gifts")],
        [InlineKeyboardButton(text=t(lang, "menu_settings"), callback_data="menu:settings")],
        [InlineKeyboardButton(text=t(lang, "menu_admin"), callback_data="menu:admin")],
    ])


def accounts_menu_kb(lang: str, accounts) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(lang, "add_account"), callback_data="acc:add")],
        [InlineKeyboardButton(text=t(lang, "remove_account"), callback_data="acc:remove_menu")],
    ]
    for acc in accounts:
        rows.append([InlineKeyboardButton(text=acc["phone"], callback_data=f"acc:open:{acc['phone']}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def accounts_remove_kb(lang: str, accounts) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=acc["phone"], callback_data=f"acc:del:{acc['phone']}")]
            for acc in accounts]
    rows.append([InlineKeyboardButton(text=t(lang, "back"), callback_data="menu:accounts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_control_kb(lang: str, phone: str, running: bool) -> InlineKeyboardMarkup:
    start_stop = (
        InlineKeyboardButton(text=t(lang, "stop_sniper"), callback_data=f"acc:stop:{phone}")
        if running else
        InlineKeyboardButton(text=t(lang, "start_sniper"), callback_data=f"acc:start:{phone}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [start_stop],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="menu:accounts")],
    ])


def gifts_kb(gifts, ignored: set) -> InlineKeyboardMarkup:
    """gifts: список dict {id, name, price} отсортированный по возрастанию цены."""
    rows = []
    for g in gifts:
        color = "🔴" if g["id"] in ignored else "🟢"
        label = f"{color} {g['name']} — {g['price']}⭐️"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"gift:toggle:{g['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "change_lang"), callback_data="settings:lang")],
        [InlineKeyboardButton(text=t(lang, "back"), callback_data="menu:main")],
    ])
