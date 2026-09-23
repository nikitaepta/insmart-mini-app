import os
import uuid
import time
from typing import List

import requests
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


app = FastAPI()


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# INSSMART
# =========================

OFFERS_URL = "https://api.inssmart.ru/v1/product-finance/offers"

# Варианты URL для получения JWT (пробуем по порядку, пока не сработает).
# Если у тебя есть ручной токен из браузера — задай INSSMART_BEARER_TOKEN,
# и эти запросы вообще не выполняются.
TOKEN_URL_CANDIDATES = [
    "https://api.inssmart.ru/v1/account/accounts/token",
    "https://api.inssmart.ru/v1/account/auth/token",
    "https://api.inssmart.ru/v1/auth/login",
    "https://api.inssmart.ru/v1/account/token",
    "https://partners.inssmart.ru/api/v1/auth/token",
    "https://partners.inssmart.ru/api/auth/token",
]


INSSMART_PHONE = os.getenv("INSSMART_PHONE", "").strip()
INSSMART_PASSWORD = os.getenv("INSSMART_PASSWORD", "")

INSSMART_LOCATION = os.getenv(
    "INSSMART_LOCATION",
    "Россия, Москва"
)

INSSMART_DOMAIN = os.getenv(
    "INSSMART_DOMAIN",
    "partners"
)

# Если токен достанешь руками из DevTools браузера — вставь сюда (в .env).
# Валидный JWT обычно вида: eyJhbGciOiJ... .xxxx... .yyyy...
INSSMART_BEARER_TOKEN = os.getenv("INSSMART_BEARER_TOKEN", "").strip()
if INSSMART_BEARER_TOKEN.startswith("Bearer "):
    INSSMART_BEARER_TOKEN = INSSMART_BEARER_TOKEN[7:].strip()


# Текущий токен держим только в памяти Railway
_cached_token = None


# =========================
# ПОЛУЧЕНИЕ TOKEN
# =========================

def extract_token(data):
    """
    Пытается найти JWT в распространённых форматах ответа.
    Сам токен нигде не логируется.
    """

    if isinstance(data, str):
        value = data.strip()

        if value.startswith("Bearer "):
            value = value[7:].strip()

        # JWT обычно состоит из 3 частей
        if value.count(".") == 2:
            return value

        return None

    if isinstance(data, dict):
        possible_keys = [
            "token",
            "accessToken",
            "access_token",
            "jwt",
            "idToken",
            "id_token",
        ]

        for key in possible_keys:
            value = data.get(key)

            if isinstance(value, str):
                value = value.strip()

                if value.startswith("Bearer "):
                    value = value[7:].strip()

                if value.count(".") == 2:
                    return value

        # Рекурсивно ищем внутри вложенных объектов
        for value in data.values():
            found = extract_token(value)

            if found:
                return found

    if isinstance(data, list):
        for value in data:
            found = extract_token(value)

            if found:
                return found

    return None


def _build_auth_payload():
    return {
        "statVisitId": str(uuid.uuid4()),
        "statClientId": str(uuid.uuid4()),
        "statYmClientId": str(int(time.time() * 1000)),
        "location": INSSMART_LOCATION,
        "domain": INSSMART_DOMAIN,
        "phone": INSSMART_PHONE,
        "password": INSSMART_PASSWORD,
    }


def _default_headers():
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://partners.inssmart.ru",
        "Referer": "https://partners.inssmart.ru/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _try_request_token_once(url: str, payload: dict, variant: str):
    """
    variant:
      - "multipart"  →  multipart/form-data (как браузер при загрузке файлов)
      - "form"       →  application/x-www-form-urlencoded (стандартная форма)
      - "json"       →  application/json (современные API)
    """
    headers = _default_headers()
    if variant == "multipart":
        files = {k: (None, str(v)) for k, v in payload.items()}
        return requests.post(url, files=files, headers=headers, timeout=30)
    if variant == "form":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return requests.post(url, data=payload, headers=headers, timeout=30)
    if variant == "json":
        headers["Content-Type"] = "application/json"
        return requests.post(url, json=payload, headers=headers, timeout=30)
    raise ValueError(variant)


def get_inssmart_token():
    global _cached_token

    if _cached_token:
        return _cached_token

    # 1. Ручной токен — самый быстрый путь (без авторизации по паролю)
    if INSSMART_BEARER_TOKEN:
        if INSSMART_BEARER_TOKEN.count(".") == 2:
            print("[inssmart] Использую ручной INSSMART_BEARER_TOKEN из env.")
            _cached_token = INSSMART_BEARER_TOKEN
            return _cached_token
        print(
            "[inssmart] INSSMART_BEARER_TOKEN задан, но не похож на JWT "
            "(3 части через точку). Игнорирую."
        )

    if not INSSMART_PHONE:
        raise RuntimeError(
            "Не задан INSSMART_PHONE. "
            "Либо укажи INSSMART_PHONE + INSSMART_PASSWORD, "
            "либо сразу INSSMART_BEARER_TOKEN."
        )
    if not INSSMART_PASSWORD:
        raise RuntimeError(
            "Не задан INSSMART_PASSWORD. "
            "Либо укажи INSSMART_PHONE + INSSMART_PASSWORD, "
            "либо сразу INSSMART_BEARER_TOKEN."
        )

    payload = _build_auth_payload()
    variants = ["multipart", "form", "json"]
    errors: List[str] = []

    for url in TOKEN_URL_CANDIDATES:
        for variant in variants:
            try:
                resp = _try_request_token_once(url, payload, variant)
            except requests.RequestException as exc:
                errors.append(f"{variant.upper()} {url} → Network {exc.__class__.__name__}")
                continue

            if resp.status_code == 404:
                errors.append(f"{variant.upper()} {url} → 404 NOT FOUND")
                continue

            if not resp.ok:
                snippet = ""
                try:
                    snippet = resp.text[:200]
                except Exception:
                    pass
                errors.append(
                    f"{variant.upper()} {url} → HTTP {resp.status_code} | {snippet!r}"
                )
                continue

            try:
                data = resp.json()
            except ValueError:
                data = resp.text

            token = extract_token(data)
            if token:
                print(f"[inssmart] Успешно получили JWT через {variant.upper()} {url}")
                _cached_token = token
                return _cached_token

            if isinstance(data, dict):
                keys = list(data.keys())
            else:
                keys = [type(data).__name__]
            errors.append(
                f"{variant.upper()} {url} → HTTP 200, но JWT не найден. Поля: {keys}"
            )

    # Ни один из вариантов не сработал — подробный вывод
    print("[inssmart] Все варианты получения токена провалились:")
    for msg in errors:
        print(f"  ❌ {msg}")

    raise RuntimeError(
        "Не удалось получить токен Инсмарта. "
        "Варианты: 1) укажи в env INSSMART_BEARER_TOKEN "
        "(скопируй из DevTools браузера в partners.inssmart.ru). "
        "2) проверь, что INSSMART_PHONE в формате 7900XXXXXXX и пароль верный."
    )


def refresh_inssmart_token():
    global _cached_token

    _cached_token = None

    return get_inssmart_token()


# =========================
# OFFERS
# =========================

def request_offers(token):
    params = {
        "startAt": 0,
        "maxResults": 100,
        "sortNulls": "true",
        "types[]": 3,
        "status": 1,
        "useRetention": "true",
    }

    response = requests.get(
        OFFERS_URL,
        params=params,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
        },
        timeout=30,
    )

    return response


def _normalize_offers_payload(data):
    """
    Инсмарт отдаёт {total, items:[...]}.
    Для совместимости с фронтендом (ожидает offers) и ботом (поддерживает оба)
    возвращаем {total, items, offers:[...]}.
    """
    if isinstance(data, list):
        items = data
        total = len(data)
        payload = {}
    elif isinstance(data, dict):
        items = data.get("items")
        if not isinstance(items, list):
            items = data.get("offers") or []
            if not isinstance(items, list):
                items = []
        total = data.get("total")
        if total is None:
            total = len(items)
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(items)
        payload = {k: v for k, v in data.items() if k not in ("items", "offers", "total")}
    else:
        return {"total": 0, "items": [], "offers": []}

    payload["items"] = items
    payload["offers"] = items
    payload["total"] = total
    return payload


@app.get("/api/offers")
def offers():
    try:
        token = get_inssmart_token()

        response = request_offers(token)

        # Если JWT протух — получаем новый и пробуем ещё раз
        if response.status_code == 401:
            token = refresh_inssmart_token()

            response = request_offers(token)

        if not response.ok:
            raise HTTPException(
                status_code=502,
                detail=f"Inssmart returned HTTP {response.status_code}",
            )

        try:
            raw = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Inssmart returned invalid JSON: {exc}")

        return _normalize_offers_payload(raw)

    except HTTPException:
        raise

    except Exception as error:
        # Не выводим пароль/JWT
        print(f"Inssmart error: {error}")

        raise HTTPException(
            status_code=500,
            detail="Не удалось получить предложения",
        )


# =========================
# HEALTH CHECK
# =========================

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "insmart-api"
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok"
    }