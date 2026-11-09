"""Время семьи против UTC: «сегодня» и границы местных дней для выборок по меткам времени."""
from __future__ import annotations


from datetime import date, datetime

from app.core import clock


def test_utc_bounds_for_moscow_day(monkeypatch):
    monkeypatch.setattr(clock, "tz", lambda: clock._zone("Europe/Moscow"))
    t0, t1 = clock.utc_bounds(date(2026, 11, 10), date(2026, 11, 10))
    # московские сутки 10.11 = с 21:00 UTC 09.11 до 21:00 UTC 10.11
    assert (t0, t1) == (datetime(2026, 11, 9, 21, 0), datetime(2026, 11, 10, 21, 0))
    # действие в 02:12 МСК 10.11 (= 23:12 UTC 09.11) попадает в этот день
    assert t0 <= datetime(2026, 11, 9, 23, 12) < t1


def test_today_uses_family_zone(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 9, 23, 12, tzinfo=clock.timezone.utc).astimezone(tz)
    monkeypatch.setattr(clock, "datetime", Fixed)
    monkeypatch.setattr(clock, "tz", lambda: clock._zone("Europe/Moscow"))
    assert clock.today() == date(2026, 11, 10)          # на сервере в UTC ещё 9-е
