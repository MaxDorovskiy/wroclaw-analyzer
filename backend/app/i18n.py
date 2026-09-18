# -*- coding: utf-8 -*-
"""Словарь структурных значений: канонический ключ -> (польская подпись, украинская).

Структурные поля переводятся ДЕТЕРМИНИРОВАННО, без модели: их конечное число,
а модель на «stan deweloperski» иногда отвечает «стан розробника». Значения,
которых тут нет, показываются по-польски и попадают в unknown_values —
по этой таблице словарь и пополняется.
"""
from typing import Dict, Optional, Tuple

Pair = Tuple[str, str]

MARKET: Dict[str, Pair] = {
    "primary": (u"pierwotny", u"первинний (від забудовника)"),
    "secondary": (u"wtórny", u"вторинний"),
}

BUILDING_TYPE: Dict[str, Pair] = {
    "block": (u"blok", u"блочний / панельний будинок"),
    "tenement": (u"kamienica", u"кам'яниця (старий будинок)"),
    "apartment": (u"apartamentowiec", u"апартаментний будинок (новобудова)"),
    "house": (u"dom wolnostojący", u"окремий будинок"),
    "infill": (u"plomba", u"«пломба» (вбудований у забудову)"),
    "ribbon": (u"szeregowiec", u"таунхаус (рядна забудова)"),
    "loft": (u"loft", u"лофт"),
    "other": (u"pozostałe", u"інше"),
}

BUILDING_MATERIAL: Dict[str, Pair] = {
    "brick": (u"cegła", u"цегла"),
    "concrete_plate": (u"wielka płyta", u"панель (велика плита)"),
    "silikat": (u"silikat", u"силікатна цегла"),
    "breezeblock": (u"pustak", u"пустотілий блок"),
    "cellular_concrete": (u"beton komórkowy", u"газобетон"),
    "reinforced_concrete": (u"żelbet", u"залізобетон"),
    "concrete": (u"beton", u"бетон"),
    "wood": (u"drewno", u"дерево"),
    "hydroton": (u"keramzyt", u"керамзитобетон"),
    "other": (u"inne", u"інше"),
}

CONSTRUCTION_STATUS: Dict[str, Pair] = {
    "ready_to_use": (u"do zamieszkania", u"готова до заселення"),
    "to_completion": (u"do wykończenia", u"під оздоблення (стан від забудовника)"),
    "to_renovation": (u"do remontu", u"потребує ремонту"),
}

CONDITION: Dict[str, Pair] = {
    "developer_bare": (u"stan deweloperski", u"стан від забудовника (без оздоблення)"),
    "to_renovate": (u"do remontu", u"під ремонт"),
    "to_refresh": (u"do odświeżenia", u"потребує косметичного оновлення"),
    "renovated": (u"po remoncie / wykończone", u"з ремонтом, готова до заселення"),
    "unknown": (u"—", u"невідомо"),
}

OWNERSHIP: Dict[str, Pair] = {
    "full_ownership": (u"pełna własność", u"повна власність"),
    "limited_ownership": (u"spółdzielcze własnościowe", u"кооперативне право власності (spółdzielcze własnościowe)"),
    "co_operative": (u"spółdzielcze lokatorskie", u"кооперативне право користування"),
    "share": (u"udział", u"частка"),
    "usufruct": (u"użytkowanie wieczyste", u"довічне користування землею"),
}

HEATING: Dict[str, Pair] = {
    "urban": (u"miejskie", u"центральне (міське)"),
    "gas": (u"gazowe", u"газове"),
    "electric": (u"elektryczne", u"електричне"),
    "boiler_room": (u"kotłownia", u"котельня будинку"),
    "tiled_stove": (u"piece kaflowe", u"кахляні печі"),
    "heat_pump": (u"pompa ciepła", u"тепловий насос"),
    "coal": (u"węglowe", u"вугільне"),
    "other": (u"inne", u"інше"),
}

WINDOWS: Dict[str, Pair] = {
    "plastic": (u"plastikowe", u"металопластикові"),
    "wooden": (u"drewniane", u"дерев'яні"),
    "aluminium": (u"aluminiowe", u"алюмінієві"),
}

SELLER_TYPE: Dict[str, Pair] = {
    "private": (u"osoba prywatna", u"власник"),
    "agency": (u"biuro nieruchomości", u"агентство"),
    "developer": (u"deweloper", u"забудовник"),
}

EXTRAS: Dict[str, Pair] = {
    "balcony": (u"balkon", u"балкон"),
    "terrace": (u"taras", u"тераса"),
    "garden": (u"ogródek", u"садок"),
    "garage": (u"garaż/miejsce parkingowe", u"гараж / паркомісце"),
    "lift": (u"winda", u"ліфт"),
    "basement": (u"piwnica", u"підвал / комора"),
    "usable_room": (u"pom. użytkowe", u"підсобне приміщення"),
    "separate_kitchen": (u"oddzielna kuchnia", u"окрема кухня"),
    "two_storey": (u"dwupoziomowe", u"дворівнева"),
    "air_conditioning": (u"klimatyzacja", u"кондиціонер"),
    "attic": (u"strych", u"горище"),
    "furniture": (u"meble", u"меблі"),
    "dishwasher": (u"zmywarka", u"посудомийна машина"),
    "fridge": (u"lodówka", u"холодильник"),
    "oven": (u"piekarnik", u"духовка"),
    "stove": (u"kuchenka", u"плита"),
    "washing_machine": (u"pralka", u"пральна машина"),
    "tv": (u"telewizor", u"телевізор"),
    "internet": (u"internet", u"інтернет"),
    "cable_television": (u"telewizja kablowa", u"кабельне ТБ"),
    "phone": (u"telefon", u"телефон"),
    "electricity": (u"prąd", u"електрика"),
    "water": (u"woda", u"вода"),
    "sewage": (u"kanalizacja", u"каналізація"),
    "gas": (u"gaz", u"газ"),
    "anti_burglary_door": (u"drzwi antywłamaniowe", u"броньовані двері"),
    "entryphone": (u"domofon/wideofon", u"домофон"),
    "monitoring": (u"monitoring/ochrona", u"відеонагляд / охорона"),
    "closed_area": (u"teren zamknięty", u"закрита територія"),
    "alarm": (u"system alarmowy", u"сигналізація"),
    "roller_shutters": (u"rolety antywłamaniowe", u"захисні ролети"),
    "non_smokers_only": (u"tylko dla niepalących", u"лише для некурців"),
    "students_ok": (u"dla studentów", u"можна студентам"),
    "pets_ok": (u"zwierzęta", u"можна з тваринами"),
}

# уровни, на которых нашлась база сравнения — для подсказок
LEVELS: Dict[str, Pair] = {
    "osiedle_rooms": (u"osiedle + pokoje", u"осиедле, ті ж кімнати"),
    "osiedle": (u"osiedle", u"осиедле, всі кімнати"),
    "district_rooms": (u"dzielnica + pokoje", u"дзельниця, ті ж кімнати"),
    "district": (u"dzielnica", u"дзельниця, всі кімнати"),
    "city_rooms": (u"miasto + pokoje", u"місто, ті ж кімнати"),
    "city": (u"miasto", u"місто"),
}

# ключи характеристик Otodom/OLX -> подписи для таблицы в карточке
CHARACTERISTIC_LABELS: Dict[str, Pair] = {
    "price": (u"Cena", u"Ціна"),
    "price_per_m": (u"Cena za m²", u"Ціна за м²"),
    "m": (u"Powierzchnia", u"Площа"),
    "area": (u"Powierzchnia", u"Площа"),
    "rooms_num": (u"Liczba pokoi", u"Кількість кімнат"),
    "rooms": (u"Liczba pokoi", u"Кількість кімнат"),
    "floor_no": (u"Piętro", u"Поверх (польська нумерація)"),
    "floor_select": (u"Piętro", u"Поверх (польська нумерація)"),
    "building_floors_num": (u"Liczba pięter", u"Поверхів у будинку"),
    "market": (u"Rynek", u"Ринок"),
    "build_year": (u"Rok budowy", u"Рік будівництва"),
    "building_type": (u"Rodzaj zabudowy", u"Тип будинку"),
    "builttype": (u"Rodzaj zabudowy", u"Тип будинку"),
    "building_material": (u"Materiał budynku", u"Матеріал будинку"),
    "construction_status": (u"Stan wykończenia", u"Стан оздоблення"),
    "windows_type": (u"Okna", u"Вікна"),
    "heating": (u"Ogrzewanie", u"Опалення"),
    "rent": (u"Czynsz", u"Експлуатаційний платіж (czynsz)"),
    "lift": (u"Winda", u"Ліфт"),
    "building_ownership": (u"Forma własności", u"Форма власності"),
    "extras_types": (u"Informacje dodatkowe", u"Додатково"),
    "security_types": (u"Zabezpieczenia", u"Безпека"),
    "media_types": (u"Media", u"Комунікації"),
    "equipment_types": (u"Wyposażenie", u"Обладнання"),
    "furniture": (u"Umeblowane", u"Мебльована"),
    "free_from": (u"Dostępne od", u"Вільна з"),
    "deposit": (u"Kaucja", u"Застава"),
    "remote_services": (u"Zdalna obsługa", u"Дистанційний показ"),
    "advertiser_type": (u"Typ ogłoszeniodawcy", u"Хто продає"),
    "energy_certificate": (u"Certyfikat energetyczny", u"Енергосертифікат"),
    "available_from": (u"Dostępne od", u"Вільна з"),
    "ownership": (u"Forma własności", u"Форма власності"),
    "type": (u"Typ", u"Тип"),
}

YES_NO: Dict[str, Pair] = {
    "yes": (u"tak", u"так"), "no": (u"nie", u"ні"),
    "true": (u"tak", u"так"), "false": (u"nie", u"ні"),
    "1": (u"tak", u"так"), "0": (u"nie", u"ні"),
}

FIELD_DICTS = {
    "market": MARKET, "building_type": BUILDING_TYPE,
    "building_material": BUILDING_MATERIAL, "construction_status": CONSTRUCTION_STATUS,
    "condition": CONDITION, "ownership": OWNERSHIP, "heating": HEATING,
    "windows": WINDOWS, "seller_type": SELLER_TYPE, "extras": EXTRAS,
}


def uk(field: str, value: Optional[str]) -> Optional[str]:
    """Украинская подпись канонического значения; None — если не знаем."""
    if value is None:
        return None
    d = FIELD_DICTS.get(field)
    if d and value in d:
        return d[value][1]
    if value in YES_NO:
        return YES_NO[value][1]
    return None


def pl(field: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    d = FIELD_DICTS.get(field)
    if d and value in d:
        return d[value][0]
    if value in YES_NO:
        return YES_NO[value][0]
    return value


def label_pair(key: str) -> Pair:
    """Подпись характеристики; неизвестный ключ — как есть в обеих колонках."""
    return CHARACTERISTIC_LABELS.get(key, (key, key))


def floor_uk(floor: Optional[int]) -> Optional[str]:
    """Польская нумерация: parter = наш 1-й поверх. Показываем оба, чтобы не
    переспрашивать при каждом просмотре."""
    if floor is None:
        return None
    if floor == 0:
        return u"партер (наш 1-й поверх)"
    if floor < 0:
        return u"цокольний"
    if floor >= 11:
        return u"вище 10-го (наш 12+)"
    return u"%d-й поверх (наш %d-й)" % (floor, floor + 1)
