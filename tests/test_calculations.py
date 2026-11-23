"""Тесты расчётов: статистика, регрессия, методы принятия решений."""

import statistics
import unittest

import analytics
from decision import Criterion, agreement, criteria_from_preferences, normalize_weights, topsis, weighted_sum
from tests.helpers import temp_db


class StatisticsTests(unittest.TestCase):
    data = [4, 8, 15, 16, 23, 42]

    def test_against_python_statistics(self):
        self.assertAlmostEqual(analytics.mean(self.data), statistics.mean(self.data))
        self.assertAlmostEqual(analytics.median(self.data), statistics.median(self.data))
        self.assertAlmostEqual(analytics.stdev(self.data), statistics.stdev(self.data))
        self.assertEqual(analytics.median([3, 1, 2]), 2)

    def test_empty_inputs(self):
        self.assertEqual(analytics.mean([]), 0)
        self.assertEqual(analytics.median([]), 0)
        self.assertEqual(analytics.stdev([5]), 0)
        self.assertEqual(analytics.pearson([1], [2]), 0)

    def test_pearson(self):
        xs = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(analytics.pearson(xs, [2, 4, 6, 8, 10]), 1.0)
        self.assertAlmostEqual(analytics.pearson(xs, [10, 8, 6, 4, 2]), -1.0)
        self.assertAlmostEqual(analytics.pearson(xs, [7, 7, 7, 7, 7]), 0.0)
        self.assertAlmostEqual(analytics.pearson(xs, [1, 3, 2, 5, 4]), statistics.correlation(xs, [1, 3, 2, 5, 4]))

    def test_linear_regression(self):
        m = analytics.linear_regression([1, 2, 3, 4], [3, 5, 7, 9])  # y = 2x + 1
        self.assertAlmostEqual(m.slope, 2); self.assertAlmostEqual(m.intercept, 1); self.assertAlmostEqual(m.r2, 1)
        self.assertAlmostEqual(m.predict(10), 21)
        ref = statistics.linear_regression([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
        m = analytics.linear_regression([1, 2, 3, 4, 5], [2, 4, 5, 4, 5])
        self.assertAlmostEqual(m.slope, ref.slope); self.assertAlmostEqual(m.intercept, ref.intercept)
        self.assertAlmostEqual(m.r2, 0.6)

    def test_percent_change(self):
        self.assertEqual(analytics.percent_change(200, 250), 25)
        self.assertEqual(analytics.percent_change(0, 5), 0)


class DecisionTests(unittest.TestCase):
    alts = [
        {"id": 1, "name": "A", "quality": 90, "price": 50},
        {"id": 2, "name": "B", "quality": 70, "price": 30},
        {"id": 3, "name": "C", "quality": 50, "price": 20},
    ]

    def test_normalize_weights(self):
        w = normalize_weights([Criterion("a", "a", 3), Criterion("b", "b", 1)])
        self.assertAlmostEqual(sum(c.weight for c in w), 1)
        self.assertAlmostEqual(w[0].weight, 0.75)
        w = normalize_weights([Criterion("a", "a", 0), Criterion("b", "b", 0)])
        self.assertAlmostEqual(w[0].weight, 0.5)

    def test_weighted_sum_by_hand(self):
        # quality: A=1, B=0.5, C=0; price (затраты): A=0, B=2/3, C=1; веса 0.5/0.5
        crit = [Criterion("quality", "Качество", 1), Criterion("price", "Цена", 1, benefit=False)]
        r = {x.name: x.score for x in weighted_sum(self.alts, crit)}
        self.assertAlmostEqual(r["A"], 50.0)
        self.assertAlmostEqual(r["B"], round((0.25 + 1 / 3) * 100, 2))
        self.assertAlmostEqual(r["C"], 50.0)
        self.assertEqual(weighted_sum(self.alts, crit)[0].name, "B")

    def test_weights_change_winner(self):
        quality_first = [Criterion("quality", "Q", 10), Criterion("price", "P", 1, False)]
        price_first = [Criterion("quality", "Q", 1), Criterion("price", "P", 10, False)]
        self.assertEqual(weighted_sum(self.alts, quality_first)[0].name, "A")
        self.assertEqual(weighted_sum(self.alts, price_first)[0].name, "C")
        self.assertEqual(topsis(self.alts, quality_first)[0].name, "A")
        self.assertEqual(topsis(self.alts, price_first)[0].name, "C")

    def test_topsis_bounds_and_dominance(self):
        alts = self.alts + [{"id": 4, "name": "Ideal", "quality": 95, "price": 10}]
        crit = [Criterion("quality", "Q", 1), Criterion("price", "P", 1, False)]
        res = topsis(alts, crit)
        self.assertEqual(res[0].name, "Ideal")
        self.assertAlmostEqual(res[0].score, 100.0)  # доминирующая альтернатива совпадает с идеалом
        self.assertTrue(all(0 <= r.score <= 100 for r in res))
        self.assertEqual([r.rank for r in res], [1, 2, 3, 4])

    def test_agreement(self):
        crit = [Criterion("quality", "Q", 1)]
        a = weighted_sum(self.alts, crit)
        self.assertEqual(agreement(a, a), 1.0)
        reverse = weighted_sum(self.alts, [Criterion("quality", "Q", 1, benefit=False)])
        self.assertEqual(agreement(a, reverse), -1.0)

    def test_empty(self):
        self.assertEqual(weighted_sum([], [Criterion("a", "a", 1)]), [])
        self.assertEqual(topsis(self.alts, []), [])

    def test_on_real_catalog(self):
        db = temp_db()
        from decision import alternatives_from_db
        alts = alternatives_from_db(db)
        crit = criteria_from_preferences({"Тишина": 5, "Безопасность": 5})
        self.assertEqual(len(alts), 14)
        self.assertEqual(len(weighted_sum(alts, crit)), 14)
        rows = analytics.rows_for_analysis(db)
        s = analytics.summary(rows)
        self.assertEqual(s["complexes"], 14)
        self.assertEqual(s["reviews"], db.total_reviews())
        self.assertTrue(-1 <= s["price_index_corr"] <= 1)
        self.assertEqual(sum(analytics.rating_distribution(db.all_reviews()).values()), db.total_reviews())
        self.assertEqual(sum(d["count"] for d in analytics.by_district(rows)), 14)
        db.close()


if __name__ == "__main__":
    unittest.main()
