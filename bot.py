
import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEB_APP_URL = os.getenv(
    "WEB_APP_URL",
    "https://nikitaepta.github.io/insmart-mini-app/?v=2",
).strip()
BACKEND_API_URL = os.getenv(
    "BACKEND_API_URL",
    "http://localhost:8000",
).strip().rstrip("/")


OFFERS_PER_PAGE = 8


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Создайте файл .env (см. .env.example) "
        "или установите переменную окружения BOT_TOKEN."
    )


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================
# Кэш офферов
# =========================

_offers_cache: Optional[List[Dict[str, Any]]] = None
_offers_cache_fetched_at: float = 0.0
_OFFERS_CACHE_TTL_SECONDS = 5 * 60


# =========================
# Утилиты форматирования
# =========================

def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(value))
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _format_amount(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number:,.0f}".replace(",", " ")


def _format_number(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number.is_integer():
        return str(int(number))
    return str(round(number, 2))


def _extract_url(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    markdown_match = re.search(r"\]\((https?://[^)]+)\)", text)
    if markdown_match:
        return markdown_match.group(1)
    url_match = re.search(r"https?://[^\s<>'\"()]+", text)
    if url_match:
        return url_match.group(0)
    return ""


# =========================
# Нормализация оффера из API
# =========================

def _extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("offers"), list):
            return payload["offers"]
        if isinstance(payload.get("items"), list):
            return payload["items"]
        if isinstance(payload.get("data"), (dict, list)):
            if isinstance(payload["data"], list):
                return payload["data"]
            return _extract_items(payload["data"])
    if isinstance(payload, list):
        return payload
    return []


def _normalize_offer(raw: Dict[str, Any]) -> Dict[str, Any]:
    company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
    product = raw.get("productInfo") if isinstance(raw.get("productInfo"), dict) else {}

    name = (
        raw.get("name")
        or company.get("name")
        or product.get("name")
        or "Предложение"
    )

    def pick(*keys: str) -> Any:
        for k in keys:
            if k in raw and raw[k] not in (None, ""):
                return raw[k]
            if k in product and product[k] not in (None, ""):
                return product[k]
        return None

    amount_from = pick("amountFrom", "amount_from", "minAmount")
    amount_to = pick("amountTo", "amount_to", "maxAmount")
    term_from = pick(
        "termFrom", "term_from", "creditTermFrom", "minTerm"
    )
    term_to = pick(
        "termTo", "term_to", "creditTermTo", "maxTerm"
    )
    rate = pick(
        "interestRate", "rate", "interest_rate", "ratePerDay"
    )

    logo = raw.get("logo") or company.get("logo") or product.get("logo") or ""
    link = raw.get("link") or raw.get("url") or product.get("link") or ""
    description = (
        raw.get("description")
        or raw.get("conditions")
        or product.get("description")
        or product.get("conditions")
        or ""
    )

    return {
        "name": _clean_text(name) or "Предложение",
        "amount_from": amount_from,
        "amount_to": amount_to,
        "term_from": term_from,
        "term_to": term_to,
        "rate": rate,
        "logo": _clean_text(logo),
        "link": _extract_url(link),
        "description": _clean_text(description),
    }


# =========================
# Загрузка офферов из бэкенда
# =========================

async def fetch_offers(force_refresh: bool = False) -> List[Dict[str, Any]]:
    global _offers_cache, _offers_cache_fetched_at

    import time

    now = time.time()
    if (
        not force_refresh
        and _offers_cache is not None
        and now - _offers_cache_fetched_at < _OFFERS_CACHE_TTL_SECONDS
    ):
        return _offers_cache

    url = f"{BACKEND_API_URL}/api/offers"
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                payload = await resp.json(content_type=None)
    except Exception as exc:
        print(f"[bot] Ошибка загрузки офферов с {url}: {exc}")
        return _get_demo_offers()

    raw_items = _extract_items(payload)
    if not raw_items:
        print("[bot] API вернул пустой список офферов, используем демо-данные")
        return _get_demo_offers()

    normalized = [
        _normalize_offer(item)
        for item in raw_items
        if isinstance(item, dict)
    ]

    _offers_cache = normalized
    _offers_cache_fetched_at = now
    return normalized


def _get_demo_offers() -> List[Dict[str, Any]]:
    return [
        {
            "name": "Предложение №1",
            "amount_from": 1000,
            "amount_to": 30000,
            "term_from": 1,
            "term_to": 30,
            "rate": "уточняется",
            "logo": "",
            "link": "",
            "description": (
                "Демо-вариант. Реальные предложения будут доступны "
                "после запуска FastAPI-сервера и настройки INSSMART_*."
            ),
        },
        {
            "name": "Предложение №2",
            "amount_from": 5000,
            "amount_to": 50000,
            "term_from": 1,
            "term_to": 30,
            "rate": "уточняется",
            "logo": "",
            "link": "",
            "description": "Демо-вариант.",
        },
        {
            "name": "Предложение №3",
            "amount_from": 10000,
            "amount_to": 100000,
            "term_from": 1,
            "term_to": 60,
            "rate": "уточняется",
            "logo": "",
            "link": "",
            "description": "Демо-вариант.",
        },
    ]


# =========================
# Главное меню
# =========================

def main_menu() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть приложение",
                    web_app=WebAppInfo(url=WEB_APP_URL),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏦 Предложения МФО",
                    callback_data="offers:page:0",
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ О сервисе",
                    callback_data="about",
                )
            ],
        ]
    )
    return keyboard


# =========================
# Команда /start
# =========================

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Здесь вы можете ознакомиться с предложениями "
        "МФО от Инсмарта.\n\n"
        "📱 Нажмите «Открыть приложение», "
        "чтобы посмотреть предложения внутри Telegram.\n"
        "🏦 Или выберите раздел «Предложения МФО» ниже.",
        reply_markup=main_menu(),
    )


# =========================
# Предложения МФО — список с пагинацией
# =========================

def _offers_pagination_markup(
    offers: List[Dict[str, Any]],
    page: int,
) -> Tuple[InlineKeyboardMarkup, int, int]:
    total = len(offers)
    total_pages = max(1, (total + OFFERS_PER_PAGE - 1) // OFFERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * OFFERS_PER_PAGE
    end = min(start + OFFERS_PER_PAGE, total)
    page_offers = offers[start:end]

    rows: List[List[InlineKeyboardButton]] = []
    for idx, offer in enumerate(page_offers, start=start):
        amount_from = _format_amount(offer.get("amount_from"))
        amount_to = _format_amount(offer.get("amount_to"))
        short = offer.get("name") or f"Предложение {idx + 1}"
        if len(short) > 28:
            short = short[:27] + "…"
        label = f"💸 {short} · {amount_from}–{amount_to} ₽"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"offer:{idx}",
                )
            ]
        )

    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"offers:page:{page - 1}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="offers:noop",
        )
    )
    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Далее ▶️",
                callback_data=f"offers:page:{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Обновить список",
                callback_data="offers:refresh",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔙 В главное меню",
                callback_data="back",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows), total, total_pages


@dp.callback_query(lambda c: c.data and c.data.startswith("offers:"))
async def offers_handler(callback: types.CallbackQuery):
    assert callback.data is not None
    parts = callback.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else "page"

    force = False
    page = 0

    if action == "page" and len(parts) == 3:
        try:
            page = max(0, int(parts[2]))
        except ValueError:
            page = 0
    elif action == "refresh":
        force = True
        page = 0
    elif action == "noop":
        await callback.answer(cache_time=1)
        return

    await callback.answer("Загружаем предложения…")

    offers = await fetch_offers(force_refresh=force)
    if force:
        try:
            await callback.answer("Список обновлён ✅")
        except Exception:
            pass

    keyboard, total, _ = _offers_pagination_markup(offers, page)
    from_mode = " (реальные данные)" if not (
        len(offers) == 3 and offers and offers[0].get("name", "").startswith("Предложение №1")
    ) else " (демо — API недоступен)"

    await callback.message.edit_text(
        "🏦 <b>Предложения МФО</b>\n\n"
        f"Всего доступно: <b>{total}</b>\n"
        f"<i>{from_mode}</i>\n\n"
        "Выберите предложение для подробностей:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# =========================
# Детальный просмотр оффера
# =========================

def _offer_details_markup(
    offer: Dict[str, Any],
    back_callback: str = "offers:page:0",
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    link = offer.get("link") or ""
    if link:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔗 Перейти к оформлению",
                    url=link,
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔗 Ссылка пока недоступна",
                    callback_data="offer:no_link",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔙 К списку предложений",
                callback_data=back_callback,
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🏠 В главное меню",
                callback_data="back",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(lambda c: c.data and c.data.startswith("offer:"))
async def offer_details_handler(callback: types.CallbackQuery):
    assert callback.data is not None
    payload = callback.data[len("offer:"):]

    if payload == "no_link":
        await callback.answer(
            "Ссылка на это предложение временно недоступна.",
            show_alert=True,
        )
        return

    try:
        idx = int(payload)
    except ValueError:
        await callback.answer("Некорректный выбор", show_alert=True)
        return

    offers = await fetch_offers()
    if idx < 0 or idx >= len(offers):
        await callback.answer("Предложение устарело, обновите список", show_alert=True)
        return

    offer = offers[idx]
    page = idx // OFFERS_PER_PAGE

    amount_from = _format_amount(offer.get("amount_from"))
    amount_to = _format_amount(offer.get("amount_to"))
    term_from = _format_number(offer.get("term_from"))
    term_to = _format_number(offer.get("term_to"))
    rate_raw = offer.get("rate")
    if rate_raw is None or rate_raw == "":
        rate_text = "уточняется"
    else:
        try:
            num = float(rate_raw)
            rate_text = f"{num:.2f}"
            if num.is_integer():
                rate_text = str(int(num))
        except (TypeError, ValueError):
            rate_text = _clean_text(rate_raw) or "уточняется"

    name = offer.get("name") or f"Предложение {idx + 1}"
    description = offer.get("description") or ""

    text_parts = [
        f"💼 <b>{name}</b>\n",
        "",
        f"💸 Сумма: <b>{amount_from} – {amount_to} ₽</b>",
        f"📅 Срок: <b>{term_from} – {term_to} дней</b>",
        f"📈 Ставка: <b>{rate_text}</b>",
    ]
    if description:
        text_parts.append("")
        if len(description) > 400:
            description = description[:397] + "…"
        text_parts.append(f"ℹ️ {description}")

    back_cb = f"offers:page:{page}"
    keyboard = _offer_details_markup(offer, back_callback=back_cb)

    await callback.message.edit_text(
        "\n".join(text_parts),
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


# =========================
# О сервисе
# =========================

@dp.callback_query(lambda callback: callback.data == "about")
async def about_handler(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 В главное меню",
                    callback_data="back",
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "ℹ️ <b>О сервисе</b>\n\n"
        "Здесь пользователи могут ознакомиться "
        "с предложениями МФО от Инсмарта.\n\n"
        "Реальные предложения подгружаются с API-партнёра "
        "через наш FastAPI-сервер. Если API недоступен, "
        "показываются демо-варианты.\n\n"
        "Выберите раздел в главном меню.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


# =========================
# Назад в главное меню
# =========================

@dp.callback_query(lambda callback: callback.data == "back")
async def back_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👋 <b>Главное меню</b>\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# =========================
# Запуск бота
# =========================

async def main():
    print("Бот запущен!")
    print(f"  BOT_TOKEN: {'успешно загружен' if BOT_TOKEN else 'НЕ ЗАДАН'}")
    print(f"  WEB_APP_URL: {WEB_APP_URL}")
    print(f"  BACKEND_API_URL: {BACKEND_API_URL}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
