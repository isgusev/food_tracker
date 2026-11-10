"""«Сегодня» и «сейчас» по времени семьи.

Сервер на Amvera работает в UTC, а семья живёт по Москве: с 00:00 до 03:00 МСК
серверное `date.today()` — ещё вчера, и покупки, «съел», сводки денег уходили
во вчерашний день. Поэтому:
  * «какой сегодня день» для учёта — только `today()` (часовой пояс APP_TIMEZONE);
  * метки времени в базе (created_at, checked_at…) — по-прежнему UTC без пояса;
  * чтобы выбрать записи за местные дни — `utc_bounds(start, end)`.
"""
from __future__ import annotations


from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@lru_cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def tz() -> ZoneInfo:
    return _zone(get_settings().app_timezone)


def today() -> date:
    """Сегодняшняя дата по времени семьи."""
    return datetime.now(tz()).date()


def utc_now() -> datetime:
    """Сейчас в UTC без пояса — как хранятся метки времени в базе."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Местные дни [start, end] → полуинтервал [t0, t1) в UTC без пояса."""
    zone = tz()
    t0 = datetime.combine(start, time.min, tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)
    t1 = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)
    return t0, t1
