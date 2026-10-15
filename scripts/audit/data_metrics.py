#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Метрики данных для внешнего аудитора — с боевой базы, ТОЛЬКО на чтение.

Аудитор не ходит в базу сам (там телефоны продавцов). Ему нужны числа, по
которым можно проверить, что система делает то, что о ней говорят: сколько
собирается, насколько обогащено, как устроены медианы и выгодность. Скрипт
печатает markdown; export_exchange.py кладёт его в snapshot/evidence/.

    .venv\\Scripts\\python.exe scripts\\audit\\data_metrics.py
"""
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"))
from app.analytics import split_key  # noqa: E402  (ключ пула читается тем же кодом, что его пишет)

DB = os.environ.get("WRO_DB") or os.path.join(os.environ.get("WRO_DATA") or r"C:\wro-data", "wro.db")


def main():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    one = lambda q, *a: c.execute(q, a).fetchone()[0]
    out = []
    w = out.append
    w("# Метрики данных Wrocław Analyzer — %s\n" % datetime.now().strftime("%d.%m.%Y %H:%M"))
    w("База открыта только на чтение. Персональных данных (телефонов, имён) здесь нет.\n")

    w("## Объём\n")
    w("| тип | активных | снятых |\n|---|---|---|")
    for t in ("sale", "rent"):
        w("| %s | %d | %d |" % (t, one("select count(*) from listings where offer_type=? and is_active=1", t),
                                one("select count(*) from listings where offer_type=? and is_active=0", t)))

    w("\n## Прогоны (последние 12)\n")
    w("| # | тип | статус | начало | конец | увидено | новых | ошибок |\n|---|---|---|---|---|---|---|---|")
    for r in c.execute("select id, kind, status, started_at, finished_at, seen, new, errors from scrape_runs "
                       "order by id desc limit 12"):
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (r[0], r[1], r[2], (r[3] or "")[:16], (r[4] or "")[:16],
                                                          r[5], r[6], r[7]))
    w("\nВремя в базе — UTC.")

    w("\n## Обогащения (активные)\n")
    w("| тип | всего | осиедле | состояние известно | телефон | заголовок переведён | описание переведено |")
    w("|---|---|---|---|---|---|---|")
    for t in ("sale", "rent"):
        tot = one("select count(*) from listings where is_active=1 and offer_type=?", t) or 1
        f = lambda cond: 100.0 * one("select count(*) from listings where is_active=1 and offer_type=? and %s" % cond, t) / tot
        w("| %s | %d | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% |" % (
            t, tot, f("coalesce(osiedle_override, osiedle) is not null"), f("condition <> 'unknown'"),
            f("seller_phone is not null and seller_phone <> ''"), f("title_uk is not null"),
            f("(description_pl is null or description_uk is not null)")))

    w("\n## Класс состояния (продажа, активные представители)\n")
    for cond, n in c.execute("select coalesce(condition_override, condition), count(*) from listings "
                             "where is_active=1 and offer_type='sale' and is_representative=1 group by 1 order by 2 desc"):
        w("- %s: %d" % (cond, n))

    w("\n## Выгодность (продажа, активные представители)\n")
    tot = one("select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=1")
    scored = one("select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=1 "
                 "and discount_pct is not null")
    w("- оценено: %d из %d" % (scored, tot))
    for thr in (10, 15, 20):
        w("- скидка ≥ %d%%: %d" % (thr, one("select count(*) from listings where is_active=1 and offer_type='sale' "
                                           "and is_representative=1 and discount_pct >= ?", thr)))
    w("- тонкая база (пул < 10): %d" % one("select count(*) from listings where is_active=1 and offer_type='sale' "
                                          "and is_representative=1 and deal_thin_base = 1"))
    thr = float(one("select coalesce((select value from settings where key='deal_threshold_pct'), '10')"))
    w("- «Вигідних зараз» на главной (скидка ≥ %g%%, без тонкой базы): %d" % (thr, one(
        "select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=1 "
        "and coalesce(deal_thin_base, 0) = 0 and discount_pct >= ?", thr)))
    w("\nНа каком уровне места найдена база:\n")
    for lvl, n in c.execute("select baseline_level, count(*) from listings where is_active=1 and offer_type='sale' "
                            "and is_representative=1 and baseline_level is not null group by 1 order by 2 desc"):
        w("- %s: %d" % (lvl, n))
    w("\nС каким классом состояния и эпохой дома сравнивали (по классу самой квартиры):\n")
    w("| класс квартиры | свой класс | другой класс (старый фонд «do wykończenia» → под ремонт) "
      "| смешанный | та же эпоха |\n|---|---|---|---|---|")
    rows = c.execute("select coalesce(condition_override, condition), baseline_level, baseline_key from listings "
                     "where is_active=1 and offer_type='sale' and is_representative=1 "
                     "and baseline_key is not null").fetchall()
    by = {}
    for cond, level, key in rows:
        k = split_key(level, json.loads(key))
        if not k:
            continue
        cnt = by.setdefault(cond, Counter())
        cnt["own" if k[2] == cond else ("mixed" if k[2] == "mixed" else "other")] += 1
        cnt["era"] += k[3] != "any"
    for cond, cnt in sorted(by.items()):
        w("| %s | %d | %d | %d | %d |" % (cond, cnt["own"], cnt["other"], cnt["mixed"], cnt["era"]))
    w("\nПоправка на площадь (продажа), измерена на данных: `%s`" % one(
        "select value from settings where key = 'area_coef_sale'"))
    w("\nПоправка на возраст дома (продажа): `%s`" % one(
        "select coalesce((select value from settings where key = 'era_coef_sale'), 'ещё не считалась')"))

    w("\n## Доходность (продажа)\n")
    w("- посчитана: %d" % one("select count(*) from listings where is_active=1 and offer_type='sale' and yield_pct is not null"))
    w("- ≥ 6%%: %d" % one("select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=1 "
                          "and yield_pct >= 6"))
    w("- вне 0..30%% (должно быть 0): %d" % one("select count(*) from listings where is_active=1 and yield_pct is not null "
                                               "and (yield_pct <= 0 or yield_pct > 30)"))
    w("- отделка в расчёте, zł/м²: %s" % one("select value from settings where key = 'renovation_cost_sqm_pln'"))
    w("- поправка на площадь (аренда): `%s`" % one("select value from settings where key = 'area_coef_rent'"))
    w("- поправка на возраст дома (аренда): `%s`" % one(
        "select coalesce((select value from settings where key = 'era_coef_rent'), 'ещё не считалась')"))

    w("\n## Склейка дублей (активные продажи)\n")
    w("- представителей: %d, скрыто дублей: %d" % (
        one("select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=1"),
        one("select count(*) from listings where is_active=1 and offer_type='sale' and is_representative=0")))
    w("- групп-инвестиций застройщика: %d" % one("select count(distinct dedup_group) from listings where is_active=1 "
                                                "and group_kind='investment'"))
    w("- групп без активного представителя (должно быть 0): %d" % one(
        "select count(*) from (select dedup_group from listings where is_active=1 group by 1 having sum(is_representative)=0)"))

    w("\n## Снижения цены\n")
    w("- активных с реальным снижением: %d" % one("select count(*) from listings where is_active=1 and price_drop_pct < 0"))

    w("\n## Настройки (без секретов)\n")
    for k, v in c.execute("select key, value from settings where key not like '%key%' and key not like '%token%' "
                          "and key not like 'area_coef%' and key not like 'era_coef%' and key not like 'resume:%' "
                          "order by key"):
        w("- `%s` = `%s`" % (k, (v or "")[:80]))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
