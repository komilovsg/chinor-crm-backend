"""Fire-and-forget webhook calls. Не блокирует основной поток, логирует ошибки."""
import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 10.0


async def call_webhook(url: str, payload: dict[str, Any]) -> None:
    """
    Асинхронный POST на webhook. Fire-and-forget — не ждём ответа в вызывающем коде.
    Пустой URL — ничего не делать. Ошибки логируются, не пробрасываются.
    """
    url = (url or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Webhook %s returned %d: %s",
                    url,
                    resp.status_code,
                    resp.text[:200] if resp.text else "",
                )
    except httpx.TimeoutException:
        logger.warning("Webhook %s timeout after %.1fs", url, WEBHOOK_TIMEOUT)
    except Exception as e:
        logger.exception("Webhook %s failed: %s", url, e)


def schedule_webhook(url: str, payload: dict[str, Any]) -> None:
    """
    Запустить вызов webhook в фоне. Не ждёт завершения.
    Вызывать после commit в create_broadcast / create_booking.
    """
    asyncio.create_task(call_webhook(url, payload))
