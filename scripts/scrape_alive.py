# -*- coding: utf-8 -*-
"""Идёт ли прогон ПРЯМО СЕЙЧАС — по базе, а не по HTTP.

Нужен safe_restart.ps1. Обычно он спрашивает `/api/summary`, но пока сервер
занят прогоном, сводка по 21 тыс. строк ждёт писателя SQLite и может не
ответить за 20 с. 26.09.2026 скрипт принял это молчание за «сервер умер» и
перезапустил его посреди прогона: продажа №27 оборвалась на 9369 объявлениях
из 11 300, пост-обработка не выполнилась.

Признак живого прогона — строка `scrape_runs` со статусом `running` и свежей
отметкой жизни (`last_beat`): её пишет отдельная сессия каждые несколько
секунд. Отметка старше 15 минут — прогон уже не живой, его добьёт сторож.

База открывается ТОЛЬКО на чтение (`mode=ro`), чтобы не мешать прогону.

    python scripts/scrape_alive.py        # печатает running / idle / unknown
    код возврата: 0 — идёт, 1 — не идёт, 2 — определить не удалось
"""
from __future__ import print_function

import os
import sqlite3
import sys
from datetime import datetime, timedelta

STALE_MIN = 15


def db_path():
    p = os.environ.get("WRO_DB")
    if p:
        return p
    data = os.environ.get("WRO_DATA") or "."
    return os.path.join(data, "wro.db")


def main():
    path = db_path()
    if not os.path.exists(path):
        print("unknown: нет файла базы %s" % path)
        return 2
    try:
        uri = "file:%s?mode=ro" % path.replace("\\", "/")
        con = sqlite3.connect(uri, uri=True, timeout=5)
        row = con.execute(
            "select id, kind, last_beat, started_at from scrape_runs "
            "where status = 'running' order by id desc limit 1").fetchone()
        con.close()
    except sqlite3.Error as e:
        print("unknown: %s" % e)
        return 2
    if row is None:
        print("idle")
        return 1
    rid, kind, beat, started = row
    stamp = beat or started
    if not stamp:
        print("running: прогон %s #%s без отметки времени" % (kind, rid))
        return 0
    try:
        # внутри базы время в UTC (docs/ARCHITECTURE.md §«Время»)
        seen = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print("running: прогон %s #%s, отметку не разобрать (%s)" % (kind, rid, stamp))
        return 0
    age = datetime.utcnow() - seen
    if age > timedelta(minutes=STALE_MIN):
        print("idle: прогон %s #%s числится идущим, но молчит %d мин — его закроет сторож"
              % (kind, rid, age.total_seconds() // 60))
        return 1
    print("running: прогон %s #%s, отметка жизни %d с назад" % (kind, rid, age.total_seconds()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
