# -*- coding: utf-8 -*-
"""География Вроцлава: 5 старых дзельниц и осиедле (единицы самоуправления).

Osiedle — единица аналитики (медианы, пулы выгодности), дзельница — агрегат и
единственное, что отдаёт OLX. Украинская транскрипция нужна для показа рядом
с оригиналом («Krzyki · Кшики»), а не вместо него.

Сверено 18.09.2026:
- список — с официальным (geoportal.wroclaw.pl/poi/rejon/7, 48 осиедле). Был
  лишний «Zakrzów»: это часть Psie Pole-Zawidawie, теперь он в ALIASES;
- осиедле → бывшая дзельница. Геопортал этого не даёт: дзельницы упразднены в
  1991 г. и существуют только как привычные районы. Привязка сверена по
  таблице «Dawna dzielnica» в pl.wikipedia «Podział administracyjny Wrocławia»
  (Fabryczna 14, Krzyki 14, Psie Pole 12, Śródmieście 5, Stare Miasto 3) и по
  самому Otodom: у 9411 объявлений первого прогона (встретились все 48
  осиедле, 70 имён под-районов) дзельница из источника ни разу не разошлась
  с этой таблицей. Три бывших «?» подтверждены: Przedmieście Oławskie —
  Krzyki (569 объявлений), Gajowice — Fabryczna (288), Kleczków — Psie Pole (237).
Незнакомые имена от источников попадают в таблицу unknown_values — по ней
список и правится.
"""
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

DISTRICTS = {
    u"Stare Miasto": u"Старе Място",
    u"Śródmieście": u"Сьрудмєсьце",
    u"Krzyki": u"Кшики",
    u"Fabryczna": u"Фабрична",
    u"Psie Pole": u"Пше Поле",
}

# (osiedle, дзельница, украинская транскрипция)
OSIEDLA = [
    # Stare Miasto
    (u"Przedmieście Świdnickie", u"Stare Miasto", u"Пшедмєсьце Свідніцьке"),
    (u"Stare Miasto", u"Stare Miasto", u"Старе Място"),
    (u"Szczepin", u"Stare Miasto", u"Щепін"),
    # Śródmieście
    (u"Biskupin-Sępolno-Dąbie-Bartoszowice", u"Śródmieście", u"Біскупін-Семпольно-Домбє-Бартошовіце"),
    (u"Nadodrze", u"Śródmieście", u"Надодже"),
    (u"Ołbin", u"Śródmieście", u"Ольбін"),
    (u"Plac Grunwaldzki", u"Śródmieście", u"Плац Ґрунвальдзький"),
    (u"Zacisze-Zalesie-Szczytniki", u"Śródmieście", u"Заціше-Залєсє-Щитнікі"),
    # Krzyki
    (u"Bieńkowice", u"Krzyki", u"Бєньковіце"),
    (u"Borek", u"Krzyki", u"Борек"),
    (u"Brochów", u"Krzyki", u"Брохув"),
    (u"Gaj", u"Krzyki", u"Ґай"),
    (u"Huby", u"Krzyki", u"Губи"),
    (u"Jagodno", u"Krzyki", u"Яґодно"),
    (u"Klecina", u"Krzyki", u"Клєціна"),
    (u"Krzyki-Partynice", u"Krzyki", u"Кшики-Партиніце"),
    (u"Księże", u"Krzyki", u"Ксєнже"),
    (u"Ołtaszyn", u"Krzyki", u"Олташин"),
    (u"Powstańców Śląskich", u"Krzyki", u"Повстаньцув Шльонських"),
    (u"Przedmieście Oławskie", u"Krzyki", u"Пшедмєсьце Олавське"),
    (u"Tarnogaj", u"Krzyki", u"Тарноґай"),
    (u"Wojszyce", u"Krzyki", u"Войшице"),
    # Fabryczna
    (u"Gajowice", u"Fabryczna", u"Ґайовіце"),
    (u"Gądów-Popowice Płd.", u"Fabryczna", u"Ґондув-Поповіце Пд."),
    (u"Grabiszyn-Grabiszynek", u"Fabryczna", u"Ґрабішин-Ґрабішинек"),
    (u"Jerzmanowo-Jarnołtów-Strachowice-Osiniec", u"Fabryczna", u"Єжманово-Ярнолтув-Страховіце-Осінєц"),
    (u"Kuźniki", u"Fabryczna", u"Кузьнікі"),
    (u"Leśnica", u"Fabryczna", u"Лєсьніца"),
    (u"Maślice", u"Fabryczna", u"Масьліце"),
    (u"Muchobór Mały", u"Fabryczna", u"Мухобур Мали"),
    (u"Muchobór Wielki", u"Fabryczna", u"Мухобур Вєлькі"),
    (u"Nowy Dwór", u"Fabryczna", u"Нови Двур"),
    (u"Oporów", u"Fabryczna", u"Опорув"),
    (u"Pilczyce-Kozanów-Popowice Płn.", u"Fabryczna", u"Пільчице-Козанув-Поповіце Пн."),
    (u"Pracze Odrzańskie", u"Fabryczna", u"Праче Оджаньське"),
    (u"Żerniki", u"Fabryczna", u"Жернікі"),
    # Psie Pole
    (u"Karłowice-Różanka", u"Psie Pole", u"Карловіце-Ружанка"),
    (u"Kleczków", u"Psie Pole", u"Клечкув"),
    (u"Kowale", u"Psie Pole", u"Ковалє"),
    (u"Lipa Piotrowska", u"Psie Pole", u"Ліпа Пьотровська"),
    (u"Osobowice-Rędzin", u"Psie Pole", u"Особовіце-Рендзін"),
    (u"Pawłowice", u"Psie Pole", u"Павловіце"),
    (u"Polanowice-Poświętne-Ligota", u"Psie Pole", u"Поляновіце-Посьвєнтне-Ліґота"),
    (u"Psie Pole-Zawidawie", u"Psie Pole", u"Пше Поле-Завідавє"),
    (u"Sołtysowice", u"Psie Pole", u"Солтисовіце"),
    (u"Strachocin-Swojczyce-Wojnów", u"Psie Pole", u"Страхоцін-Свойчице-Войнув"),
    (u"Świniary", u"Psie Pole", u"Свіняри"),
    (u"Widawa", u"Psie Pole", u"Відава"),
]

# Под-район с именем дзельницы (Otodom: «… | Krzyki | Krzyki») — часть составного
# осиедле. В первом прогоне так шли 310 объявлений «Krzyki», 62 «Psie Pole» и
# 219 «Stare Miasto» из 9411 — первые два вида оставались без осиедле.
SAME_NAME_PART = {
    u"Stare Miasto": u"Stare Miasto",
    u"Krzyki": u"Krzyki-Partynice",
    u"Psie Pole": u"Psie Pole-Zawidawie",
}

# Части составных осиедле и обиходные названия -> официальное осиедле.
# Источники пишут «Popowice», «Sępolno», «Partynice», «Stabłowice» — это
# части, а не осиедле; без этой таблицы они шли бы в «незнакомые».
ALIASES = {
    u"biskupin": u"Biskupin-Sępolno-Dąbie-Bartoszowice",
    u"sepolno": u"Biskupin-Sępolno-Dąbie-Bartoszowice",
    u"dabie": u"Biskupin-Sępolno-Dąbie-Bartoszowice",
    u"bartoszowice": u"Biskupin-Sępolno-Dąbie-Bartoszowice",
    u"zacisze": u"Zacisze-Zalesie-Szczytniki",
    u"zalesie": u"Zacisze-Zalesie-Szczytniki",
    u"szczytniki": u"Zacisze-Zalesie-Szczytniki",
    u"partynice": u"Krzyki-Partynice",
    u"gadow": u"Gądów-Popowice Płd.",
    u"gadow maly": u"Gądów-Popowice Płd.",
    u"popowice": u"Pilczyce-Kozanów-Popowice Płn.",
    u"popowice poludniowe": u"Gądów-Popowice Płd.",
    u"popowice pld": u"Gądów-Popowice Płd.",
    u"popowice polnocne": u"Pilczyce-Kozanów-Popowice Płn.",
    u"popowice pln": u"Pilczyce-Kozanów-Popowice Płn.",
    u"pilczyce": u"Pilczyce-Kozanów-Popowice Płn.",
    u"kozanow": u"Pilczyce-Kozanów-Popowice Płn.",
    u"grabiszyn": u"Grabiszyn-Grabiszynek",
    u"grabiszynek": u"Grabiszyn-Grabiszynek",
    u"jerzmanowo": u"Jerzmanowo-Jarnołtów-Strachowice-Osiniec",
    u"jarnoltow": u"Jerzmanowo-Jarnołtów-Strachowice-Osiniec",
    u"strachowice": u"Jerzmanowo-Jarnołtów-Strachowice-Osiniec",
    u"osiniec": u"Jerzmanowo-Jarnołtów-Strachowice-Osiniec",
    u"stablowice": u"Leśnica",
    u"zlotniki": u"Leśnica",
    u"marszowice": u"Leśnica",
    u"ratyn": u"Leśnica",
    u"karlowice": u"Karłowice-Różanka",
    u"rozanka": u"Karłowice-Różanka",
    u"osobowice": u"Osobowice-Rędzin",
    u"redzin": u"Osobowice-Rędzin",
    u"polanowice": u"Polanowice-Poświętne-Ligota",
    u"poswietne": u"Polanowice-Poświętne-Ligota",
    u"ligota": u"Polanowice-Poświętne-Ligota",
    u"zawidawie": u"Psie Pole-Zawidawie",
    u"strachocin": u"Strachocin-Swojczyce-Wojnów",
    u"swojczyce": u"Strachocin-Swojczyce-Wojnów",
    u"wojnow": u"Strachocin-Swojczyce-Wojnów",
    u"centrum": u"Stare Miasto",
    u"nowe zerniki": u"Żerniki",
    u"rynek": u"Stare Miasto",
    # Две строки ниже НЕ сверены (поиск по адресам геопортала 18.09.2026 не отвечал).
    # На данные не влияют: ни Otodom (70 имён под-районов), ни OLX таких имён не
    # присылают; объявление с Kępa Mieszczańska Otodom отнёс к Nadodrze.
    u"ostrow tumski": u"Stare Miasto",
    u"kepa mieszczanska": u"Stare Miasto",
    u"przedmiescie swidnickie": u"Przedmieście Świdnickie",
    u"przedmiescie olawskie": u"Przedmieście Oławskie",
    u"plac grunwaldzki": u"Plac Grunwaldzki",
    u"pl grunwaldzki": u"Plac Grunwaldzki",
    u"powstancow slaskich": u"Powstańców Śląskich",
    u"os powstancow slaskich": u"Powstańców Śląskich",
    u"gadow popowice pld": u"Gądów-Popowice Płd.",
    u"pilczyce kozanow popowice pln": u"Pilczyce-Kozanów-Popowice Płn.",
    # части осиедле по столбцу «jednostki przestrzenne» той же таблицы (см. шапку)
    u"zakrzow": u"Psie Pole-Zawidawie",          # был ошибочно отдельным осиедле
    u"zgorzelisko": u"Psie Pole-Zawidawie",
    u"klokoczyce": u"Psie Pole-Zawidawie",
    u"mokra": u"Leśnica",                        # встретилась в первом прогоне
    u"pustki": u"Leśnica",
    u"zar": u"Leśnica",
    u"janowek": u"Pracze Odrzańskie",
    u"nowa karczma": u"Pracze Odrzańskie",
    u"glinianki": u"Huby",
    u"ksieze male": u"Księże",
    u"ksieze wielkie": u"Księże",
    u"swiatniki": u"Księże",
    u"opatowice": u"Księże",
    u"bierdzany": u"Księże",
    u"nowy dom": u"Księże",
    u"mirowiec": u"Karłowice-Różanka",
    u"polanka": u"Karłowice-Różanka",
    u"popiele": u"Strachocin-Swojczyce-Wojnów",
    u"dworek": u"Powstańców Śląskich",
    u"poludnie": u"Powstańców Śląskich",
    u"nowe miasto": u"Stare Miasto",
    u"przedmiescie mikolajskie": u"Szczepin",
}


def norm(s: Optional[str]) -> str:
    """Без диакритики, регистра и пунктуации: «Gądów-Popowice Płd.» -> «gadow popowice pld»."""
    if not s:
        return u""
    s = unicodedata.normalize("NFKD", s)
    s = u"".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace(u"ł", u"l").replace(u"Ł", u"L")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


_OSIEDLE_BY_NORM: Dict[str, str] = {}
_DISTRICT_OF: Dict[str, str] = {}
_UK_OF: Dict[str, str] = {}
for _name, _dist, _uk in OSIEDLA:
    _OSIEDLE_BY_NORM[norm(_name)] = _name
    _DISTRICT_OF[_name] = _dist
    _UK_OF[_name] = _uk
for _alias, _name in ALIASES.items():
    _OSIEDLE_BY_NORM.setdefault(norm(_alias), _name)
_DISTRICT_BY_NORM = {norm(k): k for k in DISTRICTS}


def match_osiedle(name: Optional[str]) -> Optional[str]:
    n = norm(name)
    if not n:
        return None
    if n in _OSIEDLE_BY_NORM:
        return _OSIEDLE_BY_NORM[n]
    # «osiedle Gaj», «Wrocław-Gaj», «Gaj, Krzyki»
    for prefix in (u"osiedle ", u"os ", u"wroclaw "):
        if n.startswith(prefix) and n[len(prefix):] in _OSIEDLE_BY_NORM:
            return _OSIEDLE_BY_NORM[n[len(prefix):]]
    return None


def match_district(name: Optional[str]) -> Optional[str]:
    n = norm(name)
    if not n:
        return None
    if n in _DISTRICT_BY_NORM:
        return _DISTRICT_BY_NORM[n]
    for prefix in (u"wroclaw ", u"dzielnica "):
        if n.startswith(prefix) and n[len(prefix):] in _DISTRICT_BY_NORM:
            return _DISTRICT_BY_NORM[n[len(prefix):]]
    return None


def district_of(osiedle: Optional[str]) -> Optional[str]:
    return _DISTRICT_OF.get(osiedle) if osiedle else None


def osiedle_uk(osiedle: Optional[str]) -> Optional[str]:
    return _UK_OF.get(osiedle) if osiedle else None


def district_uk(district: Optional[str]) -> Optional[str]:
    return DISTRICTS.get(district) if district else None


def resolve(names: Iterable[str]) -> Tuple[Optional[str], Optional[str], List[str]]:
    """(дзельница, осиедле, незнакомые имена) по всем именам мест от источника.

    Источник даёт цепочку «Dolnośląskie / Wrocław / Krzyki / Gaj» (Otodom) или
    только «Krzyki» (OLX). Имя из пятёрки дзельниц — это дзельница. Осиедле из
    него получается, только когда имя стоит в цепочке ВТОРОЙ раз: тогда это
    уже под-район (Otodom: «… | Krzyki | Krzyki», «… | Stare Miasto | Stare
    Miasto») — часть осиедле из SAME_NAME_PART. Одиночное «Stare Miasto» (так
    пишет OLX, у него только дзельница) осиедле НЕ даёт: в дзельнице их три,
    и раньше все объявления OLX из Szczepin и Przedmieście Świdnickie
    записывались в осиедле Stare Miasto. Найденное осиедле сильнее дзельницы
    источника — у него она бывает просто «Wrocław».
    """
    district = None
    osiedle = None
    hits: Dict[str, int] = {}
    unknown = []
    skip = {u"", u"wroclaw", u"dolnoslaskie", u"polska", u"dolnoslaskie wroclaw",
            u"miasto wroclaw", u"wroclaw dolnoslaskie", u"powiat wroclaw",
            u"m wroclaw"}
    for raw in names or []:
        if not raw:
            continue
        # «Wrocław, Krzyki, Gaj» — источники любят склеивать
        parts = [p for p in re.split(r"[,/|]", raw) if p.strip()]
        for part in parts:
            n = norm(part)
            if n in skip:
                continue
            d = match_district(part)
            if d:
                district = district or d
                hits[d] = hits.get(d, 0) + 1
                continue
            o = match_osiedle(part)
            if o:
                osiedle = osiedle or o
                continue
            unknown.append(part.strip())
    if not osiedle and district and hits.get(district, 0) >= 2:
        osiedle = SAME_NAME_PART.get(district)
    if osiedle:
        district = district_of(osiedle) or district
    return district, osiedle, unknown


def all_geo() -> List[dict]:
    """Для выпадающих списков: дзельницы с их осиедле."""
    out = []
    for d, uk in DISTRICTS.items():
        out.append({
            "name": d, "name_uk": uk,
            "osiedla": [{"name": n, "name_uk": u} for n, dd, u in OSIEDLA if dd == d],
        })
    return out
