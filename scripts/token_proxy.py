
"""
Локальный token-proxy для обхода WAF Инсмарта (503 Service Unavailable).

Запускается ТОЛЬКО на машине, IP которой НЕ заблокирован Inssmart:
   — твой домашний ПК под Windows (1 команда ниже)
   — или любой VPS с РФ-IP

Команда запуска (PowerShell, из корня проекта telegram_mfo_bot):
    .venv\Scripts\activate
    python -m uvicorn scripts.token_proxy:app --host 0.0.0.0 --port 8787

Затем на своём роутере пробрось порт 8787 → этот ПК.
Или используй ngrok / cloudflared tunnel (проброс localhost в интернет без port-forwarding):
    ngrok http 8787  → даст https://xxxx.ngrok-free.app

В Railway Variables добавь:
    INSSMART_TOKEN_EXTERNAL_URL=https://xxxx.ngrok-free.app/token

Если хочешь защитить endpoint паролем (рекомендуется для публичного URL):
    TOKEN_PROXY_API_KEY=мой_секретный_ключ_который_знаю_только_я
И в Railway:
    INSSMART_TOKEN_EXTERNAL_URL=https://xxxx.ngrok-free.app/token?key=мой_секретный_ключ_который_знаю_только_я
"""

import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Загружаем .env из корня проекта (там же INSSMART_PHONE/PASSWORD и т.п.)
ROOT = Path(__file__).resolve().parent.parent
if (ROOT / ".env").exists():
    load_dotenv(ROOT / ".env")


# ==== Переиспользуем логику получения токена из server.py ====
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import get_inssmart_token, refresh_inssmart_token  # noqa: E402


TOKEN_PROXY_PORT = int(os.getenv("TOKEN_PROXY_PORT", "8787"))
TOKEN_PROXY_API_KEY = os.getenv("TOKEN_PROXY_API_KEY", "").strip()
TOKEN_CACHE_SECONDS = int(os.getenv("TOKEN_CACHE_SECONDS", "3000"))  # ~50 минут (JWT обычно живёт 1 час)


app = FastAPI(title="Inssmart Token Proxy", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


_cached: dict = {"token": None, "expire_at": 0.0}


def _is_authorized(key: str | None) -> bool:
    if not TOKEN_PROXY_API_KEY:
        return True
    return bool(key) and key == TOKEN_PROXY_API_KEY


@app.get("/health")
def health():
    return {
        "status": "ok",
        "has_token": _cached["token"] is not None,
        "token_ttl_seconds": max(0, int(_cached["expire_at"] - time.time())),
        "has_api_key": bool(TOKEN_PROXY_API_KEY),
    }


@app.get("/token")
def get_token(key: str | None = Query(default=None), refresh: bool = False):
    if not _is_authorized(key):
        raise HTTPException(status_code=401, detail="Unauthorized: set ?key=... or remove TOKEN_PROXY_API_KEY")

    now = time.time()
    if not refresh and _cached["token"] and now < _cached["expire_at"]:
        return {"token": _cached["token"], "cached": True, "ttl": int(_cached["expire_at"] - now)}

    try:
        if refresh:
            token = refresh_inssmart_token()
        else:
            token = get_inssmart_token()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    _cached["token"] = token
    _cached["expire_at"] = now + TOKEN_CACHE_SECONDS
    return {"token": token, "cached": False, "ttl": TOKEN_CACHE_SECONDS}


if __name__ == "__main__":
    import uvicorn
    print(f"[token_proxy] starting on 0.0.0.0:{TOKEN_PROXY_PORT} …")
    if TOKEN_PROXY_API_KEY:
        print(f"[token_proxy] auth enabled (API_KEY len={len(TOKEN_PROXY_API_KEY)})")
    else:
        print("[token_proxy] auth DISABLED (anyone can call /token). Set TOKEN_PROXY_API_KEY env to protect.")
    uvicorn.run(app, host="0.0.0.0", port=TOKEN_PROXY_PORT)
