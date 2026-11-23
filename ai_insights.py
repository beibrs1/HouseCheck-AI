"""Собственные ИИ-функции HouseCheck AI (работают без интернета и API-ключей).

1. analyze_reviews (analyzer.py) — анализ тональности отзывов по 5 категориям.
2. price_forecast — прогноз «справедливой» цены ЖК по индексу комфорта
   (линейная регрессия по всем ЖК каталога) и оценка: дороже или дешевле ожидаемого.
3. recommend — рекомендации на основе профиля комфорта (TOPSIS) с причинами.
4. explain_analysis — объяснение результата: уверенность и ограничения модели.
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics import linear_regression, rows_for_analysis
from decision import Ranked, alternatives_from_db, criteria_from_preferences, topsis

DEMO_SOURCE = "Демо-данные"


@dataclass
class Forecast:
    id: int
    name: str
    actual: int
    predicted: int
    deviation_pct: float
    verdict: str


@dataclass
class Explanation:
    confidence: str          # высокая | средняя | низкая
    confidence_pct: int
    reasons: list[str]
    limitations: list[str]


def price_forecast(db) -> tuple[list[Forecast], float]:
    """Возвращает прогноз по каждому ЖК и R² модели (доля объяснённой дисперсии цены)."""
    rows = [r for r in rows_for_analysis(db) if r["reviews"] and r["price"]]
    if len(rows) < 3:
        return [], 0.0
    model = linear_regression([r["index"] for r in rows], [r["price"] for r in rows])
    out = []
    for r in rows:
        predicted = max(1, round(model.predict(r["index"])))
        dev = (r["price"] - predicted) / predicted * 100
        if dev > 15:
            verdict = "дороже ожидаемого"
        elif dev < -15:
            verdict = "выгоднее рынка"
        else:
            verdict = "цена соответствует комфорту"
        out.append(Forecast(r["id"], r["name"], r["price"], predicted, round(dev, 1), verdict))
    out.sort(key=lambda f: f.deviation_pct)
    return out, round(model.r2, 3)


def recommend(db, prefs: dict[str, int], top: int = 3) -> list[tuple[Ranked, str]]:
    criteria = criteria_from_preferences(prefs)
    ranked = topsis(alternatives_from_db(db), criteria)[:top]
    weights = {c.key: c.weight for c in criteria if c.key not in ("price", "rating")}
    focus = sorted(weights, key=weights.get, reverse=True)[:2]
    result = []
    for r in ranked:
        strong = [k.lower() for k in focus if r.values.get(k, 0) >= 70]
        why = ("сильные стороны по вашим приоритетам: " + ", ".join(strong)) if strong else "сбалансирован по всем критериям"
        result.append((r, why))
    return result


def explain_analysis(reviews: list[dict], analysis) -> Explanation:
    n = len(reviews)
    sources = {r.get("source", "") for r in reviews}
    texts = [str(r.get("text", "")) for r in reviews]
    avg_len = sum(len(t) for t in texts) / n if n else 0
    score = min(1.0, n / 20) * 0.6 + min(1.0, avg_len / 160) * 0.2 + (0.2 if len(sources) > 1 or DEMO_SOURCE not in sources else 0.05)
    pct = round(score * 100)
    level = "высокая" if pct >= 70 else "средняя" if pct >= 40 else "низкая"
    reasons = [f"Проанализировано отзывов: {n}.", f"Средняя длина отзыва: {avg_len:.0f} символов.",
               f"Источники: {', '.join(sorted(s for s in sources if s)) or '—'}."]
    if analysis.pros:
        reasons.append("Чаще хвалят: " + ", ".join(analysis.pros) + ".")
    if analysis.cons:
        reasons.append("Чаще жалуются: " + ", ".join(analysis.cons) + ".")
    limitations = [
        "Модель ищет ключевые слова и оценки — она не понимает сарказм и сложный контекст.",
        "Лучше всего распознаётся русский язык; казахские и английские отзывы учитываются в основном по оценке.",
        "Индекс отражает мнение авторов отзывов, а не официальную экспертизу дома.",
    ]
    if n < 5:
        limitations.insert(0, "Отзывов меньше 5 — вывод может быть случайным.")
    if DEMO_SOURCE in sources:
        limitations.insert(0, "Часть отзывов — демо-данные для презентации, а не реальные мнения жителей.")
    return Explanation(level, pct, reasons, limitations)
