"""Тесты базы данных: схема, CRUD, проверка данных, импорт, история."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.helpers import temp_db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = temp_db()

    def tearDown(self):
        self.db.close()

    def test_schema_has_all_tables(self):
        tables = {r[0] for r in self.db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ("developments", "reviews", "users", "comfort_preferences", "history", "reset_codes"):
            self.assertIn(name, tables)

    def test_catalog_and_demo_seeded_with_source(self):
        self.assertEqual(len(self.db.developments()), 14)
        self.assertGreater(self.db.total_reviews(), 100)
        sources = {r["source"] for r in self.db.all_reviews()}
        self.assertEqual(sources, {"Демо-данные"})

    def test_demo_can_be_disabled(self):
        db = temp_db(seed_demo=False)
        self.assertEqual(db.total_reviews(), 0)
        db.close()

    def test_crud_development(self):
        item = {"name": "Тестовый ЖК", "district": "Есильский район", "lat": 51.12, "lng": 71.43, "purchase_price": 30_000_000}
        new_id = self.db.add_development(item, "manual")
        self.assertEqual(self.db.get_development(new_id)["name"], "Тестовый ЖК")
        item["name"] = "Переименован"
        self.db.update_development(new_id, item)
        self.assertEqual(self.db.get_development(new_id)["name"], "Переименован")
        self.db.add_review(new_id, "Импорт", 4, "Автор", "Тихо и спокойно, рядом автобус")
        self.assertEqual(self.db.review_count(new_id), 1)
        self.db.delete_development(new_id)
        self.assertIsNone(self.db.get_development(new_id))
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM reviews WHERE development_id=?", (new_id,)).fetchone()[0], 0)

    def test_rejects_invalid_development(self):
        with self.assertRaises(ValueError):
            self.db.add_development({"name": "Алматы ЖК", "city": "Алматы", "lat": 43.2, "lng": 76.9})
        with self.assertRaises(ValueError):
            self.db.add_development({"name": "Вне Астаны", "lat": 43.2, "lng": 76.9})
        with self.assertRaises(ValueError):
            self.db.add_development({"name": "", "lat": 51.1, "lng": 71.4})
        with self.assertRaises(ValueError):
            self.db.add_development({"name": "Минус", "lat": 51.1, "lng": 71.4, "purchase_price": -5})

    def test_rejects_invalid_review(self):
        dev_id = self.db.developments()[0]["id"]
        for rating, text, source in [(0, "текст", "Импорт"), (6, "текст", "Импорт"), (5, "  ", "Импорт"), (5, "текст", "")]:
            with self.assertRaises(ValueError):
                self.db.add_review(dev_id, source, rating, "А", text)

    def test_import_skips_bad_rows(self):
        payload = [
            {"name": "Хороший", "lat": 51.1, "lng": 71.4, "reviews": [{"rating": 5, "text": "Отлично", "source": "Импорт"},
                                                                       {"rating": 9, "text": "Плохая оценка"}]},
            {"name": "Плохие координаты", "lat": 10, "lng": 10},
            {"name": "Другой город", "city": "Шымкент", "lat": 51.1, "lng": 71.4},
        ]
        path = Path(tempfile.mkdtemp()) / "import.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        devs, reviews = self.db.import_file(path)
        self.assertEqual((devs, reviews), (1, 1))
        self.assertEqual(len(self.db.last_import_errors), 2)

    def test_import_broken_json(self):
        path = Path(tempfile.mkdtemp()) / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.db.import_file(path)

    def test_validate_and_repair(self):
        self.assertEqual(self.db.validate_data(), [])
        dev_id = self.db.developments()[0]["id"]
        # «портим» базу в обход проверок, как это мог бы сделать сторонний инструмент
        self.db.connection.execute("INSERT INTO reviews (development_id, source, rating, text) VALUES (?, 'x', 9, 'ok')", (dev_id,))
        self.db.connection.execute("INSERT INTO reviews (development_id, source, rating, text) VALUES (?, 'x', 3, '  ')", (dev_id,))
        self.db.connection.execute("UPDATE developments SET purchase_price = -1 WHERE id = ?", (dev_id,))
        self.db.connection.commit()
        kinds = {i["kind"] for i in self.db.validate_data()}
        self.assertTrue({"rating", "empty_review", "development"} <= kinds)
        self.assertGreaterEqual(self.db.repair_data(), 3)
        self.assertEqual(self.db.validate_data(), [])

    def test_integrity_check_ok(self):
        self.assertEqual(self.db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_history_log_search_filter(self):
        user = self.db.authenticate("super_admin", "super_admin")
        self.db.log(user, "Поиск", "BI City", "Найдено: 3")
        self.db.log(user, "Вопрос Доми", "Что до 35 млн?", "Arman Qala")
        self.db.log({"id": 999, "username": "other"}, "Поиск", "Expo", "1")
        self.assertEqual(len(self.db.history(user_id=user["id"], action="Поиск")), 1)
        self.assertEqual(self.db.history(user_id=user["id"], search="35 млн")[0]["action"], "Вопрос Доми")
        self.assertEqual(len(self.db.history(search="Expo")), 1)
        self.assertEqual(self.db.history(user_id=user["id"], date_from="2000-01-01", date_to="2000-01-02"), [])
        self.assertIn("Поиск", self.db.history_actions())
        self.db.clear_history(user["id"])
        self.assertEqual(len(self.db.history(user_id=user["id"], action="Поиск")), 0)
        self.assertEqual(len(self.db.history(search="Expo")), 1)


if __name__ == "__main__":
    unittest.main()
