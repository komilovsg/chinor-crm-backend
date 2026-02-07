"""Broadcasts API: GET stats, GET history, POST (create campaign + campaign_sends, no real send)."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Campaign, CampaignSend, Guest, User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["broadcasts"])


class BroadcastStatsResponse(BaseModel):
    available: int
    delivered: Optional[int] = None
    errors: Optional[int] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    message_text: str
    target_segment: Optional[str]
    scheduled_at: Optional[str]
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


def _campaign_to_response(c: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=c.id,
        name=c.name,
        message_text=c.message_text,
        target_segment=c.target_segment,
        scheduled_at=c.scheduled_at.isoformat() if c.scheduled_at else None,
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
    )


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
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[BroadcastHistoryItemResponse]:
    """Список кампаний с агрегатами sent/failed по campaign_sends."""
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


@router.post("/broadcasts", response_model=CampaignResponse)
async def create_broadcast(
    body: CreateBroadcastRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CampaignResponse:
    """Создать кампанию и записи campaign_sends со статусом pending. Отправку в WhatsApp не делать."""
    now = datetime.now(timezone.utc)
    campaign = Campaign(
        name=f"Рассылка: {body.segment}",
        message_text=body.messageText,
        target_segment=body.segment or None,
        scheduled_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(campaign)
    await session.flush()

    guests_stmt = select(Guest).where(
        Guest.deleted_at.is_(None),
        Guest.is_in_stop_list.is_(False),
        Guest.phone != "",
    )
    if body.segment and body.segment.strip():
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
    return _campaign_to_response(campaign)
