"""Фоновая проверка «ждущих» чеков: раз в N минут переспросить code-qr.ru.

Чек доходит до налоговой с задержкой (касса без связи — часы и дни). Пока окно
чека открыто, его опрашивает сам браузер; это — для чеков, которые не дошли за
минуту: сервер сам узнаёт, что чек готов, и в «Покупках» появится «чек готов».
Запрос статуса (info) проверку из пакета не тратит — тратит только add-qr.
Работает внутри процесса приложения (на Amvera он один), отдельный воркер не нужен.
"""
from __future__ import annotations


import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ServiceUnavailableError
from app.repositories.receipt import ReceiptRepository
from app.services import receipt_client
from app.services.receipt import ReceiptService

log = logging.getLogger("receipts")

EXPIRED_MESSAGE = "Чек так и не дошёл до налоговой — проверьте QR-код или занесите покупки вручную"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def refresh_pending_once(
    factory: async_sessionmaker[AsyncSession], *, now: datetime | None = None, pending_days: int = 3
) -> int:
    """Один проход: переспросить «ждущие» чеки (старше минуты). Вернёт, сколько стало готовыми."""
    now = now or _now()
    ready = 0
    async with factory() as session:
        repo = ReceiptRepository(session)
        for receipt in await repo.pending_before(now - timedelta(minutes=1)):
            if receipt.created_at and receipt.created_at < now - timedelta(days=pending_days):
                receipt.status, receipt.error = "error", EXPIRED_MESSAGE
                continue
            try:
                data = await receipt_client.info(receipt.provider_hash)
            except ServiceUnavailableError:
                break  # сервис или ключ недоступны — попробуем в следующий раз
            if not data.get("success"):
                continue  # «нет пакета» и т. п. — это не ответ про сам чек, ждём дальше
            ReceiptService._apply_info(receipt, data)
            ready += receipt.status == "done"
        await session.commit()
    return ready


async def run_poller(factory: async_sessionmaker[AsyncSession], minutes: int, pending_days: int) -> None:
    """Бесконечный цикл для lifespan: ошибки логируются, цикл не падает."""
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            ready = await refresh_pending_once(factory, pending_days=pending_days)
            if ready:
                log.info("Чеки: готово к проверке — %s", ready)
        except Exception:  # noqa: BLE001 — фоновая задача не должна умирать
            log.exception("Фоновая проверка чеков не удалась")
