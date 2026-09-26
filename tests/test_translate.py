# -*- coding: utf-8 -*-
from app import translate
from app.models import Listing, Translation


class Fake(translate.Provider):
    name = "fake"
    model = "v0"

    def __init__(self):
        self.calls = 0

    def translate(self, texts):
        self.calls += 1
        return [u"UK:" + t for t in texts]


def test_cache_and_chunks(clean_db):
    db = clean_db
    p = Fake()
    a = Listing(source="olx", source_id="1", offer_type="sale", title_pl=u"Mieszkanie 2 pokoje",
                description_pl=u"Opis " * 10, is_active=True, details_fetched=True)
    b = Listing(source="otodom", source_id="2", offer_type="sale", title_pl=u"Mieszkanie 2 pokoje",
                description_pl=u"Opis " * 10, is_active=True, details_fetched=True)
    db.add_all([a, b])
    db.commit()
    res = translate.translate_listing(db, a, p)
    assert res["title_uk"].startswith(u"UK:") and a.description_uk.startswith(u"UK:")
    assert p.calls == 2
    translate.translate_listing(db, b, p)
    assert p.calls == 2                       # тот же текст — из кэша, провайдер не звался
    assert db.query(Translation).count() == 2
    long = u"\n\n".join([u"akapit " * 60] * 8)
    parts = translate._chunks(long)
    assert len(parts) > 1 and all(len(x) <= translate.CHUNK_CHARS + 20 for x in parts)
    st = translate.pending_counts(db)
    assert st["pending_titles"] == 0 and st["done_total"] == 2


def test_cache_is_scoped_to_prompt_version(clean_db, monkeypatch):
    """После правки подсказки старый перевод из кэша отдаваться не должен — иначе
    PROMPT_VERSION ничего не меняет, и кнопка «Перекласти» возвращает прежний текст."""
    db = clean_db
    p = Fake()
    a = Listing(source="olx", source_id="1", offer_type="sale", title_pl=u"Mieszkanie na 1. piętrze", is_active=True)
    db.add(a)
    db.commit()
    translate.translate_listing(db, a, p, with_description=False)
    assert p.calls == 1 and a.translate_version == translate.PROMPT_VERSION
    monkeypatch.setattr(translate, "PROMPT_VERSION", "next")
    translate.translate_listing(db, a, p, force=True, with_description=False)
    assert p.calls == 2 and a.translate_version == "next"                     # кэш прежней версии не подошёл
    translate.translate_listing(db, a, p, force=True, with_description=False)
    assert p.calls == 2                                                       # а в пределах версии — из кэша
    assert db.query(Translation).count() == 2                                 # прежняя строка осталась


def test_queue_takes_freshly_posted_first(clean_db, monkeypatch):
    """Первый прогон вставляет объявления в порядке страниц выдачи, и «свежее по
    first_seen» — это последняя страница, то есть самое старое. Очередь идёт по дате подачи."""
    from datetime import datetime
    db = clean_db
    old = Listing(source="otodom", source_id="1", offer_type="sale", title_pl=u"Stare ogłoszenie", is_active=True,
                  posted_at=datetime(2026, 1, 30), first_seen=datetime(2026, 9, 18, 9, 15))    # вставлено позже
    new = Listing(source="otodom", source_id="2", offer_type="sale", title_pl=u"Dzisiejsze ogłoszenie", is_active=True,
                  posted_at=datetime(2026, 9, 18), first_seen=datetime(2026, 9, 18, 9, 5))
    db.add_all([old, new])
    db.commit()
    monkeypatch.setattr(translate, "get_provider", lambda settings: Fake())
    from app.settings_store import set_setting
    set_setting(db, "translate_enabled", "1")
    translate.translate_pending(db, limit=1)
    db.refresh(old)
    db.refresh(new)
    assert new.title_uk and old.title_uk is None
    # выключатель — про АВТОперевод; кнопка «Перекласти чергу» (manual) работает и при нём
    set_setting(db, "translate_enabled", "0")
    assert translate.translate_pending(db, limit=1) == u"выключено"
    assert translate.translate_pending(db, limit=1, manual=True).startswith(u"заголовков 1")
    db.refresh(old)
    assert old.title_uk


def test_ollama_context_comes_from_settings(monkeypatch):
    """Контекст должен совпадать с уже загруженным экземпляром модели, иначе Ollama
    перезагружает её на каждый запрос (замер: 15-25 с против 0.0 с)."""
    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": u"<think>…</think>Квартира"}}

    monkeypatch.setattr(translate.httpx, "post", lambda url, json=None, timeout=None: sent.append(json) or Resp())
    p = translate.get_provider({"translate_provider": "ollama", "translate_ollama_model": "qwen3.5:9b-q4_K_M",
                                "translate_ollama_num_ctx": "16384"})
    assert p.translate([u"Mieszkanie"]) == [u"Квартира"]
    assert sent[0]["options"]["num_ctx"] == 16384 and sent[0]["model"] == "qwen3.5:9b-q4_K_M"
    assert translate.get_provider({"translate_provider": "ollama"}).num_ctx == 8192            # по умолчанию
    assert translate.get_provider({"translate_provider": "ollama", "translate_ollama_num_ctx": "x"}).num_ctx == 8192


def test_gpu_lease_only_for_our_card(clean_db, monkeypatch):
    """Видеокарта одна на все проекты владельца, очередь ведёт реестр заявок.

    26.09.2026 в 06:06 наши ночные переводы (gemma4:12b) и фоновая проверка
    re-analyzer (qwen3.5:9b с мака) выгружали модели друг друга 6 раз за две
    минуты: две модели по 8-10 ГБ в 16 ГБ не помещаются. Теперь очередь идёт
    под заявкой, и перед каждым объявлением спрашивается реестр.

    Заявка нужна ТОЛЬКО когда считает наша карта: у anthropic/google/deepl
    счёт идёт на чужих машинах, занимать очередь незачем."""
    from app.settings_store import set_setting

    db = clean_db
    db.add(Listing(source="otodom", source_id="1", offer_type="sale",
                   title_pl=u"Mieszkanie", is_active=True))
    db.add(Listing(source="otodom", source_id="2", offer_type="sale",
                   title_pl=u"Kawalerka", is_active=True))
    db.commit()
    monkeypatch.setattr(translate, "get_provider", lambda settings: Fake())
    set_setting(db, "translate_enabled", "1")

    # 1. провайдер не ollama — реестр вообще не трогаем
    set_setting(db, "translate_provider", "deepl")
    assert translate.gpu_for({"translate_provider": "deepl"}) is None

    # 2. ollama — клиент берёт модель ИЗ НАСТРОЕК: реестр по этому списку
    #    решает, что нам можно выгружать, а чужое трогать нельзя никогда
    gpu = translate.gpu_for({"translate_provider": "ollama",
                             "translate_ollama_model": "gemma4:12b-it-q4_K_M"})
    assert gpu is not None and gpu.models == ["gemma4:12b-it-q4_K_M"]
    assert gpu.project == "wroclaw-analyzer"

    # 3. очередь идёт под заявкой, checkpoint — перед КАЖДЫМ объявлением
    seen = {"priority": None, "vram": None, "checks": 0, "released": False}

    class FakeLease:
        def __enter__(self):
            return self

        def checkpoint(self, every=60):
            seen["checks"] += 1

        def __exit__(self, *exc):
            seen["released"] = True
            return False

    class FakeGpu:
        def lease(self, priority=None, note="", vram_gb=None, **kw):
            seen["priority"], seen["vram"] = priority, vram_gb
            return FakeLease()

    monkeypatch.setattr(translate, "gpu_for", lambda settings: FakeGpu())
    out = translate.translate_pending(db, manual=True)
    assert out.startswith(u"заголовков 2")
    assert seen["checks"] == 2
    assert seen["priority"] == 50 and seen["vram"] == translate.GPU_VRAM_GB
    assert seen["released"] is True           # заявка снята: равные приоритеты идут по очереди
