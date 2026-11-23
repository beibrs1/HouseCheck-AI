"""Общие утилиты тестов: временная база данных, не трогающая рабочую."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HOUSECHECK_SEED_DEMO", "1")
os.environ.setdefault("HOUSECHECK_SEED_ASTANA", "1")

from database import Database  # noqa: E402


def temp_db(seed_demo: bool = True) -> Database:
    os.environ["HOUSECHECK_SEED_DEMO"] = "1" if seed_demo else "0"
    path = Path(tempfile.mkdtemp(prefix="housecheck-test-")) / "test.sqlite3"
    return Database(path)
