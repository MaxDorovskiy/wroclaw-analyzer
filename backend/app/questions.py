# -*- coding: utf-8 -*-
"""Вопросы к владельцу — раздел «Питання до мене» на сайте.

Правило владельца от 27.09.2026: в каждом проекте, где есть сайт и сервер,
должен быть список отложенных вопросов. Владелец видит, что висит, и может
ответить прямо там; номера — те же, что в чате, поэтому «№12 — да» работает
в любой момент и в любом месте.

Состояния: `open` — ждёт ответа; `answered` — ответ есть, осталось сделать;
`deferred` — владелец отложил, не напоминать; `done` — сделано.

Номера НЕ автоинкремент: они приходят из переписки. Новый вопрос берёт
следующий свободный (`add`), и этот же номер называется в чате.
"""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import OwnerQuestion

STATUS_UK = {"open": u"чекає на відповідь", "answered": u"відповідь є, робимо",
             "deferred": u"відкладено", "done": u"зроблено"}
OPEN_STATES = ("open", "answered")

# Вопросы из переписки. Номера — те, под которыми они прозвучали в чате.
# (num, дата, тема, вопрос, зачем, статус, ответ, итог)
SEED = [
    (1, "09.10.2026", u"Автозапуск",
     u"Виконати install.ps1 -TasksOnly від адміністратора, щоб сервер піднімався без входу в систему",
     u"Було єдине спрацювання «при вході»: після перезавантаження на оновлення сайт не піднімався, "
     u"поки власник не сяде за компʼютер, і прогони в ці дні не відбувалися.",
     "done", u"виконано 10.10.2026",
     u"Два спрацювання (запуск Windows + вхід), вхід S4U, -StartWhenAvailable. "
     u"Chromium у процесі S4U перевірено — працює."),
    (2, "09.10.2026", u"Цей розділ",
     u"Зробити розділ «Питання до мене» на сайті",
     u"Правило власника від 27.09.2026: бачити, що висить, і відповідати прямо на сайті.",
     "done", u"так, роби", u"Зроблено 10.10.2026 — ви читаєте його зараз."),
    (3, "09.10.2026", u"Переклад",
     u"Описи перекладаються ~480 на добу — залишаємо чи підняти пріоритет відеокарти?",
     u"Упирається не в ліміт (2500), а у нічне вікно 23:00–07:00 і швидкість моделі. "
     u"У черзі 6617 описів — це ще близько двох тижнів.",
     "answered", u"залишаємо", u"Пріоритет на відеокарті не чіпаємо."),
    (4, "24.09.2026", u"Телефони OLX",
     u"Дати вхід в акаунт OLX, щоб зібрати телефони 3138 приватних продавців",
     u"Акаунт потрібен на ПОЛЬСЬКОМУ olx.pl (той самий сайт, звідки беремо оголошення) — "
     u"звичайна безкоштовна реєстрація поштою. API телефон не віддає, номер показується "
     u"тільки після входу. Збір — браузером, 1 номер за хвилину, лише по обраних і вигідних. "
     u"Приватник — це торг без комісії, саме заради цього система й збиралася.",
     "deferred", u"відкладено 10.10.2026", None),
    (5, "10.10.2026", u"Викатка",
     u"Перезапустити сервер від адміністратора, щоб доїхала мікроправка підігріву зведення",
     u"Після переходу на вхід S4U задачу Планувальника не зупинити зі звичайного PowerShell, "
     u"і будь-яка викатка мовчки не доїжджає. Команду з запитом прав друкує сам safe_restart.ps1.",
     "open", None, None),
]


def seed(db: Session) -> int:
    """Записать вопросы из переписки, не трогая уже отвеченные."""
    have = {n for (n,) in db.execute(select(OwnerQuestion.num)).all()}
    added = 0
    for num, asked, topic, text, why, status, answer, result in SEED:
        if num in have:
            continue
        db.add(OwnerQuestion(
            num=num, asked_at=asked, topic=topic, text=text, why=why, status=status,
            answer=answer, result=result, updated_at=datetime.utcnow(),
            answered_at=datetime.utcnow() if answer else None,
            answered_via=u"чат" if answer else None))
        added += 1
    if added:
        db.commit()
    return added


def _dict(q: OwnerQuestion) -> Dict:
    return {"num": q.num, "asked_at": q.asked_at, "topic": q.topic, "text": q.text,
            "why": q.why, "status": q.status, "status_uk": STATUS_UK.get(q.status, q.status),
            "answer": q.answer, "answered_at": q.answered_at, "answered_via": q.answered_via,
            "result": q.result, "updated_at": q.updated_at}


def all_questions(db: Session) -> List[Dict]:
    """Сначала то, что ждёт действия, потом отложенное, в конце сделанное."""
    order = {"open": 0, "answered": 1, "deferred": 2, "done": 3}
    rows = db.query(OwnerQuestion).all()
    rows.sort(key=lambda q: (order.get(q.status, 9), -(q.num or 0)))
    return [_dict(q) for q in rows]


def open_count(db: Session) -> int:
    """Сколько ждёт ответа — число на вкладке. Отложенное не считаем: владелец
    уже сказал «не сейчас», и мигать этим было бы навязчиво."""
    return db.execute(select(func.count()).select_from(OwnerQuestion)
                      .where(OwnerQuestion.status == "open")).scalar() or 0


def answer(db: Session, num: int, text: str, via: str = u"сайт") -> Optional[Dict]:
    q = db.get(OwnerQuestion, num)
    if q is None:
        return None
    q.status = "answered"
    q.answer = (text or "").strip()[:4000]
    q.answered_at = q.updated_at = datetime.utcnow()
    q.answered_via = via
    db.commit()
    return _dict(q)


def set_status(db: Session, num: int, status: str) -> Optional[Dict]:
    """«Відкласти» и «Повернути» — одной ручкой: иначе их было бы три почти
    одинаковых, и каждая со своим набором разрешённых переходов."""
    if status not in ("open", "deferred"):
        return None
    q = db.get(OwnerQuestion, num)
    if q is None or q.status == "done":
        return None                       # сделанное обратно не открываем
    q.status = status
    q.updated_at = datetime.utcnow()
    db.commit()
    return _dict(q)


def add(db: Session, topic: str, text: str, why: Optional[str] = None) -> int:
    """Новый вопрос — следующий свободный номер. Этот же номер называем в чате."""
    top = db.execute(select(func.max(OwnerQuestion.num))).scalar() or 0
    q = OwnerQuestion(num=top + 1, asked_at=datetime.utcnow().strftime("%d.%m.%Y"),
                      topic=topic, text=text, why=why, status="open",
                      updated_at=datetime.utcnow())
    db.add(q)
    db.commit()
    return q.num


def mark_done(db: Session, num: int, result: str) -> Optional[Dict]:
    q = db.get(OwnerQuestion, num)
    if q is None:
        return None
    q.status = "done"
    q.result = result
    q.updated_at = datetime.utcnow()
    db.commit()
    return _dict(q)
