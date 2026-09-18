# -*- coding: utf-8 -*-
"""Реестр адаптеров источников. Новый источник = новый модуль с классом,
наследующим `base.Source`, и строка в REGISTRY."""
from typing import Dict, Type

from .base import RawListing, Source  # noqa: F401
from .otodom import Otodom
from .olx import Olx

REGISTRY: Dict[str, Type[Source]] = {
    Otodom.name: Otodom,
    Olx.name: Olx,
}


def get_source(name: str) -> Source:
    return REGISTRY[name]()
