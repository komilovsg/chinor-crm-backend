"""Broadcasts API: GET stats, GET history (last 5), GET history/export (admin), POST (create campaign + campaign_sends, trigger webhook)."""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models import Campaign, CampaignSend, Guest, Setting, User
from app.db.session import get_session
from app.services.webhooks import schedule_webhook

router = APIRouter(prefix="/api", tags=["broadcasts"])

# Человекочитаемые названия сегментов (не показывать "selected" и т.п.)
SEGMENT_DISPLAY_NAMES = {
    "all": "Все гости",
    "selected": "Выбранные гости",
    "VIP": "VIP",
    "Постоянные": "Постоянные",
    "Новички": "Новички",
}


def _campaign_display_name(segment: Optional[str], guest_ids: Optional[List[int]]) -> str:
    """Название рассылки для отображения пользователю."""
    if guest_ids:
        return "Выбранные гости"
    seg = (segment or "").strip()
    if seg.lower() == "selected":
        return "Выбранные гости"
    return SEGMENT_DISPLAY_NAMES.get(seg, seg or "Все гости")

# Папка для загруженных изображений (должна совпадать с main.py)
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class BroadcastStatsResponse(BaseModel):
    available: int
    delivered: Optional[int] = None
    errors: Optional[int] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    message_text: str
    image_url: Optional[str] = None
    target_segment: Optional[str]
    scheduled_at: Optional[str] = None  # алиас для scheduled_for
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BroadcastHistoryItemResponse(BaseModel):
    campaign: CampaignResponse
    sent_count: int
    failed_count: int


class CreateBroadcastRequest(BaseModel):
    segment: str
    messageText: str
    imageUrl: Optional[str] = None


def _normalize_campaign_name_for_display(name: str) -> str:
    """Чтобы пользователь не видел 'selected' — подменяем на внятные слова."""
    if not name:
        return name
    if "selected" in name.lower():
        return "Рассылка: Выбранные гости"
    return name


def _campaign_to_response(c: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=c.id,
        name=_normalize_campaign_name_for_display(c.name),
        message_text=c.message_text,
        image_url=getattr(c, "image_url", None),
        target_segment=c.target_segment,
        scheduled_at=c.scheduled_for.isoformat() if c.scheduled_for else None,
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
    )


@router.post("/broadcasts/upload-image")
async def upload_broadcast_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Загрузить изображение для рассылки. JPEG/PNG, до 5 MB. Возвращает публичный URL."""
    UPLOADS_DIR.mkdir(exist_ok=True)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"detail": "Только JPEG и PNG"},
        )
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=400,
            content={"detail": "Файл не более 5 MB"},
        )
    filename = f"{uuid.uuid4().hex}{ext}"
    path = UPLOADS_DIR / filename
    path.write_bytes(content)
    base = str(request.base_url).rstrip("/")
    url = f"{base}/uploads/{filename}"
    return {"url": url}


@router.get("/broadcasts/stats", response_model=BroadcastStatsResponse)
async def get_broadcast_stats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BroadcastStatsResponse:
    """Количество гостей, доступных для рассылки: с телефоном, не в стоп-листе, не удалены."""
    stmt = select(func.count(Guest.id)).where(
        Guest.deleted_at.is_(None),
        Guest.is_in_stop_list.is_(False),
        Guest.phone != "",
    )
    result = await session.execute(stmt)
    available = (result.scalar() or 0)
    return BroadcastStatsResponse(available=available, delivered=None, errors=None)


@router.get("/broadcasts/history", response_model=List[BroadcastHistoryItemResponse])
async def get_broadcast_history(
    limit: int = Query(5, ge=1, le=100, description="Количество последних записей"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[BroadcastHistoryItemResponse]:
    """Список последних кампаний с агрегатами sent/failed (по умолчанию 5)."""
    campaigns_result = await session.execute(
        select(Campaign).order_by(Campaign.id.desc()).limit(limit)
    )
    campaigns = campaigns_result.scalars().all()
    out = []
    for c in campaigns:
        sent_result = await session.execute(
            select(func.count(CampaignSend.id)).where(
                CampaignSend.campaign_id == c.id,
                CampaignSend.status == "sent",
            )
        )
        failed_result = await session.execute(
            select(func.count(CampaignSend.id)).where(
                CampaignSend.campaign_id == c.id,
                CampaignSend.status == "failed",
            )
        )
        sent_count = (sent_result.scalar() or 0)
        failed_count = (failed_result.scalar() or 0)
        out.append(
            BroadcastHistoryItemResponse(
                campaign=_campaign_to_response(c),
                sent_count=sent_count,
                failed_count=failed_count,
            )
        )
    return out


@router.get("/broadcasts/history/export", response_model=List[BroadcastHistoryItemResponse])
async def export_broadcast_history(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> List[BroadcastHistoryItemResponse]:
    """Полная выгрузка истории рассылок для админа (CSV на фронте)."""
    campaigns_result = await session.execute(
        select(Campaign).order_by(Campaign.id.desc())
    )
    campaigns = campaigns_result.scalars().all()
    out = []
    for c in campaigns:
        sent_result = await session.execute(
            select(func.count(CampaignSend.id)).where(
                CampaignSend.campaign_id == c.id,
                CampaignSend.status == "sent",
            )
        )
        failed_result = await session.execute(
            select(func.count(CampaignSend.id)).where(
                CampaignSend.campaign_id == c.id,
                CampaignSend.status == "failed",
            )
        )
        sent_count = (sent_result.scalar() or 0)
        failed_count = (failed_result.scalar() or 0)
        out.append(
            BroadcastHistoryItemResponse(
                campaign=_campaign_to_response(c),
                sent_count=sent_count,
                failed_count=failed_count,
            )
        )
    return out


async def _get_broadcast_webhook_url(session: AsyncSession) -> str:
    """Получить URL webhook для рассылок: broadcastWebhookUrl или webhookUrl."""
    result = await session.execute(
        select(Setting).where(
            Setting.key.in_(("broadcastWebhookUrl", "webhookUrl"))
        )
    )
    by_key = {r.key: (r.value or "").strip() for r in result.scalars().all()}
    return by_key.get("broadcastWebhookUrl") or by_key.get("webhookUrl") or ""


@router.post("/broadcasts", response_model=CampaignResponse)
async def create_broadcast(
    body: CreateBroadcastRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CampaignResponse:
    """Создать кампанию и записи campaign_sends. После commit — POST webhook в n8n (если URL задан)."""
    now = datetime.now(timezone.utc)
    image_url = (body.imageUrl or "").strip() or None
    display_name = _campaign_display_name(body.segment, None)
    campaign = Campaign(
        name=f"Рассылка: {display_name}",
        message_text=body.messageText,
        image_url=image_url,
        target_segment=body.segment or None,
        scheduled_for=None,
        created_at=now,
        updated_at=now,
    )
    session.add(campaign)
    await session.flush()

    # Рассылка только по сегменту; гости с галочкой «исключить из рассылок» не попадают
    guests_stmt = select(Guest).where(
        Guest.deleted_at.is_(None),
        Guest.is_in_stop_list.is_(False),
        Guest.phone != "",
        Guest.exclude_from_broadcasts.is_(False),
    )
    if body.segment and body.segment.strip() and body.segment.strip().lower() != "all":
        guests_stmt = guests_stmt.where(Guest.segment == body.segment.strip())
    guests_result = await session.execute(guests_stmt)
    guests = guests_result.scalars().all()

    for guest in guests:
        send = CampaignSend(
            campaign_id=campaign.id,
            guest_id=guest.id,
            status="pending",
            created_at=now,
        )
        session.add(send)
    await session.commit()
    await session.refresh(campaign)

    webhook_url = await _get_broadcast_webhook_url(session)
    if webhook_url:
        guests_payload = [
            {
                "id": g.id,
                "phone": g.phone or "",
                "name": (g.name or "").strip() or "",
                "last_visit_at": g.last_visit_at.strftime("%d.%m.%Y") if g.last_visit_at else "",
            }
            for g in guests
        ]
        payload = {
            "campaign_id": campaign.id,
            "segment": body.segment,
            "messageText": body.messageText,
            "guests": guests_payload,
        }
        if image_url:
            payload["imageUrl"] = image_url
        schedule_webhook(webhook_url, payload)

    return _campaign_to_response(campaign)
