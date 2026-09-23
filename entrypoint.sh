#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"
HOST="0.0.0.0"

echo "[entrypoint] Запускаю FastAPI (uvicorn) на ${HOST}:${PORT} ..."
uvicorn server:app --host "${HOST}" --port "${PORT}" &
API_PID=$!

echo "[entrypoint] Запускаю Telegram-бот (bot.py) ..."
set +e
python bot.py
BOT_EXIT=$?
set -e

echo "[entrypoint] Бот завершился с кодом ${BOT_EXIT}, останавливаю FastAPI (PID ${API_PID}) ..."
kill "${API_PID}" 2>/dev/null || true
wait "${API_PID}" 2>/dev/null || true

exit "${BOT_EXIT}"
