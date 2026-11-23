"""Формирование отчётов: HTML, PDF и CSV.

build_report_data() собирает все показатели в один словарь (экспортные данные),
render_html() превращает его в оформленный HTML, save_report() сохраняет файл.
PDF печатается из того же HTML средствами Qt (QTextDocument → QPdfWriter).
"""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

import analytics
from ai_insights import price_forecast
from decision import agreement, alternatives_from_db, criteria_from_preferences, explain, topsis, weighted_sum
from config import DATA_DIR

REPORTS_DIR = DATA_DIR / "reports"


def build_report_data(db, user: dict | None = None, prefs: dict | None = None) -> dict:
    prefs = prefs if prefs is not None else db.preferences()
    rows = analytics.rows_for_analysis(db)
    criteria = criteria_from_preferences(prefs)
    alts = alternatives_from_db(db)
    wsm, tps = weighted_sum(alts, criteria), topsis(alts, criteria)
    forecast, r2 = price_forecast(db)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user": (user or {}).get("full_name") or (user or {}).get("username", ""),
        "summary": analytics.summary(rows),
        "districts": analytics.by_district(rows),
        "categories": analytics.category_averages(rows),
        "ratings": analytics.rating_distribution(db.all_reviews()),
        "rows": sorted(rows, key=lambda r: -r["index"]),
        "criteria": [{"title": c.title, "weight": round(c.weight, 3), "benefit": c.benefit} for c in criteria],
        "wsm": [{"rank": r.rank, "name": r.name, "score": r.score} for r in wsm],
        "topsis": [{"rank": r.rank, "name": r.name, "score": r.score} for r in tps],
        "agreement": agreement(wsm, tps),
        "explanation": explain(wsm[0], criteria) if wsm else "",
        "forecast": [f.__dict__ for f in forecast],
        "forecast_r2": r2,
    }


def _money(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ") + " ₸"


def _table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(data: dict) -> str:
    s = data["summary"]
    kpi = [("ЖК в каталоге", s["complexes"]), ("Отзывов", s["reviews"]), ("Средний индекс", s["avg_index"]),
           ("Медиана индекса", s["median_index"]), ("Ст. отклонение", s["stdev_index"]), ("Средняя оценка", s["avg_rating"]),
           ("Средняя цена", _money(s["avg_price"])), ("Корреляция цена↔индекс", s["price_index_corr"])]
    kpi_html = "".join(f"<td class='kpi'><b>{html.escape(str(v))}</b><br><span>{html.escape(k)}</span></td>" for k, v in kpi)
    parts = [
        "<html><head><meta charset='utf-8'><title>Отчёт HouseCheck AI</title><style>",
        "body{font-family:'Helvetica Neue',Arial,sans-serif;color:#17233F;margin:28px;}"
        "h1{color:#F28A3C;margin-bottom:2px}h2{margin-top:26px;border-bottom:2px solid #FFE6D2;padding-bottom:4px}"
        "table{border-collapse:collapse;width:100%;margin-top:8px}th{background:#17233F;color:#fff;text-align:left;padding:6px 8px;font-size:12px}"
        "td{border-bottom:1px solid #F0E3D8;padding:5px 8px;font-size:12px}.kpi{border:none;background:#FFF4EA;text-align:center;padding:10px}"
        ".kpi b{font-size:18px}.kpi span{color:#7A8498;font-size:11px}.note{color:#7A8498;font-size:11px}",
        "</style></head><body>",
        "<h1>HouseCheck AI — аналитический отчёт</h1>",
        f"<p class='note'>Сформирован: {html.escape(data['generated_at'])}"
        + (f" · Пользователь: {html.escape(data['user'])}" if data["user"] else "") + "</p>",
        "<h2>1. Итоговые показатели</h2>", f"<table><tr>{kpi_html}</tr></table>",
        f"<p>Лучший индекс комфорта: <b>{html.escape(s['best'])}</b>. Самый доступный: <b>{html.escape(s['cheapest'])}</b>. "
        f"Лучшее соотношение цены и комфорта: <b>{html.escape(s['best_value'])}</b>.</p>",
        "<h2>2. Районы</h2>",
        _table(["Район", "ЖК", "Средний индекс", "Средняя цена", "Отзывов"],
               [[d["district"], d["count"], d["avg_index"], _money(d["avg_price"]), d["reviews"]] for d in data["districts"]]),
        "<h2>3. Распределение оценок</h2>",
        _table(["Оценка", "Количество"], [[f"{k} ★", v] for k, v in data["ratings"].items()]),
        "<h2>4. Средние баллы по категориям</h2>",
        _table(["Категория", "Средний балл"], [[k, v] for k, v in data["categories"].items()]),
        "<h2>5. Принятие решения</h2>",
        "<p>Критерии и нормированные веса (по профилю «Мой комфорт»):</p>",
        _table(["Критерий", "Вес", "Тип"], [[c["title"], c["weight"], "выгода" if c["benefit"] else "затраты"] for c in data["criteria"]]),
        "<p><b>Метод взвешенной суммы (WSM)</b> и <b>TOPSIS</b>:</p>",
        _table(["Место", "WSM", "Балл", "TOPSIS", "Близость к идеалу"],
               [[w["rank"], w["name"], w["score"], t["name"], t["score"]] for w, t in zip(data["wsm"][:10], data["topsis"][:10])]),
        f"<p>{html.escape(data['explanation'])} Согласованность методов (ранговая корреляция Спирмена): "
        f"<b>{data['agreement']}</b>.</p>",
        "<h2>6. ИИ-прогноз справедливой цены</h2>",
        f"<p class='note'>Линейная регрессия «цена ~ индекс комфорта», R² = {data['forecast_r2']}. "
        "Низкий R² означает, что цена зависит и от других факторов (класс, локация, год) — прогноз ориентировочный.</p>",
        _table(["ЖК", "Цена", "Прогноз", "Отклонение", "Вывод"],
               [[f["name"], _money(f["actual"]), _money(f["predicted"]), f"{f['deviation_pct']:+.1f}%", f["verdict"]] for f in data["forecast"]]),
        "<h2>7. Все ЖК</h2>",
        _table(["ЖК", "Район", "Класс", "Цена", "Индекс", "Оценка", "Отзывов"],
               [[r["name"], r["district"], r["housing_class"], _money(r["price"]), r["index"], r["rating"], r["reviews"]] for r in data["rows"]]),
        "<p class='note'>Индекс комфорта рассчитан по отзывам. Отзывы с источником «Демо-данные» созданы для презентации "
        "и не являются реальными мнениями жителей.</p>",
        "</body></html>",
    ]
    return "".join(parts)


def save_csv(data: dict, path: Path) -> Path:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ЖК", "Район", "Класс", "Цена, ₸", "Индекс комфорта", "Средняя оценка", "Отзывов",
                    "Транспорт", "Тишина", "Двор", "Безопасность", "Сервис", "Место WSM", "Место TOPSIS"])
        wsm = {x["name"]: x["rank"] for x in data["wsm"]}
        tps = {x["name"]: x["rank"] for x in data["topsis"]}
        for r in data["rows"]:
            c = r["categories"]
            w.writerow([r["name"], r["district"], r["housing_class"], r["price"], r["index"], r["rating"], r["reviews"],
                        c.get("Транспорт", ""), c.get("Тишина", ""), c.get("Двор", ""), c.get("Безопасность", ""), c.get("Сервис", ""),
                        wsm.get(r["name"], ""), tps.get(r["name"], "")])
    return Path(path)


def save_json(data: dict, path: Path) -> Path:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return Path(path)


def save_pdf(html_text: str, path: Path) -> Path:
    """Нужен запущенный QApplication (Qt-печать)."""
    from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(110)
    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.print_(writer)
    return Path(path)


def save_report(data: dict, path: Path) -> Path:
    """Сохраняет отчёт в формат по расширению: .html, .pdf, .csv, .json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    if ext == ".csv":
        return save_csv(data, path)
    if ext == ".json":
        return save_json(data, path)
    html_text = render_html(data)
    if ext == ".pdf":
        return save_pdf(html_text, path)
    path.write_text(html_text, encoding="utf-8")
    return path


def default_report_path(ext: str = "html") -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR / f"HouseCheck-report-{datetime.now():%Y%m%d-%H%M}.{ext}"
