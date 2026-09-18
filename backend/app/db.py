# -*- coding: utf-8 -*-
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import DB_PATH

engine = create_engine(
    "sqlite:///%s" % DB_PATH,
    connect_args={"check_same_thread": False, "timeout": 60},
    # во время прогона фоновый поток держит соединение, а API продолжает
    # обслуживать каталог — пул побольше
    pool_size=10,
    max_overflow=20,
    pool_timeout=60,
    pool_recycle=1800,
    # после сна ноутбука соединения в пуле протухают: pre_ping молча
    # заменяет мёртвое вместо 500 до перезапуска
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    """WAL: читатели не блокируются писателем — каталог отвечает во время прогона."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=60000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns():
    """Лёгкая миграция SQLite: новые таблицы, недостающие колонки И индексы.

    create_all() существующие таблицы пропускает целиком, вместе с новыми
    индексами — поэтому индексы досоздаём здесь же, иначе сортировка по
    свежедобавленной колонке идёт полным сканом.
    """
    from sqlalchemy import inspect, text
    from .models import Base
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if table.name not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(text(
                    'ALTER TABLE %s ADD COLUMN "%s" %s' % (table.name, col.name, ddl)))
            have_idx = {i["name"] for i in insp.get_indexes(table.name)}
            for idx in table.indexes:
                if idx.name not in have_idx:
                    idx.create(bind=conn)
