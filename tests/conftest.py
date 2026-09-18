# -*- coding: utf-8 -*-
"""Тесты идут на ВРЕМЕННОЙ базе: WRO_DB задаётся до импорта приложения,
потому что config.py читает окружение при импорте."""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="wro-test-"))
os.environ["WRO_DB"] = str(TMP / "test.db")
os.environ["WRO_DATA"] = str(TMP)
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ.pop("WRO_WEB_PASS", None)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from app.db import SessionLocal, ensure_columns  # noqa: E402
from app.models import Base  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    ensure_columns()


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def clean_db(db):
    for t in reversed(Base.metadata.sorted_tables):
        db.execute(t.delete())
    db.commit()
    yield db


@pytest.fixture
def fixtures():
    return FIX
