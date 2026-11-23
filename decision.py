"""Методы принятия решений: какой ЖК выбрать.

Реализованы два классических метода многокритериального выбора:

1. WSM (Weighted Sum Model, метод взвешенной суммы)
   Каждый критерий нормируется в шкалу 0..1 (min-max), «стоимостные» критерии
   (цена — чем меньше, тем лучше) инвертируются. Итог = Σ wᵢ · xᵢ.

2. TOPSIS (Technique for Order Preference by Similarity to Ideal Solution)
   Матрица нормируется векторно (xᵢⱼ / √Σxᵢⱼ²), умножается на веса, затем для
   каждой альтернативы считается расстояние до идеального (A⁺) и анти-идеального
   (A⁻) решения. Близость C = D⁻ / (D⁺ + D⁻) ∈ [0, 1] — чем больше, тем лучше.

Оба метода получают одинаковые критерии и веса, поэтому их результаты можно
сравнить: если лидер совпадает — решение устойчиво.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Criterion:
    key: str
    title: str
    weight: float
    benefit: bool = True  # True — больше лучше, False — меньше лучше (цена)


@dataclass
class Ranked:
    id: int
    name: str
    score: float           # 0..100
    rank: int
    values: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)  # вклад критериев (для WSM)


def normalize_weights(criteria: list[Criterion]) -> list[Criterion]:
    total = sum(max(0.0, c.weight) for c in criteria)
    if total <= 0:
        share = 1 / len(criteria) if criteria else 0
        return [Criterion(c.key, c.title, share, c.benefit) for c in criteria]
    return [Criterion(c.key, c.title, max(0.0, c.weight) / total, c.benefit) for c in criteria]


def _rank(items: list[Ranked]) -> list[Ranked]:
    items.sort(key=lambda r: (-r.score, r.name))
    for i, item in enumerate(items, 1):
        item.rank = i
    return items


def weighted_sum(alternatives: list[dict], criteria: list[Criterion]) -> list[Ranked]:
    """alternatives: [{"id", "name", <criterion.key>: число, ...}]"""
    if not alternatives or not criteria:
        return []
    criteria = normalize_weights(criteria)
    bounds = {}
    for c in criteria:
        column = [float(a.get(c.key, 0) or 0) for a in alternatives]
        bounds[c.key] = (min(column), max(column))
    result = []
    for a in alternatives:
        total = 0.0
        contributions = {}
        for c in criteria:
            lo, hi = bounds[c.key]
            x = float(a.get(c.key, 0) or 0)
            norm = 1.0 if hi == lo else (x - lo) / (hi - lo)
            if not c.benefit:
                norm = 1 - norm
            contributions[c.key] = round(c.weight * norm * 100, 2)
            total += c.weight * norm
        result.append(Ranked(a["id"], a["name"], round(total * 100, 2), 0,
                             {c.key: float(a.get(c.key, 0) or 0) for c in criteria}, contributions))
    return _rank(result)


def topsis(alternatives: list[dict], criteria: list[Criterion]) -> list[Ranked]:
    if not alternatives or not criteria:
        return []
    criteria = normalize_weights(criteria)
    weighted: dict[str, list[float]] = {}
    for c in criteria:
        column = [float(a.get(c.key, 0) or 0) for a in alternatives]
        norm = math.sqrt(sum(x * x for x in column)) or 1.0
        weighted[c.key] = [c.weight * x / norm for x in column]
    ideal = {c.key: (max if c.benefit else min)(weighted[c.key]) for c in criteria}
    anti = {c.key: (min if c.benefit else max)(weighted[c.key]) for c in criteria}
    result = []
    for i, a in enumerate(alternatives):
        d_plus = math.sqrt(sum((weighted[c.key][i] - ideal[c.key]) ** 2 for c in criteria))
        d_minus = math.sqrt(sum((weighted[c.key][i] - anti[c.key]) ** 2 for c in criteria))
        closeness = 0.5 if d_plus + d_minus == 0 else d_minus / (d_plus + d_minus)
        result.append(Ranked(a["id"], a["name"], round(closeness * 100, 2), 0,
                             {c.key: float(a.get(c.key, 0) or 0) for c in criteria}))
    return _rank(result)


def agreement(a: list[Ranked], b: list[Ranked]) -> float:
    """Ранговая корреляция Спирмена между двумя рейтингами (−1..1)."""
    rank_b = {r.id: r.rank for r in b}
    common = [r for r in a if r.id in rank_b]
    n = len(common)
    if n < 2:
        return 1.0
    d2 = sum((r.rank - rank_b[r.id]) ** 2 for r in common)
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


# ───────────── Применение к данным HouseCheck ─────────────

CATEGORY_KEYS = ["Транспорт", "Тишина", "Двор", "Безопасность", "Сервис"]


def criteria_from_preferences(prefs: dict[str, int], price_weight: int = 3, rating_weight: int = 2) -> list[Criterion]:
    """Переводит 12 ползунков «Мой комфорт» в веса 5 категорий + цена + рейтинг."""
    from assistant_engine import CRITERIA_MAP
    weights = {k: 0.0 for k in CATEGORY_KEYS}
    for criterion, importance in (prefs or {}).items():
        cat = CRITERIA_MAP.get(criterion)
        if cat in weights:
            weights[cat] += float(importance or 0)
    if not any(weights.values()):
        weights = {k: 3.0 for k in CATEGORY_KEYS}
    criteria = [Criterion(k, k, w) for k, w in weights.items()]
    criteria.append(Criterion("price", "Цена покупки", float(price_weight), benefit=False))
    criteria.append(Criterion("rating", "Средняя оценка", float(rating_weight)))
    return criteria


def alternatives_from_db(db, ids: list[int] | None = None) -> list[dict]:
    rows = []
    for item in db.developments():
        if ids and item["id"] not in ids:
            continue
        if not db.review_count(item["id"]):
            continue
        analysis = db.analysis_for(item["id"])
        row = {"id": item["id"], "name": item["name"],
               "price": float(item.get("purchase_price") or item.get("price_from") or 0),
               "rating": round(db.avg_rating(item["id"]), 2)}
        row.update({k: float(analysis.categories.get(k, 0)) for k in CATEGORY_KEYS})
        rows.append(row)
    return rows


def explain(best: Ranked, criteria: list[Criterion]) -> str:
    """Короткое объяснение, почему лидер WSM оказался первым."""
    if not best.contributions:
        return ""
    criteria = {c.key: c for c in normalize_weights(criteria)}
    top = sorted(best.contributions.items(), key=lambda kv: kv[1], reverse=True)[:3]
    parts = [f"{criteria[k].title.lower()} (+{v:.1f})" for k, v in top if v > 0]
    return f"«{best.name}» набрал {best.score:.1f} из 100. Больше всего баллов дали: " + ", ".join(parts) + "."
