"""Проверка ИИ-функций на трёх разных наборах данных."""

import unittest

from ai_insights import explain_analysis, price_forecast, recommend
from analyzer import analyze_reviews
from assistant_engine import LocalEngine
from tests.helpers import temp_db

# Набор 1: однозначно положительные отзывы
POSITIVE = [
    {"rating": 5, "text": "Очень тихо, шум не слышно. Рядом остановка автобуса, до метро LRT быстро.", "source": "Импорт"},
    {"rating": 5, "text": "Закрытый двор, детская площадка, охрана и камеры. Управляющая компания быстро решают заявки.", "source": "Импорт"},
    {"rating": 4, "text": "Спокойный район, консьерж, чисто в подъезде, уборка каждый день.", "source": "Импорт"},
]
# Набор 2: однозначно отрицательные отзывы
NEGATIVE = [
    {"rating": 1, "text": "Шум дороги и стройка рядом, громко даже ночью. Парковки не хватает.", "source": "Импорт"},
    {"rating": 2, "text": "Лифт не работает неделями, в подъезде темно, посторонние ходят. Охраны фактически нет.", "source": "Импорт"},
    {"rating": 1, "text": "Управляющая плохая, не убирают, крыша течет. Пробки утром, трудно добираться.", "source": "Импорт"},
]
# Набор 3: смешанные отзывы
MIXED = [
    {"rating": 5, "text": "Отличный двор и детская площадка, тихо.", "source": "Импорт"},
    {"rating": 2, "text": "Пробки и парковки не хватает, машин много.", "source": "Импорт"},
    {"rating": 3, "text": "Охрана есть, но лифт не работает иногда.", "source": "Импорт"},
    {"rating": 4, "text": "Рядом остановка, удобный транспорт.", "source": "Импорт"},
]


class ReviewAnalysisTests(unittest.TestCase):
    def test_three_datasets_are_ordered(self):
        pos, neg, mix = analyze_reviews(POSITIVE), analyze_reviews(NEGATIVE), analyze_reviews(MIXED)
        self.assertGreater(pos.overall, mix.overall)
        self.assertGreater(mix.overall, neg.overall)
        self.assertGreaterEqual(pos.overall, 80)
        self.assertLessEqual(neg.overall, 45)

    def test_moods_and_signals(self):
        pos, neg, mix = analyze_reviews(POSITIVE), analyze_reviews(NEGATIVE), analyze_reviews(MIXED)
        self.assertEqual(pos.mood, "Преимущественно положительный фон")
        self.assertEqual(neg.mood, "Есть повторяющиеся проблемы")
        self.assertEqual(mix.mood, "Смешанные впечатления")
        self.assertTrue(pos.pros and not pos.cons)
        self.assertTrue(neg.cons)
        self.assertEqual(len(neg.cons), 3)  # выводятся три главные проблемы

    def test_categories_in_range(self):
        for data in (POSITIVE, NEGATIVE, MIXED):
            r = analyze_reviews(data)
            self.assertEqual(set(r.categories), {"Транспорт", "Тишина", "Двор", "Безопасность", "Сервис"})
            self.assertTrue(all(30 <= v <= 98 for v in r.categories.values()))

    def test_no_data(self):
        r = analyze_reviews([])
        self.assertEqual((r.overall, r.mood), (0, "Нет данных"))

    def test_explanation_confidence_and_limitations(self):
        few = explain_analysis(POSITIVE, analyze_reviews(POSITIVE))
        many = explain_analysis(POSITIVE * 8, analyze_reviews(POSITIVE * 8))
        self.assertLess(few.confidence_pct, many.confidence_pct)
        self.assertTrue(any("меньше 5" in x for x in few.limitations))
        demo = [dict(r, source="Демо-данные") for r in POSITIVE]
        self.assertTrue(any("демо" in x.lower() for x in explain_analysis(demo, analyze_reviews(demo)).limitations))


class PredictionAndRecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = temp_db()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_price_forecast(self):
        forecast, r2 = price_forecast(self.db)
        self.assertEqual(len(forecast), 14)
        self.assertTrue(0 <= r2 <= 1)
        for f in forecast:
            self.assertGreater(f.predicted, 0)
            self.assertIn(f.verdict, {"дороже ожидаемого", "выгоднее рынка", "цена соответствует комфорту"})

    def test_recommendations_follow_preferences(self):
        quiet = recommend(self.db, {"Тишина": 5}, top=3)
        transport = recommend(self.db, {"Транспорт": 5, "Магазины": 5}, top=3)
        self.assertEqual(len(quiet), 3)
        self.assertNotEqual([r.id for r, _ in quiet], [r.id for r, _ in transport])

    def test_assistant_answers_three_question_types(self):
        engine = LocalEngine(self.db)
        for question in ("Подбери ЖК для семьи", "Что до 35 млн?", "Сравни BI City Seoul и Highvill Astana"):
            with self.subTest(question=question):
                reply = engine.answer(question, {}, "ru")
                self.assertTrue(reply["text"])
                self.assertIsInstance(reply["cards"], list)


if __name__ == "__main__":
    unittest.main()
