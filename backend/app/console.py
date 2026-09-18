# -*- coding: utf-8 -*-
"""Вывод скриптов в UTF-8 на Windows.

В консоли print() идёт через Unicode API и печатает что угодно. Но стоит вывод
перенаправить (файл, конвейер, Планировщик, запуск из чата) — Python пишет в
ANSI-кодировке системы, а в cp1251 нет ни «ł», ни «²»: print() заголовка
объявления ронял probe_sources.py с UnicodeEncodeError (проверено 18.09.2026,
Python 3.14). Русский текст при этом проходит — поэтому на своём выводе
скрипты «работали», пока не доходили до первой польской буквы.
"""
import sys


def utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):   # поток подменён (pytest, IDE) — оставляем как есть
            pass
