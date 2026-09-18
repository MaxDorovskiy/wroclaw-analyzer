# -*- coding: utf-8 -*-
"""Догнать очередь перевода руками (например, ночью, когда карта свободна).

    .venv/bin/python scripts/translate_backlog.py --limit 500
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import translate  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    db = SessionLocal()
    print(translate.status(db))
    print(translate.translate_pending(db, args.limit))


if __name__ == "__main__":
    main()
