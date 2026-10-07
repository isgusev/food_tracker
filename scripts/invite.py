"""Создать одноразовый код регистрации прямо в базе (для локальной работы).

    python -m scripts.invite                 # код без семьи: новый пользователь получит свою семью
    python -m scripts.invite --household 3   # сразу в семью с id=3

На хостинге первый вход — по FIRST_INVITE_CODE, дальше коды создаются в
приложении: «Семья → Пригласить в приложение».
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.session import init_db
from app.models.user import RegistrationInvite
from app.services.household import new_invite_code


async def main(household_id: int | None, days: int) -> None:
    factory = init_db(get_settings())
    async with factory() as session:
        code = new_invite_code(10)
        session.add(RegistrationInvite(
            code=code, household_id=household_id,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days),
        ))
        await session.commit()
    print(f"Код приглашения: {code} (действует {days} дн.)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--household", type=int, default=None)
    p.add_argument("--days", type=int, default=7)
    a = p.parse_args()
    asyncio.run(main(a.household, a.days))
