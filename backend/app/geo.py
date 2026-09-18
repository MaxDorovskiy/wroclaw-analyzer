# -*- coding: utf-8 -*-
"""География Вроцлава: 5 старых дзельниц и осиедле (единицы самоуправления).

Osiedle — единица аналитики (медианы, пулы выгодности), дзельница — агрегат и
единственное, что отдаёт OLX. Украинская транскрипция нужна для показа рядом
с оригиналом («Krzyki · Кшики»), а не вместо него.

ВНИМАНИЕ: соответствие осиедле → дзельница проставлено по памяти, среда
разработки не имела доступа к geoportal.wroclaw.pl. Официально осиедле 48
(Fabryczna 14, Krzyki 14, Psie Pole 12, Śródmieście 5, Stare Miasto 3), а в
списке ниже 49 имён — одно из них либо не самостоятельное, либо отнесено не
туда. Сомнительные помечены «?». Сверить: https://geoportal.wroclaw.pl/osiedla/
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
    (u"Przedmieście Oławskie", u"Krzyki", u"Пшедмєсьце Олавське"),   # ? (Krzyki или Śródmieście)
    (u"Tarnogaj", u"Krzyki", u"Тарноґай"),
    (u"Wojszyce", u"Krzyki", u"Войшице"),
    # Fabryczna
    (u"Gajowice", u"Fabryczna", u"Ґайовіце"),                          # ? (Fabryczna или Krzyki)
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
    (u"Kleczków", u"Psie Pole", u"Клечкув"),                            # ? (Psie Pole или Śródmieście)
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
    (u"Zakrzów", u"Psie Pole", u"Закшув"),
]

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
    только «Krzyki» (OLX). Имя из пятёрки дзельниц считается дзельницей, даже
    если такое же осиедле есть («Stare Miasto»): осиедле с тем же именем
    берётся лишь когда другого осиедле в цепочке нет. Найденное осиедле
    сильнее дзельницы источника — у него она бывает просто «Wrocław».
    """
    district = None
    osiedle = None
    same_name_osiedle = None
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
                if d in _DISTRICT_OF:          # «Stare Miasto» — ещё и осиедле
                    same_name_osiedle = same_name_osiedle or d
                continue
            o = match_osiedle(part)
            if o:
                osiedle = osiedle or o
                continue
            unknown.append(part.strip())
    if not osiedle and same_name_osiedle:
        osiedle = same_name_osiedle
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
