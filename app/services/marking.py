"""Код маркировки «Честный знак» (GS1 DataMatrix): штрихкод, серийный номер, срок годности.

Код — строка из «идентификаторов применения» GS1:
  01 — GTIN, 14 цифр (EAN-13 упаковки с ведущим нулём);
  21 — серийный номер упаковки (переменной длины, обычно 6–13 символов);
  17 — «годен до» ГГММДД (товары со сроком хранения больше 72 часов);
  7003 — «годен до» ГГММДДЧЧММ (скоропорт, меньше 72 часов);
  91/92/93 — служебный криптохвост (нам не нужен).
Поля переменной длины разделяются символом GS (\\x1d). Сканеры иногда его теряют
или подменяют — тогда серийный номер подбираем по типичным длинам.
Срок в код производитель кладёт по желанию: если его нет — дату вводят руками.
"""
from __future__ import annotations


import re
from dataclasses import dataclass
from datetime import date, datetime

GS = "\x1d"
# известные префиксы и замены разделителя у разных сканеров
_PREFIXES = ("]d2", "]D2", "]C1", "]Q3")
_GS_ALIASES = ("è", "<GS>", "\\x1d", "␝")
_SERIAL_LENGTHS = (13, 6, 7, 8, 11, 20)   # без разделителя — пробуем по порядку


@dataclass
class MarkInfo:
    gtin: str                       # 14 цифр
    serial: str
    expires_on: date | None = None
    expires_at: datetime | None = None  # для 7003 — с точностью до минуты

    @property
    def barcode(self) -> str:
        """EAN-13 (как напечатан под штрихкодом): GTIN без ведущего нуля."""
        return self.gtin[1:] if self.gtin.startswith("0") else self.gtin


def _date6(s: str) -> date | None:
    try:
        y, m, d = int(s[:2]), int(s[2:4]), int(s[4:6])
        # ГС1: день 00 — «последний день месяца»
        if d == 0:
            nxt = date(2000 + y + (m // 12), m % 12 + 1, 1)
            return date.fromordinal(nxt.toordinal() - 1)
        return date(2000 + y, m, d)
    except ValueError:
        return None


def _datetime10(s: str) -> datetime | None:
    try:
        return datetime(2000 + int(s[:2]), int(s[2:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]))
    except ValueError:
        return None


def _parse_tail(rest: str, info: MarkInfo) -> bool:
    """Поля после серийного номера (через GS или подряд). False — не похоже на GS1."""
    while rest:
        if rest.startswith(GS):
            rest = rest[1:]
            continue
        if rest.startswith("17") and re.match(r"17\d{6}", rest) and _date6(rest[2:8]):
            info.expires_on = _date6(rest[2:8])
            rest = rest[8:]
        elif rest.startswith("7003") and re.match(r"7003\d{10}", rest) and _datetime10(rest[4:14]):
            info.expires_at = _datetime10(rest[4:14])
            info.expires_on = info.expires_at.date()
            rest = rest[14:]
        elif rest[:2] in ("91", "92", "93", "94", "95", "96", "97", "98", "99") or rest[:3] in ("240", "241", "310", "330"):
            # служебные и прочие поля переменной длины — до следующего GS
            nxt = rest.find(GS)
            if nxt < 0:
                return True
            rest = rest[nxt + 1:]
        else:
            return False
    return True


def parse_mark(raw: str | None) -> MarkInfo | None:
    """Разобрать код маркировки; None — это не код «Честного знака» (например, EAN-13)."""
    if not raw:
        return None
    s = raw.strip()
    for p in _PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
    for alias in _GS_ALIASES:
        s = s.replace(alias, GS)
    s = s.lstrip(GS)
    m = re.match(r"01(\d{14})21", s)
    if not m:
        return None
    gtin, rest = m.group(1), s[m.end():]
    if GS in rest:
        serial, tail = rest.split(GS, 1)
        info = MarkInfo(gtin=gtin, serial=serial)
        return info if serial and _parse_tail(tail, info) else None
    # разделителя нет: серийный номер — одной из типичных длин, остальное должно разобраться
    for n in _SERIAL_LENGTHS:
        if len(rest) < n:
            continue
        info = MarkInfo(gtin=gtin, serial=rest[:n])
        if _parse_tail(rest[n:], info):
            return info
    return MarkInfo(gtin=gtin, serial=rest) if rest else None
