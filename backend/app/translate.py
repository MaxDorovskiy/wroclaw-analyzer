# -*- coding: utf-8 -*-
"""Перевод PL -> UK заголовков и описаний.

Провайдер — настройка (`translate_provider`): локальная Ollama (по умолчанию,
бесплатно), Anthropic API, Google Cloud Translation, DeepL или «выключено».
Все провайдеры прячутся за одним интерфейсом, результат ложится в кэш
`translations` по SHA-1 текста — зеркала Otodom<->OLX и повторные подачи
переводятся один раз.

Подсказка закрепляет термины (см. GLOSSARY): без неё модель на «stan
deweloperski» отвечает «стан розробника». Меняли подсказку — поднимите
PROMPT_VERSION: старые переводы станут «устаревшими» в отчёте, а не молча
несравнимыми.

Оригинал хранится всегда, перевод — производная.
"""
import hashlib
import html
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Listing, Translation
from .settings_store import get_settings

log = logging.getLogger("translate")

# "2" (18.09.2026): на первых 22 живых переводах gemma4:12b этаж оставался по-польски
# во всех примерах («на 1. piętrze», «3 piętro») — строку словаря про piętro модель
# читала как «термин сохранять»; город шёл латиницей в польском падеже («у Wrocławiu»),
# «spacerkiem» — «Прохідцем», слово osiedle — гибридом «осиедle». Правки проверены на
# тех же фразах дважды подряд: «на 1-му поверсі», «3-й поверх», «у Вроцлаві», «Пішки»,
# собственные имена (улицы, осиедле, инвестиции, магазины) остаются латиницей.
# "3" (19.09.2026): «osiedle» в ТЕКСТЕ объявления — это не административное осиедле,
# а жилой комплекс («strzeżone osiedle» = охраняемый ЖК), и модель всё равно писала
# «осидле» (172 заголовка из 288 с этим словом). Переводим по смыслу: «житловий
# комплекс» / «у мікрорайоні Gaj», а «осиедле» остаётся только названием единицы
# в интерфейсе (оно из geo.py, не от модели). «BEZCZYNSZOWE» давало
# «БЕЗКОМУНІТАЛЬНИ» — теперь строка словаря в обоих регистрах.
PROMPT_VERSION = "3"
GLOSSARY = u"""stan deweloperski -> стан від забудовника (без оздоблення)
do wykończenia -> під оздоблення
do remontu -> під ремонт
do odświeżenia -> потребує косметичного оновлення
po remoncie -> після ремонту
czynsz (administracyjny) -> експлуатаційний платіж (czynsz)
kaucja -> застава
rynek pierwotny / wtórny -> первинний / вторинний ринок
kamienica -> кам'яниця (старий будинок)
blok / wielka płyta -> блочний (панельний) будинок
apartamentowiec -> апартаментний будинок (новобудова)
parter -> партер (перший поверх)
piętro, na 1. piętrze, na II piętrze, 3 piętro -> поверх, на 1-му поверсі, на II поверсі, 3-й поверх (слово «piętro» завжди перекладай; номер не змінюй — це польська нумерація, 1 piętro = наш 2-й поверх)
Wrocław, we Wrocławiu -> Вроцлав, у Вроцлаві (місто — українською; назви вулиць і мікрорайонів — латиницею)
spacerem, spacerkiem -> пішки
pokój / pokoje -> кімната / кімнати
kawalerka -> однокімнатна (студія)
osiedle (у тексті оголошення) -> житловий комплекс; strzeżone osiedle -> охоронюваний житловий комплекс; na osiedlu Gaj -> у мікрорайоні Gaj (у тексті це житловий масив, а не адміністративна одиниця — слова «осиедле» в перекладі не вживай)
bezczynszowe -> без експлуатаційного платежу
BEZCZYNSZOWE (великими літерами) -> БЕЗ ЕКСПЛУАТАЦІЙНОГО ПЛАТЕЖУ
czynsz najmu -> орендна плата
pilne, PILNE -> терміново, ТЕРМІНОВО
okazja, OKAZJA -> вигідна пропозиція, ВИГІДНА ПРОПОЗИЦІЯ
własność / spółdzielcze własnościowe -> повна власність / кооперативне право
miejsce postojowe -> паркомісце
komórka lokatorska -> комора (підсобка)
winda -> ліфт
ogrzewanie miejskie -> центральне опалення
"""
SYSTEM_PROMPT = (
    u"Ти перекладач оголошень про нерухомість з польської на українську. "
    u"Перекладай точно і природно, зберігай числа, адреси, назви вулиць і осиедле "
    u"(латиницею, як в оригіналі), ціни та одиниці. Латиницею залишай ЛИШЕ власні назви: "
    u"вулиць, мікрорайонів (Gaj, Krzyki), інвестицій, фірм, магазинів; усі інші польські слова "
    u"перекладай — зокрема piętro/piętrze, etap, blok, osiedle. Не додавай нічого від себе, "
    u"не скорочуй, не коментуй. Форматування (абзаци, списки) і регістр зберігай: "
    u"ВЕЛИКІ літери лишаються великими. "
    u"Відповідай ЛИШЕ перекладом, без вступу.\nСловник термінів:\n" + GLOSSARY
)
CHUNK_CHARS = 2500
_state = {"running": False, "last_error": None, "lock": threading.Lock()}


def _hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text.strip()).encode("utf-8")).hexdigest()


# ---------- провайдеры ----------
class Provider:
    name = "none"
    model = ""

    def translate(self, texts: List[str]) -> List[str]:
        raise NotImplementedError


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, url: str, model: str, num_ctx: int = 8192):
        self.url = url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx          # см. translate_ollama_num_ctx в config.py

    def translate(self, texts: List[str]) -> List[str]:
        out = []
        for t in texts:
            r = httpx.post(self.url + "/api/chat", json={
                "model": self.model, "stream": False,
                # думающие модели (qwen3.x) без этого пишут рассуждения минутами
                "think": False,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": t}],
                "options": {"temperature": 0.1, "num_ctx": self.num_ctx},
            }, timeout=300)
            r.raise_for_status()
            msg = (r.json().get("message") or {}).get("content") or ""
            out.append(_strip_think(msg).strip())
        return out


def _strip_think(s: str) -> str:
    return re.sub(r"<think>.*?</think>", "", s, flags=re.S)


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key or None)
        self.model = model
        self._anthropic = anthropic

    def _one(self, text: str) -> str:
        kwargs = dict(model=self.model, max_tokens=8000, system=SYSTEM_PROMPT,
                      messages=[{"role": "user", "content": text}])
        try:
            # серверный фолбэк на отказ: перевод объявления в отказ упирается
            # редко, но при отказе запрос доедет на другой модели той же семьи
            resp = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        except TypeError:
            resp = self.client.messages.create(**kwargs)
        if getattr(resp, "stop_reason", None) == "refusal":
            raise RuntimeError(u"модель отказалась переводить текст")
        return u"".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()

    def translate(self, texts: List[str]) -> List[str]:
        return [self._one(t) for t in texts]


class GoogleProvider(Provider):
    name = "google"
    model = "nmt-v2"

    def __init__(self, api_key: str):
        self.key = api_key

    def translate(self, texts: List[str]) -> List[str]:
        r = httpx.post("https://translation.googleapis.com/language/translate/v2",
                       params={"key": self.key},
                       json={"q": texts, "source": "pl", "target": "uk", "format": "text"},
                       timeout=60)
        r.raise_for_status()
        return [html.unescape(t["translatedText"]) for t in r.json()["data"]["translations"]]


class DeepLProvider(Provider):
    name = "deepl"
    model = "deepl"

    def __init__(self, api_key: str):
        self.key = api_key
        self.url = ("https://api-free.deepl.com/v2/translate" if api_key.endswith(":fx")
                    else "https://api.deepl.com/v2/translate")

    def translate(self, texts: List[str]) -> List[str]:
        r = httpx.post(self.url, headers={"Authorization": "DeepL-Auth-Key " + self.key},
                       json={"text": texts, "source_lang": "PL", "target_lang": "UK"}, timeout=60)
        r.raise_for_status()
        return [t["text"] for t in r.json()["translations"]]


def get_provider(settings: Dict[str, str]) -> Optional[Provider]:
    name = (settings.get("translate_provider") or "none").strip()
    if name == "ollama":
        try:
            num_ctx = int(float(settings.get("translate_ollama_num_ctx") or 8192))
        except ValueError:
            num_ctx = 8192
        return OllamaProvider(settings.get("translate_ollama_url") or "http://127.0.0.1:11434",
                              settings.get("translate_ollama_model") or "gemma3:12b",
                              max(2048, num_ctx))
    if name == "anthropic":
        return AnthropicProvider(settings.get("translate_anthropic_key") or "",
                                 settings.get("translate_anthropic_model") or "claude-opus-5")
    if name == "google" and settings.get("translate_google_key"):
        return GoogleProvider(settings["translate_google_key"])
    if name == "deepl" and settings.get("translate_deepl_key"):
        return DeepLProvider(settings["translate_deepl_key"])
    return None


# ---------- кэш и разбиение ----------
def _chunks(text: str) -> List[str]:
    """Длинные описания режем по абзацам до CHUNK_CHARS, чтобы не упираться
    в окно локальной модели и не терять хвост."""
    if len(text) <= CHUNK_CHARS:
        return [text]
    out, cur = [], u""
    for para in re.split(r"(\n\s*\n)", text):
        if len(cur) + len(para) > CHUNK_CHARS and cur.strip():
            out.append(cur)
            cur = u""
        cur += para
    if cur.strip():
        out.append(cur)
    return out


def translate_text(db: Session, text: Optional[str], provider: Provider) -> Optional[str]:
    if not text or not text.strip():
        return None
    h = _hash(text)
    # кэш — в пределах версии подсказки: иначе после её правки старый перевод отдавался
    # бы вечно, даже по кнопке «Перекласти» в карточке (строки прежних версий остаются)
    cached = db.execute(select(Translation.text).where(Translation.src_hash == h,
                                                       Translation.dst_lang == "uk",
                                                       Translation.prompt_version == PROMPT_VERSION)).first()
    if cached:
        return cached[0]
    parts = _chunks(text)
    translated = provider.translate(parts)
    result = u"\n\n".join(t for t in translated if t is not None).strip()
    if not result:
        return None
    db.add(Translation(src_hash=h, dst_lang="uk", provider=provider.name, model=provider.model,
                       prompt_version=PROMPT_VERSION, src_len=len(text), text=result))
    return result


def translate_listing(db: Session, row: Listing, provider: Provider, force: bool = False,
                      with_description: bool = True) -> Dict:
    cached_before = db.execute(select(func.count()).select_from(Translation)).scalar()
    if force or not row.title_uk:
        row.title_uk = translate_text(db, row.title_pl, provider)
    if with_description and (force or not row.description_uk) and row.description_pl:
        row.description_uk = translate_text(db, row.description_pl, provider)
    row.translated_at = datetime.utcnow()
    row.translate_provider = "%s:%s" % (provider.name, provider.model)
    row.translate_version = PROMPT_VERSION
    db.commit()
    cached_after = db.execute(select(func.count()).select_from(Translation)).scalar()
    return {"title_uk": row.title_uk, "description_uk": row.description_uk,
            "provider": row.translate_provider, "cached": cached_after == cached_before}


def _done_today(db: Session) -> int:
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(select(func.count()).select_from(Listing).where(
        Listing.translated_at >= since, Listing.description_uk.isnot(None))).scalar() or 0


def pending_counts(db: Session) -> Dict[str, int]:
    base = (Listing.is_active.is_(True), Listing.title_pl.isnot(None))
    titles = db.execute(select(func.count()).select_from(Listing).where(*base, Listing.title_uk.is_(None))).scalar() or 0
    descs = db.execute(select(func.count()).select_from(Listing).where(
        *base, Listing.description_pl.isnot(None), Listing.description_uk.is_(None))).scalar() or 0
    done = db.execute(select(func.count()).select_from(Listing).where(Listing.title_uk.isnot(None))).scalar() or 0
    return {"pending_titles": titles, "pending_descriptions": descs, "done_total": done,
            "done_today": _done_today(db)}


def translate_pending(db: Session, limit: Optional[int] = None,
                      stop_check: Optional[Callable[[], bool]] = None, manual: bool = False) -> str:
    """Очередь: заголовки всех новых (короткие), потом описания в пределах
    суточного потолка, самые новые первыми. Три ошибки подряд — стоп: если
    Ollama выключена, нечего долбить её сотней запросов.

    translate_enabled выключает АВТОперевод после прогона. Кнопка «Перекласти
    чергу» и translate_backlog.py (manual=True) — явное действие владельца: при
    выключенном автопереводе кнопка отвечала «запущено», а в логе было «выключено»."""
    settings = get_settings(db)
    if not manual and settings.get("translate_enabled") != "1":
        return u"выключено"
    provider = get_provider(settings)
    if provider is None:
        return u"провайдер не настроен"
    with _state["lock"]:
        if _state["running"]:
            return u"уже идёт"
        _state["running"] = True
    try:
        cap = int(float(settings.get("translate_daily_cap") or 800))
    except ValueError:
        cap = 800
    done_t = done_d = 0
    errors = 0
    try:
        # свежие — по дате подачи (см. тот же довод в scraper._scrape_details): по first_seen
        # первая очередь из 20 целиком ушла на одну инвестицию с последней страницы выдачи
        fresh = (Listing.is_representative.desc(), Listing.posted_at.desc(), Listing.first_seen.desc())
        q = (db.query(Listing).filter(Listing.is_active.is_(True), Listing.title_pl.isnot(None),
                                      Listing.title_uk.is_(None))
             .order_by(*fresh).limit(limit or 3000))
        for row in q.all():
            if stop_check and stop_check():
                break
            try:
                translate_listing(db, row, provider, with_description=False)
                done_t += 1
                errors = 0
            except Exception as e:  # noqa: BLE001
                db.rollback()
                errors += 1
                _state["last_error"] = str(e)[:300]
                log.warning("перевод заголовка %s: %s", row.id, e)
                if errors >= 3:
                    return u"заголовков %d, остановлено после 3 ошибок: %s" % (done_t, e)
        budget = max(0, cap - _done_today(db))
        if limit:
            budget = min(budget, limit)
        q = (db.query(Listing).filter(Listing.is_active.is_(True), Listing.description_pl.isnot(None),
                                      Listing.description_uk.is_(None))
             .order_by(*fresh).limit(budget))
        for row in q.all():
            if stop_check and stop_check():
                break
            try:
                translate_listing(db, row, provider)
                done_d += 1
                errors = 0
            except Exception as e:  # noqa: BLE001
                db.rollback()
                errors += 1
                _state["last_error"] = str(e)[:300]
                log.warning("перевод описания %s: %s", row.id, e)
                if errors >= 3:
                    return u"заголовков %d, описаний %d, остановлено после 3 ошибок: %s" % (done_t, done_d, e)
        _state["last_error"] = None
        return u"заголовков %d, описаний %d (потолок %d/сутки)" % (done_t, done_d, cap)
    finally:
        _state["running"] = False


def status(db: Session) -> Dict:
    settings = get_settings(db)
    p = get_provider(settings)
    out = pending_counts(db)
    out.update({"provider": settings.get("translate_provider"),
                "model": p.model if p else None,
                "enabled": settings.get("translate_enabled") == "1",
                "running": _state["running"], "last_error": _state["last_error"],
                "prompt_version": PROMPT_VERSION})
    return out
