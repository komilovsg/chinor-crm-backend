"""Точка входа FastAPI. CORS для фронта, префикс /api — в роутерах (B4+)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from sqlalchemy import func, select, text

from app.config import get_cors_origins_list, Settings
from app.db.models import User
from app.db.session import engine, async_session_factory

_settings = Settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _ensure_admin_seed() -> None:
    """Если в БД нет пользователей — создать одного admin из env (B11)."""
    async with async_session_factory() as session:
        result = await session.execute(select(func.count(User.id)))
        count = result.scalar() or 0
        if count > 0:
            return
        # bcrypt accepts max 72 bytes; truncate to avoid ValueError
        raw = _settings.admin_password.encode("utf-8")[:72]
        pwd_for_hash = raw.decode("utf-8", errors="ignore") or _settings.admin_password[:1]
        admin = User(
            email=_settings.admin_email,
            password_hash=_pwd_context.hash(pwd_for_hash),
            role="admin",
            display_name="Admin",
        )
        session.add(admin)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Проверка подключения к БД при старте; сид первого админа при отсутствии пользователей."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await _ensure_admin_seed()
    yield
    await engine.dispose()


app = FastAPI(
    title="CHINOR CRM API",
    description="REST API для фронтенда CHINOR CRM",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: список из env + regex для *.vercel.app (основной и preview деплои)
_cors_origins = get_cors_origins_list(_settings.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/")
async def root():
    """Корень API (здоровье/инфо)."""
    return {"service": "CHINOR CRM API", "docs": "/docs"}


from app.api import auth, dashboard, bookings, guests, broadcasts, settings

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(bookings.router)
app.include_router(guests.router)
app.include_router(broadcasts.router)
app.include_router(settings.router)


def _run_uvicorn() -> None:
    """Точка входа для запуска сервера: python -m app.main. Хост и порт из config (PORT на Railway)."""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=_settings.host,
        port=_settings.port,
        reload=False,
    )


if __name__ == "__main__":
    try:
        _run_uvicorn()
    except Exception as e:
        import sys
        print(f"[app.main] Startup failed: {e}", file=sys.stderr)
        raise
