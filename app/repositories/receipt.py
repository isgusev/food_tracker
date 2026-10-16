"""Репозитории кассовых чеков и выученных соответствий строк чека продуктам."""
from __future__ import annotations


from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.models.product import Product
from app.models.receipt import Receipt, ReceiptAlias
from app.repositories.base import BaseRepository


class ReceiptRepository(BaseRepository[Receipt]):
    model = Receipt

    async def by_qr(self, household_id: int, qr_raw: str) -> Receipt | None:
        stmt = select(Receipt).where(Receipt.household_id == household_id, Receipt.qr_raw == qr_raw)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, receipt: Receipt) -> Receipt:
        """Сохранить новый чек; если тот же QR параллельно уже занесли — вернуть тот."""
        try:
            async with self._session.begin_nested():
                self._session.add(receipt)
            await self._session.refresh(receipt)  # created_at (server default) — сразу, без ленивой загрузки
            return receipt
        except IntegrityError:
            existing = await self.by_qr(receipt.household_id, receipt.qr_raw)
            assert existing is not None
            return existing

    async def recent(self, household_id: int, limit: int = 20) -> list[Receipt]:
        stmt = (
            select(Receipt)
            .where(Receipt.household_id == household_id)
            .order_by(Receipt.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def catalog_candidates(self, patterns: set[str], limit: int = 300) -> list[Product]:
        """Продукты справочника, в названии которых есть хоть один из кусочков слов.

        search_name хранится в нижнем регистре (Python .lower()), поэтому LIKE
        без SQL LOWER() — он не работает с кириллицей в SQLite.
        """
        if not patterns:
            return []
        stmt = (
            select(Product)
            .where(or_(*(Product.search_name.like(f"%{p}%") for p in sorted(patterns))))
            .options(selectinload(Product.packages), joinedload(Product.brand))
            .order_by(Product.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).unique().scalars().all())


class ReceiptAliasRepository(BaseRepository[ReceiptAlias]):
    model = ReceiptAlias

    async def for_names(self, household_id: int, norm_names: set[str]) -> list[ReceiptAlias]:
        """Все соответствия семьи для этих строк чека (любых магазинов)."""
        if not norm_names:
            return []
        stmt = (
            select(ReceiptAlias)
            .where(ReceiptAlias.household_id == household_id, ReceiptAlias.norm_name.in_(norm_names))
            .order_by(ReceiptAlias.hits.desc(), ReceiptAlias.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find(self, household_id: int, store_inn: str | None, norm_name: str) -> ReceiptAlias | None:
        stmt = select(ReceiptAlias).where(
            ReceiptAlias.household_id == household_id,
            ReceiptAlias.norm_name == norm_name,
            ReceiptAlias.store_inn.is_(None) if store_inn is None else ReceiptAlias.store_inn == store_inn,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
