import os
import re
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

# ========== РУЧНОЙ ПЕРЕОПРЕДЕЛЁННЫЙ URL АВТОРИЗАЦИИ ==========
# Самый важный параметр. Если ты знаешь ТОЧНЫЙ endpoint логина — вставь его сюда,
# и он будет испробован ПЕРВЫМ (до всех догадок).
# Как узнать: зайди в partners.inssmart.ru, F12 → Network → введи логин/пароль,
# найди первый XHR-запрос со статусом 200 (Method: POST). Скопируй его URL.
INSSMART_LOGIN_URL = os.getenv("INSSMART_LOGIN_URL", "").strip()

# Варианты URL для получения JWT (пробуем по порядку, пока не сработает).
# Если INSSMART_LOGIN_URL задан — он встаёт на первое место.
_BASE_TOKEN_URLS = [
    # Оригинальный URL из рабочего коммита 85a7d9b («под браузер»)
    "https://api.inssmart.ru/v1/account/accounts/token",
    "https://api.inssmart.ru/v1/account/accounts/login",
    "https://api.inssmart.ru/v1/account/accounts/signin",
    "https://api.inssmart.ru/v1/account/auth/token",
    "https://api.inssmart.ru/v1/account/auth/login",
    "https://api.inssmart.ru/v1/account/token",
    "https://api.inssmart.ru/v1/account/login",
    "https://api.inssmart.ru/v1/auth/token",
    "https://api.inssmart.ru/v1/auth/login",
    "https://api.inssmart.ru/v1/auth/signin",
    "https://api.inssmart.ru/v1/user/token",
    "https://api.inssmart.ru/v1/user/login",
    "https://api.inssmart.ru/v1/login",
    "https://api.inssmart.ru/v1/token",
    # Партнёрский домен (часто у них API там)
    "https://partners.inssmart.ru/api/token",
    "https://partners.inssmart.ru/api/login",
    "https://partners.inssmart.ru/api/auth/token",
    "https://partners.inssmart.ru/api/auth/login",
    "https://partners.inssmart.ru/api/v1/token",
    "https://partners.inssmart.ru/api/v1/login",
    "https://partners.inssmart.ru/api/v1/account/token",
    "https://partners.inssmart.ru/api/v1/account/login",
    "https://partners.inssmart.ru/api/v1/auth/accounts/token",
]
TOKEN_URL_CANDIDATES: List[str] = []
if INSSMART_LOGIN_URL:
    TOKEN_URL_CANDIDATES.append(INSSMART_LOGIN_URL)
TOKEN_URL_CANDIDATES.extend(_BASE_TOKEN_URLS)


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

# =====================================================================
# Прокси / обход WAF Инсмарта (503 Service Temporarily Unavailable)
# =====================================================================
# Инсмарт активно банит облачные IP (Railway / AWS / GCP).
# Решение 1: residential/static proxy РФ (покупается за 50-300₽/мес).
#   Формат: http://user:pass@host:port   или   socks5h://user:pass@host:port
#   Пример: INSSMART_PROXY_URL=http://login:password@1.2.3.4:5678
INSSMART_PROXY_URL = os.getenv("INSSMART_PROXY_URL", "").strip() or \
                     os.getenv("HTTP_PROXY", "").strip() or \
                     os.getenv("HTTPS_PROXY", "").strip()

# Решение 2: внешний token-прокси (самый надёжный и бесплатный).
# Запускаешь scripts/token_proxy.py НА ДОМАШНЕМ КОМПЬЮТЕРЕ или VPS с РФ-IP.
# Он по твоему телефону/паролю получает JWT у Инсарта (с НЕзабаненного IP),
# а Railway сервер приходит за JWT к ТЕБЕ, а не к Inssmart напрямую.
# Пример: http://<твой-домашний-айпи>:8787/token
INSSMART_TOKEN_EXTERNAL_URL = os.getenv("INSSMART_TOKEN_EXTERNAL_URL", "").strip()


def _inssmart_requests_proxies() -> dict | None:
    """Готовит proxies dict для requests."""
    if not INSSMART_PROXY_URL:
        return None
    return {"http": INSSMART_PROXY_URL, "https": INSSMART_PROXY_URL}


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


def _normalize_phone_variants() -> List[str]:
    """
    Возвращает 4 варианта телефона — API бывает привередлив к формату.
    Пример входа: "89153890989" или "+79153890989" или "79153890989"
    """
    digits = re.sub(r"\D", "", INSSMART_PHONE or "")
    if not digits:
        return []
    if len(digits) == 11 and digits[0] in ("7", "8"):
        rest = digits[1:]
        return [
            "7" + rest,       # 79153890989
            "8" + rest,       # 89153890989
            "+7" + rest,      # +79153890989
            rest,             # 9153890989
        ]
    if len(digits) == 10:
        return [
            "7" + digits,
            "8" + digits,
            "+7" + digits,
            digits,
        ]
    # Неожиданная длина — верни как есть + ещё 3 самых распространённых
    out = [digits]
    if not digits.startswith("7"):
        out.append("7" + digits)
    if not digits.startswith("8"):
        out.append("8" + digits)
    if not digits.startswith("+"):
        out.append("+" + digits)
    return out


def _build_all_auth_payload_variants() -> List[dict]:
    """
    Возвращает все комбинации формата телефона × имя поля авторизации.
    Порядок: сначала phone (как было в рабочем коммите), потом username, потом login.
    """
    payloads: List[dict] = []
    base = {
        "statVisitId": str(uuid.uuid4()),
        "statClientId": str(uuid.uuid4()),
        "statYmClientId": str(int(time.time() * 1000)),
        "location": INSSMART_LOCATION,
        "domain": INSSMART_DOMAIN,
    }
    phone_variants = _normalize_phone_variants() or [INSSMART_PHONE]
    user_key_candidates = ["phone", "username", "login"]

    for phone in phone_variants:
        for key in user_key_candidates:
            p = dict(base)
            p[key] = phone
            p["password"] = INSSMART_PASSWORD
            payloads.append(p)
    return payloads


def _default_headers(target_url: str) -> dict:
    """
    Подробные браузерные заголовки. Origin/Referer подстраиваются под partners/inssmart.
    Sec-Fetch/Sec-CH-UA очень сильно влияют на бэкенд WAF (Cloudflare/Akamai),
    который может отдавать 404/403 облачным IP.
    """
    is_partners = "partners." in target_url
    origin = "https://partners.inssmart.ru" if is_partners else "https://api.inssmart.ru"
    referer = origin + "/"
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": origin,
        "Referer": referer,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "Sec-CH-UA": (
            '"Chromium";v="134", "Google Chrome";v="134", '
            '"Not-A.Brand";v="24"'
        ),
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site" if is_partners else "same-origin",
        "Upgrade-Insecure-Requests": "1",
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
    proxies = _inssmart_requests_proxies()
    headers = _default_headers(url)
    if variant == "multipart":
        files = {k: (None, str(v)) for k, v in payload.items()}
        # Для multipart Content-Type задаёт сама requests (с boundary)
        return requests.post(url, files=files, headers=headers, proxies=proxies, timeout=30)
    if variant == "form":
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        return requests.post(url, data=payload, headers=headers, proxies=proxies, timeout=30)
    if variant == "json":
        headers["Content-Type"] = "application/json;charset=UTF-8"
        return requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=30)
    raise ValueError(variant)


def get_inssmart_token():
    global _cached_token

    if _cached_token:
        return _cached_token

    # 0. Внешний token-proxy (самый надёжный обход WAF Инсмарта).
    #    Берём JWT напрямую у твоего домашнего прокси (scripts/token_proxy.py)
    if INSSMART_TOKEN_EXTERNAL_URL:
        try:
            resp = requests.get(
                INSSMART_TOKEN_EXTERNAL_URL,
                proxies=_inssmart_requests_proxies(),
                timeout=30,
            )
            if not resp.ok:
                print(
                    f"[inssmart] Внешний token-proxy {INSSMART_TOKEN_EXTERNAL_URL!r} "
                    f"вернул HTTP {resp.status_code}. Ответ: {resp.text[:200]!r}"
                )
            else:
                try:
                    data = resp.json()
                except ValueError:
                    data = resp.text
                token = extract_token(data)
                if isinstance(data, dict) and isinstance(data.get("token"), str):
                    if not token:
                        token = data["token"].strip()
                if token:
                    print(
                        f"[inssmart] ✅ Использую JWT из внешнего token-proxy "
                        f"{INSSMART_TOKEN_EXTERNAL_URL!r}."
                    )
                    _cached_token = token
                    return _cached_token
                print(
                    f"[inssmart] Внешний token-proxy вернул 200, но JWT не найден. "
                    f"Ответ keys: {list(data) if isinstance(data, dict) else type(data).__name__}"
                )
        except requests.RequestException as exc:
            print(
                f"[inssmart] Внешний token-proxy недоступен "
                f"({exc.__class__.__name__}). Падаю назад на локальную авторизацию."
            )

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
            "либо сразу INSSMART_BEARER_TOKEN, либо INSSMART_TOKEN_EXTERNAL_URL."
        )
    if not INSSMART_PASSWORD:
        raise RuntimeError(
            "Не задан INSSMART_PASSWORD. "
            "Либо укажи INSSMART_PHONE + INSSMART_PASSWORD, "
            "либо сразу INSSMART_BEARER_TOKEN, либо INSSMART_TOKEN_EXTERNAL_URL."
        )

    all_payloads = _build_all_auth_payload_variants()
    content_variants = ["multipart", "form", "json"]
    errors: List[str] = []
    total_tries = 0
    start = time.time()
    MAX_SECONDS = 60  # суммарно не больше минуты на все попытки
    MAX_ERRORS_LOGGED = 80

    print(
        f"[inssmart] Перебираем варианты авторизации по логину/паролю: "
        f"{len(TOKEN_URL_CANDIDATES)} URL × {len(all_payloads)} payload-вариантов "
        f"× {len(content_variants)} content-type = "
        f"{len(TOKEN_URL_CANDIDATES) * len(all_payloads) * len(content_variants)} попыток"
    )

    for url in TOKEN_URL_CANDIDATES:
        for payload in all_payloads:
            # Не логируем пароль — логируем только поле с телефоном и его значением
            user_ident = "?"
            for k in ("phone", "username", "login"):
                if k in payload:
                    user_ident = f"{k}={payload[k]!r}"
                    break
            for variant in content_variants:
                total_tries += 1
                if time.time() - start > MAX_SECONDS:
                    errors.append(f"[TIMEOUT] Превышен лимит {MAX_SECONDS}с")
                    break
                try:
                    resp = _try_request_token_once(url, payload, variant)
                except requests.RequestException as exc:
                    errors.append(
                        f"#{total_tries} {variant.upper()} {url} {user_ident} "
                        f"→ Network {exc.__class__.__name__}"
                    )
                    continue

                if resp.status_code == 404:
                    continue  # 404 на 90% URL — не загромождаем логи.
                if resp.status_code == 401 or resp.status_code == 403:
                    if len(errors) < MAX_ERRORS_LOGGED:
                        errors.append(
                            f"#{total_tries} {variant.upper()} {url} {user_ident} "
                            f"→ HTTP {resp.status_code}"
                        )
                    continue
                if not resp.ok:
                    snippet = ""
                    try:
                        snippet = resp.text[:120]
                    except Exception:
                        pass
                    if len(errors) < MAX_ERRORS_LOGGED:
                        errors.append(
                            f"#{total_tries} {variant.upper()} {url} {user_ident} "
                            f"→ HTTP {resp.status_code} | {snippet!r}"
                        )
                    continue

                try:
                    data = resp.json()
                except ValueError:
                    data = resp.text

                token = extract_token(data)
                if token:
                    elapsed = time.time() - start
                    print(
                        f"[inssmart] ✅ Успешно получили JWT "
                        f"(попытка #{total_tries}, {elapsed:.1f}с): "
                        f"{variant.upper()} {url}  ({user_ident})"
                    )
                    _cached_token = token
                    return _cached_token

                if isinstance(data, dict):
                    keys = list(data.keys())
                else:
                    keys = [type(data).__name__]
                if len(errors) < MAX_ERRORS_LOGGED:
                    errors.append(
                        f"#{total_tries} {variant.upper()} {url} {user_ident} "
                        f"→ HTTP 200, но JWT не найден. Поля: {keys}"
                    )
            if time.time() - start > MAX_SECONDS:
                break
        if time.time() - start > MAX_SECONDS:
            break

    # Ни один из вариантов не сработал — подробный вывод
    elapsed = time.time() - start
    print(
        f"[inssmart] ❌ Все варианты получения токена провалились "
        f"(попыток {total_tries}, {elapsed:.1f}с)."
    )
    if INSSMART_LOGIN_URL:
        print(f"[inssmart] Задан INSSMART_LOGIN_URL={INSSMART_LOGIN_URL!r} — он тоже не сработал.")
    else:
        print(
            "[inssmart] Совет: укажи env INSSMART_LOGIN_URL — "
            "скопируй точный endpoint из DevTools браузера (Network → клик по login-запросу → Request URL)."
        )
    for msg in errors:
        print(f"  ❌ {msg}")
    if len(errors) >= MAX_ERRORS_LOGGED:
        print(f"  … и ещё {total_tries - len(errors)} ошибок (обрезано для читаемости)")

    raise RuntimeError(
        "Не удалось получить токен Инсмарта по логину/паролю. "
        "Что сделать: 1) зайди в браузере на partners.inssmart.ru, "
        "F12 → Network → введи логин/пароль → найди login-запрос "
        "(Method POST, 200/401). Скопируй его Request URL и вставь в "
        "Railway Variables: INSSMART_LOGIN_URL=https://... ."
        " 2) Если это не помогло — скопируй из DevTools «Copy » «Copy as cURL» "
        "этого login-запроса и пришли мне его — я добавлю недостающие "
        "headers/cookie/body-поля. 3) Временный вариант: INSSMART_BEARER_TOKEN "
        "(ставь на час, пока не настроим)."
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

    h = _default_headers(OFFERS_URL)
    h["Authorization"] = f"Bearer {token}"

    response = requests.get(
        OFFERS_URL,
        params=params,
        headers=h,
        proxies=_inssmart_requests_proxies(),
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