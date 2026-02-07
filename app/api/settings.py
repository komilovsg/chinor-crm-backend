"""Settings API: GET /api/settings, PATCH /api/settings (pushNotifications, webhookUrl, autoBackup, сегментация)."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.models import Guest, Setting, User
from app.db.session import get_session
from app.services.segmentation import calc_segment

router = APIRouter(prefix="/api", tags=["settings"])

SETTING_KEYS = (
    "pushNotifications",
    "webhookUrl",
    "autoBackup",
    "segment_regular_threshold",
    "segment_vip_threshold",
)

DEFAULT_REGULAR = 5
DEFAULT_VIP = 10


class SettingsResponse(BaseModel):
    pushNotifications: bool
    webhookUrl: str
    autoBackup: bool
    segment_regular_threshold: int
    segment_vip_threshold: int


class UpdateSettingsRequest(BaseModel):
    pushNotifications: Optional[bool] = None
    webhookUrl: Optional[str] = None
    autoBackup: Optional[bool] = None
    segment_regular_threshold: Optional[int] = None
    segment_vip_threshold: Optional[int] = None


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return True
    return value.strip().lower() in ("true", "1", "yes")


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        v = int(value.strip())
        return max(0, v)
    except ValueError:
        return default


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    """Вернуть настройки из таблицы settings (key-value). Отсутствующие ключи — дефолты."""
    result = await session.execute(select(Setting).where(Setting.key.in_(SETTING_KEYS)))
    rows = result.scalars().all()
    by_key = {r.key: r.value for r in rows}
    reg = _parse_int(by_key.get("segment_regular_threshold"), DEFAULT_REGULAR)
    vip = _parse_int(by_key.get("segment_vip_threshold"), DEFAULT_VIP)
    if vip <= reg:
        vip = reg + 1
    return SettingsResponse(
        pushNotifications=_parse_bool(by_key.get("pushNotifications")),
        webhookUrl=by_key.get("webhookUrl") or "",
        autoBackup=_parse_bool(by_key.get("autoBackup")),
        segment_regular_threshold=reg,
        segment_vip_threshold=vip,
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
    if body.segment_regular_threshold is not None:
        v = max(0, body.segment_regular_threshold)
        _upsert_setting(session, by_key, "segment_regular_threshold", str(v))
    if body.segment_vip_threshold is not None:
        v = max(0, body.segment_vip_threshold)
        _upsert_setting(session, by_key, "segment_vip_threshold", str(v))

    await session.commit()

    result2 = await session.execute(select(Setting).where(Setting.key.in_(SETTING_KEYS)))
    rows2 = result2.scalars().all()
    by_key2 = {r.key: r.value for r in rows2}
    reg = _parse_int(by_key2.get("segment_regular_threshold"), DEFAULT_REGULAR)
    vip = _parse_int(by_key2.get("segment_vip_threshold"), DEFAULT_VIP)
    if vip <= reg:
        vip = reg + 1
    return SettingsResponse(
        pushNotifications=_parse_bool(by_key2.get("pushNotifications")),
        webhookUrl=by_key2.get("webhookUrl") or "",
        autoBackup=_parse_bool(by_key2.get("autoBackup")),
        segment_regular_threshold=reg,
        segment_vip_threshold=vip,
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


async def _get_segment_thresholds(session: AsyncSession) -> tuple[int, int]:
    """Получить пороги сегментации из settings."""
    result = await session.execute(
        select(Setting).where(
            Setting.key.in_(("segment_regular_threshold", "segment_vip_threshold"))
        )
    )
    rows = result.scalars().all()
    by_key = {r.key: r.value for r in rows}
    reg = DEFAULT_REGULAR
    vip = DEFAULT_VIP
    if by_key.get("segment_regular_threshold"):
        try:
            reg = max(0, int(by_key["segment_regular_threshold"].strip()))
        except (ValueError, AttributeError):
            pass
    if by_key.get("segment_vip_threshold"):
        try:
            vip = max(0, int(by_key["segment_vip_threshold"].strip()))
        except (ValueError, AttributeError):
            pass
    if vip <= reg:
        vip = reg + 1
    return reg, vip


@router.post("/settings/recalc-segments")
async def recalc_segments(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Пересчитать сегменты всех гостей по текущим порогам. Доступ: только admin."""
    reg, vip = await _get_segment_thresholds(session)
    result = await session.execute(select(Guest).where(Guest.deleted_at.is_(None)))
    guests = result.scalars().all()
    updated = 0
    for g in guests:
        new_seg = calc_segment(g.visits_count or 0, reg, vip)
        if (g.segment or "Новичок") != new_seg:
            g.segment = new_seg
            updated += 1
    await session.commit()
    return {"total": len(guests), "updated": updated}
