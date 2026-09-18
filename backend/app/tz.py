# -*- coding: utf-8 -*-
"""Внутри UTC, наружу Киев.

База хранит наивный UTC (`utcnow()`), и переводить хранилище на местную зону
нельзя: однажды сравнят киевское с UTC и не заметят, а в ночь перевода часов
местное время неоднозначно. Зато всё, что видит человек, — киевское, с явным
смещением: «2026-09-18T10:02:00+03:00». Строка без смещения — приглашение
угадать, и рано или поздно угадают неверно (в Киеве здоровый прогон три часа
выглядел зависшим из-за этого).

Владелец живёт в Киеве, поэтому наружу Киев, а не Варшава: дата подачи
объявления — это дата, а время прогона ему нужно по своим часам.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
WARSAW = ZoneInfo("Europe/Warsaw")
UTC = timezone.utc


def utcnow() -> datetime:
    """Наивный UTC — так, как хранит база."""
    return datetime.utcnow()


def to_kyiv(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KYIV)


def kyiv_str(dt, fmt="%d.%m.%Y %H:%M"):
    d = to_kyiv(dt)
    return d.strftime(fmt) if d else u"—"


def now_kyiv() -> datetime:
    return datetime.now(KYIV)


def install_json_encoder():
    """Все даты в ответах API — в киевской зоне и с явным смещением."""
    from fastapi import encoders
    encoders.ENCODERS_BY_TYPE[datetime] = lambda d: to_kyiv(d).isoformat()
