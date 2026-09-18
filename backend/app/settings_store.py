# -*- coding: utf-8 -*-
from typing import Dict

from sqlalchemy.orm import Session

from .config import DEFAULT_SETTINGS
from .models import Setting


def get_settings(db: Session) -> Dict[str, str]:
    vals = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        vals[row.key] = row.value if row.value is not None else ""
    return vals


def get_setting(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row is None or row.value is None:
        return DEFAULT_SETTINGS.get(key, "")
    return row.value


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_int(db: Session, key: str, default: int) -> int:
    try:
        return int(float(get_setting(db, key)))
    except (TypeError, ValueError):
        return default


def get_float(db: Session, key: str, default: float) -> float:
    try:
        return float(get_setting(db, key))
    except (TypeError, ValueError):
        return default
