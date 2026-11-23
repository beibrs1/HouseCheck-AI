"""Проверка вводимых данных: e-mail, пароль, ФИО, логин, ЖК, отзывы.

Каждая функция возвращает текст ошибки на русском или пустую строку, если всё верно.
Одни и те же правила используются в окнах интерфейса и в базе данных.
"""

from __future__ import annotations

import re
import urllib.parse

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,32}$")
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁёӘәІіҢңҒғҮүҰұҚқӨөҺһ\-\s'.]{2,80}$")

# Границы Астаны с запасом: всё, что вне прямоугольника, — явная ошибка ввода.
ASTANA_BOUNDS = (50.95, 51.35, 71.10, 71.80)  # lat_min, lat_max, lng_min, lng_max


def email_error(email: str) -> str:
    email = (email or "").strip()
    if not email:
        return "Укажите электронную почту."
    if len(email) > 254:
        return "Адрес почты слишком длинный."
    if not EMAIL_RE.match(email) or ".." in email:
        return "Неверный формат почты. Пример: name@mail.kz"
    return ""


def password_error(password: str, repeat: str | None = None) -> str:
    password = password or ""
    if len(password) < 8:
        return "Пароль должен содержать минимум 8 символов."
    if not re.search(r"[A-Za-zА-Яа-я]", password) or not re.search(r"\d", password):
        return "Пароль должен содержать хотя бы одну букву и одну цифру."
    if repeat is not None and password != repeat:
        return "Пароли не совпадают."
    return ""


def username_error(username: str) -> str:
    if not USERNAME_RE.match((username or "").strip()):
        return "Логин: 3–32 символа, латинские буквы, цифры, «_» или «.»."
    return ""


def full_name_error(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "Укажите имя и фамилию."
    if not NAME_RE.match(name):
        return "Имя может содержать только буквы, пробел, дефис и апостроф (2–80 символов)."
    return ""


def phone_error(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if phone and not 10 <= len(digits) <= 12:
        return "Телефон: 10–12 цифр, например +7 701 123 45 67."
    return ""


def development_errors(item: dict) -> list[str]:
    """Проверка записи ЖК перед сохранением в базу."""
    errors: list[str] = []
    if not str(item.get("name", "")).strip():
        errors.append("Не заполнено название ЖК.")
    try:
        lat, lng = float(item.get("lat", 0)), float(item.get("lng", 0))
        lat_min, lat_max, lng_min, lng_max = ASTANA_BOUNDS
        if not (lat_min <= lat <= lat_max and lng_min <= lng <= lng_max):
            errors.append("Координаты находятся за пределами Астаны.")
    except (TypeError, ValueError):
        errors.append("Координаты должны быть числами.")
    for key, title in (("rental_price", "аренды"), ("purchase_price", "покупки"), ("price_from", "цены")):
        try:
            if int(item.get(key, 0) or 0) < 0:
                errors.append(f"Значение {title} не может быть отрицательным.")
        except (TypeError, ValueError):
            errors.append(f"Значение {title} должно быть целым числом.")
    for key in ("google_maps_url", "two_gis_url"):
        value = str(item.get(key, "") or "").strip()
        if value and urllib.parse.urlparse(value).scheme not in {"http", "https"}:
            errors.append(f"Ссылка {key} должна начинаться с http:// или https://.")
    return errors


def review_errors(rating, text: str) -> list[str]:
    errors: list[str] = []
    try:
        if not 1 <= int(rating) <= 5:
            errors.append("Оценка должна быть от 1 до 5.")
    except (TypeError, ValueError):
        errors.append("Оценка должна быть числом от 1 до 5.")
    if not str(text or "").strip():
        errors.append("Текст отзыва пустой.")
    return errors
