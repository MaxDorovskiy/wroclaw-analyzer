# -*- coding: utf-8 -*-
"""Восстановить из сохранённых карточек два поля: телефон и класс состояния.

Зачем отдельный скрипт, а не `reparse.py`. Полный переразбор берёт из
`raw_json` ВСЁ, в том числе цену — а карточка скачана раньше последнего
прохода по выдаче, и на боевой базе 24.09.2026 это откатило бы цену у 433
объявлений к значению на день скачивания карточки. Здесь трогаем только то,
что выдача в принципе не знает.

Что чинится:

1. `seller_phone` у частников Otodom. Адаптер читал `owner.phones`, а у
   частника он всегда пустой: номер лежит в `contactDetails.phones` и
   `owner.contacts[].phone`. 1670 телефонов собственников — тех самых, ради
   которых система и собиралась, — лежали в базе и не были видны.

2. `condition`. Класс состояния выводится из описания, а описание есть
   только в карточке. Проход по выдаче пересчитывал его на пустом тексте и
   записывал "unknown" поверх честного значения, так что к 24.09.2026 81%
   объявлений продажи числились «невідомо». Сам механизм закрыт в
   `scraper.DETAILS_ONLY`; здесь — разовое восстановление истории.

Ручные правки владельца (`condition_override`) не трогаем.

    python scripts/backfill_card_fields.py [--dry]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.db import SessionLocal                     # noqa: E402
from backend.app.models import Listing                      # noqa: E402
from backend.app.normalize import classify_condition        # noqa: E402

BATCH = 1000


def phone_from_raw(d):
    """Тот же порядок, что в sources/otodom.py после правки 24.09.2026."""
    owner = d.get("owner") or {}
    agency = d.get("agency") or {}
    contact = d.get("contactDetails") or {}
    phones = owner.get("phones") or agency.get("phones") or contact.get("phones") or []
    if not phones:
        phones = [c.get("phone") for c in (owner.get("contacts") or [])
                  if isinstance(c, dict) and c.get("phone")]
    phones = [p for p in phones if p]
    return str(phones[0]) if phones else None


def main(dry=False):
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(Listing.id).filter(
            Listing.raw_json.isnot(None), Listing.details_fetched.is_(True)).all()]
        print(u"карточек в базе: %d" % len(ids))
        phones = conds = 0
        updates = []
        for i, lid in enumerate(ids, 1):
            row = db.get(Listing, lid)
            try:
                d = json.loads(row.raw_json)
            except (TypeError, ValueError):
                continue
            patch = {}
            if not row.seller_phone:
                ph = phone_from_raw(d)
                if ph:
                    patch["seller_phone"] = ph
                    phones += 1
            if not row.condition_override:
                cond, src = classify_condition(
                    row.construction_status, row.market,
                    row.title_pl or u"", row.description_pl)
                if cond != row.condition:
                    patch["condition"], patch["condition_src"] = cond, src
                    conds += 1
            if patch:
                patch["id"] = lid
                updates.append(patch)
            if len(updates) >= BATCH or i == len(ids):
                if updates and not dry:
                    # по колонкам, а не через ORM-объекты: у строк висят
                    # description_pl и raw_json, перебор их вытянул бы в память
                    db.bulk_update_mappings(Listing, updates)
                    db.commit()
                updates = []
                if i % 5000 == 0 or i == len(ids):
                    print(u"  %d/%d" % (i, len(ids)))
            db.expunge(row)
        print(u"телефонов проставлено: %d" % phones)
        print(u"состояний исправлено:  %d" % conds)
        if dry:
            print(u"(--dry: ничего не записано)")
        else:
            print(u"пересчитать выгодность: POST /api/recompute")
    finally:
        db.close()


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
