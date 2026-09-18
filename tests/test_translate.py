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
