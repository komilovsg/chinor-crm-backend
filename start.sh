#!/bin/sh
# Старт для Railway: миграции + приложение. Ошибки выводятся в лог.
set -e
echo "[start] Running migrations..."
alembic upgrade head || { echo "[start] Alembic failed!"; exit 1; }
echo "[start] Starting app..."
exec python -m app.main
