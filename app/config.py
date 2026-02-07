"""Конфигурация приложения через переменные окружения (pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из env. См. .env.example."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Подключение к БД (для шагов B2+)
    database_url: str = "postgresql+asyncpg://localhost/chinor"

    # Секрет для подписи JWT (для шагов B4+)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"

    # CORS: разрешённые origins через запятую (например http://localhost:5173)
    cors_origins: str = "http://localhost:5173"

    # Хост и порт для uvicorn (Railway передаёт PORT в env; локально — 8000)
    host: str = "0.0.0.0"
    port: int = 8000

    # Сид первого админа (B11): если в БД нет пользователей, создаётся один с этими данными
    admin_email: str = "admin@localhost"
    admin_password: str = "admin"


def get_cors_origins_list(origins: str) -> list[str]:
    """Парсит CORS_ORIGINS в список строк (без пробелов)."""
    return [o.strip() for o in origins.split(",") if o.strip()]
