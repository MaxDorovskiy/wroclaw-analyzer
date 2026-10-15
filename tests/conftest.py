# -*- coding: utf-8 -*-
"""Тесты идут на ВРЕМЕННОЙ базе: WRO_DB задаётся до импорта приложения,
потому что config.py читает окружение при импорте."""
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="wro-test-"))
os.environ["WRO_DB"] = str(TMP / "test.db")
os.environ["WRO_DATA"] = str(TMP)
os.environ["DISABLE_SCHEDULER"] = "1"
# Реестр видеокарты — ОБЩАЯ с другими проектами вещь на ПК владельца.
# 26.09.2026 тесты подняли приложение на временной базе без настроек, и старт
# записал в боевой реестр чужое имя модели.
os.environ["GPU_REGISTRY"] = "off"
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
    yield
    # Каждый прогон оставлял в %TEMP% папку с базой по 7 МБ: к 15.10.2026 их
    # набралось 96 (224 МБ). Базу и server.log (его держит открытым журнал
    # main.py) сначала закрываем — иначе Windows не даст удалить файлы.
    import logging
    from app.db import engine
    engine.dispose()
    root = logging.getLogger()
    for h in list(root.handlers):
        if str(getattr(h, "baseFilename", "")).startswith(str(TMP)):
            root.removeHandler(h)
            h.close()
    shutil.rmtree(str(TMP), ignore_errors=True)


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
