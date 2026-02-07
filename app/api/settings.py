"""Settings API: GET /api/settings, PATCH /api/settings (pushNotifications, webhookUrl, autoBackup)."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models import Setting, User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["settings"])

SETTING_KEYS = ("pushNotifications", "webhookUrl", "autoBackup")


class SettingsResponse(BaseModel):
    pushNotifications: bool
    webhookUrl: str
    autoBackup: bool


class UpdateSettingsRequest(BaseModel):
    pushNotifications: Optional[bool] = None
    webhookUrl: Optional[str] = None
    autoBackup: Optional[bool] = None


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return True
    return value.strip().lower() in ("true", "1", "yes")


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    """Вернуть настройки из таблицы settings (key-value). Отсутствующие ключи — дефолты."""
    result = await session.execute(select(Setting).where(Setting.key.in_(SETTING_KEYS)))
    rows = result.scalars().all()
    by_key = {r.key: r.value for r in rows}
    return SettingsResponse(
        pushNotifications=_parse_bool(by_key.get("pushNotifications")),
        webhookUrl=by_key.get("webhookUrl") or "",
        autoBackup=_parse_bool(by_key.get("autoBackup")),
    )


@router.patch("/settings", response_model=SettingsResponse)
async def update_settings(
    body: UpdateSettingsRequest,
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    """Обновить переданные настройки и вернуть полный объект."""
    result = await session.execute(select(Setting).where(Setting.key.in_(SETTING_KEYS)))
    rows = result.scalars().all()
    by_key = {r.key: r for r in rows}

    if body.pushNotifications is not None:
        _upsert_setting(session, by_key, "pushNotifications", "true" if body.pushNotifications else "false")
    if body.webhookUrl is not None:
        _upsert_setting(session, by_key, "webhookUrl", body.webhookUrl)
    if body.autoBackup is not None:
        _upsert_setting(session, by_key, "autoBackup", "true" if body.autoBackup else "false")

    await session.commit()

    result2 = await session.execute(select(Setting).where(Setting.key.in_(SETTING_KEYS)))
    rows2 = result2.scalars().all()
    by_key2 = {r.key: r.value for r in rows2}
    return SettingsResponse(
        pushNotifications=_parse_bool(by_key2.get("pushNotifications")),
        webhookUrl=by_key2.get("webhookUrl") or "",
        autoBackup=_parse_bool(by_key2.get("autoBackup")),
    )


def _upsert_setting(
    session: AsyncSession,
    by_key: dict,
    key: str,
    value: str,
) -> None:
    if key in by_key:
        by_key[key].value = value
    else:
        session.add(Setting(key=key, value=value))
