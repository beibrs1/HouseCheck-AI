"""Математические расчёты и подготовка данных для графиков.

Здесь нет зависимостей от интерфейса: функции принимают списки чисел или
базу данных и возвращают готовые структуры, которые рисуют графики и отчёты.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass


# ───────────── Базовая статистика ─────────────

def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def stdev(values: list[float]) -> float:
    """Выборочное стандартное отклонение (n − 1)."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def pearson(xs: list[float], ys: list[float]) -> float:
    """Коэффициент корреляции Пирсона, −1..1."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    mx, my = mean(xs[:n]), mean(ys[:n])
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs[:n])
    vy = sum((y - my) ** 2 for y in ys[:n])
    if vx == 0 or vy == 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


@dataclass(frozen=True)
class LinearModel:
    slope: float
    intercept: float
    r2: float

    def predict(self, x: float) -> float:
        return self.slope * x + self.intercept


def linear_regression(xs: list[float], ys: list[float]) -> LinearModel:
    """Метод наименьших квадратов: y = a·x + b, плюс коэффициент детерминации R²."""
    n = min(len(xs), len(ys))
    if n < 2:
        return LinearModel(0.0, mean(ys), 0.0)
    mx, my = mean(xs[:n]), mean(ys[:n])
    sxx = sum((x - mx) ** 2 for x in xs[:n])
    if sxx == 0:
        return LinearModel(0.0, my, 0.0)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys[:n])
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if ss_tot == 0 else max(0.0, 1 - ss_res / ss_tot)
    return LinearModel(slope, intercept, r2)


def percent_change(old: float, new: float) -> float:
    return 0.0 if not old else (new - old) / old * 100


# ───────────── Данные HouseCheck ─────────────

def rows_for_analysis(db) -> list[dict]:
    """Одна строка на ЖК: цена, индекс комфорта, оценка, число отзывов."""
    rows = []
    for item in db.developments():
        n = db.review_count(item["id"])
        analysis = db.analysis_for(item["id"])
        rows.append({
            "id": item["id"], "name": item["name"], "district": item.get("district") or "—",
            "housing_class": item.get("housing_class") or "—",
            "price": int(item.get("purchase_price") or item.get("price_from") or 0),
            "rent": int(item.get("rental_price") or 0),
            "index": analysis.overall, "rating": round(db.avg_rating(item["id"]), 2), "reviews": n,
            "categories": dict(analysis.categories),
        })
    return rows


def summary(rows: list[dict]) -> dict:
    """Итоговые показатели для плиток и отчёта."""
    rated = [r for r in rows if r["reviews"]]
    prices = [r["price"] for r in rows if r["price"]]
    idx = [r["index"] for r in rated]
    best = max(rated, key=lambda r: r["index"], default=None)
    cheapest = min((r for r in rows if r["price"]), key=lambda r: r["price"], default=None)
    value = max((r for r in rated if r["price"]), key=lambda r: r["index"] / (r["price"] / 1e6), default=None)
    return {
        "complexes": len(rows),
        "reviews": sum(r["reviews"] for r in rows),
        "avg_index": round(mean(idx), 1),
        "median_index": round(median(idx), 1),
        "stdev_index": round(stdev(idx), 1),
        "avg_rating": round(mean([r["rating"] for r in rated]), 2),
        "avg_price": round(mean(prices)),
        "median_price": round(median(prices)),
        "price_index_corr": round(pearson([r["price"] for r in rated if r["price"]], [r["index"] for r in rated if r["price"]]), 3),
        "best": best["name"] if best else "—",
        "cheapest": cheapest["name"] if cheapest else "—",
        "best_value": value["name"] if value else "—",
    }


def by_district(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["district"]].append(r)
    out = []
    for district, items in groups.items():
        rated = [i for i in items if i["reviews"]]
        prices = [i["price"] for i in items if i["price"]]
        out.append({"district": district, "count": len(items), "avg_index": round(mean([i["index"] for i in rated]), 1),
                    "avg_price": round(mean(prices)), "reviews": sum(i["reviews"] for i in items)})
    return sorted(out, key=lambda d: -d["avg_index"])


def rating_distribution(reviews: list[dict]) -> dict[int, int]:
    counts = Counter(max(1, min(5, int(r.get("rating") or 0))) for r in reviews if r.get("rating"))
    return {star: counts.get(star, 0) for star in range(1, 6)}


def category_averages(rows: list[dict]) -> dict[str, float]:
    rated = [r for r in rows if r["reviews"]]
    keys = list(rated[0]["categories"]) if rated else []
    return {k: round(mean([r["categories"].get(k, 0) for r in rated]), 1) for k in keys}


def price_per_index(rows: list[dict]) -> list[dict]:
    """Сколько миллионов тенге стоит 1 балл индекса комфорта (меньше — выгоднее)."""
    out = []
    for r in rows:
        if r["reviews"] and r["price"] and r["index"]:
            out.append({"name": r["name"], "value": round(r["price"] / 1e6 / r["index"], 3)})
    return sorted(out, key=lambda d: d["value"])
