from __future__ import annotations

import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, QSequentialAnimationGroup, QSize, Qt,
    QThread, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import icons
from analyzer import AnalysisResult
from features import FeaturePages, ForgotPasswordDialog, RegisterDialog, SessionGuard
from assistant_engine import CATS, ClaudeEngine, LocalEngine, personal_score
from astana_map import AstanaMap
from database import Database
from demo_data import DEMO_SOURCE
from google_places import GooglePlacesError, get_place_details, normalize_reviews, search_place
from i18n import tr
from mascot import Mascot
from theme_tokens import T, load_theme_stylesheet, set_theme
from ui_kit import (
    AnimatedStack, Avatar, Badge, Button, C, Card, Chip, CountLabel, Cover, Divider, IconBubble, IconButton,
    MeterBar, ResponsiveGrid, ScoreRing, SearchBox, Segmented, Stars, _Hover, _mix, clear_layout, fade_in, font,
    hbox, label, money, score_color, toast, vbox,
)

CRITERIA = ["Тишина", "Транспорт", "Зелень и воздух", "Безопасность", "Парковка", "Двор и условия для детей", "Школы и детские сады", "Магазины", "Дом и инженерные коммуникации", "Управление домом", "Доступная среда", "Интернет и связь"]
CRITERIA_ICONS = {"Тишина": "volume", "Транспорт": "bus", "Зелень и воздух": "tree", "Безопасность": "shield", "Парковка": "layers", "Двор и условия для детей": "home", "Школы и детские сады": "building", "Магазины": "wallet", "Дом и инженерные коммуникации": "wrench", "Управление домом": "settings", "Доступная среда": "users", "Интернет и связь": "globe"}
CAT_ICONS = {"Транспорт": "bus", "Тишина": "volume", "Двор": "tree", "Безопасность": "shield", "Сервис": "wrench"}
CAT_NAMES = {
    "ru": {"Транспорт": "Транспорт", "Тишина": "Тишина", "Двор": "Двор", "Безопасность": "Безопасность", "Сервис": "Сервис УК"},
    "kk": {"Транспорт": "Көлік", "Тишина": "Тыныштық", "Двор": "Аула", "Безопасность": "Қауіпсіздік", "Сервис": "Қызмет"},
    "en": {"Транспорт": "Transport", "Тишина": "Quietness", "Двор": "Courtyard", "Безопасность": "Safety", "Сервис": "Management"},
}
PRESETS = [
    ("preset_family", "users", {"Тишина": 4, "Школы и детские сады": 5, "Безопасность": 5, "Двор и условия для детей": 5, "Парковка": 3}),
    ("preset_remote", "monitor", {"Тишина": 5, "Интернет и связь": 5, "Зелень и воздух": 3, "Транспорт": 2}),
    ("preset_student", "bus", {"Транспорт": 5, "Магазины": 4, "Интернет и связь": 4}),
    ("preset_calm", "tree", {"Тишина": 5, "Зелень и воздух": 5, "Управление домом": 4, "Доступная среда": 4}),
    ("preset_base", "sliders", {}),
]
IS_MAC = sys.platform == "darwin"


# ───────────────────────── Dialogs & workers (логика сохранена) ─────────────────────────

class LoginDialog(QDialog):
    def __init__(self, db: Database, lang: str = "ru"):
        super().__init__()
        self.db = db
        self.lang = lang
        self.user: dict | None = None
        self.setWindowTitle("HouseCheck AI — вход")
        self.setFixedSize(920, 580)
        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        left = _LoginArt(); left.setFixedWidth(430)
        ll = QVBoxLayout(left); ll.setContentsMargins(44, 44, 44, 40); ll.setSpacing(14)
        ll.addLayout(hbox(_BrandMark(40), label("HouseCheck AI", 18, "#FFFFFF", 800), None, spacing=12))
        ll.addStretch()
        self.mascot = Mascot(170); self.mascot.set_mood("happy")
        ll.addWidget(self.mascot, 0, Qt.AlignLeft)
        ll.addWidget(label(tr("tagline", lang), 30, "#FFFFFF", 800))
        for i, key in enumerate(["feat1", "feat2", "feat3"]):
            row = hbox(IconBubble(["star", "map", "sparkle"][i], "#2B3A6B", "#FFB37A", 30), label(tr(key, lang), 13, "#C9D2E6", 500), None, spacing=12)
            ll.addLayout(row)
        root.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(64, 70, 64, 50); rl.setSpacing(10)
        rl.addWidget(label(tr("login_title", lang), 30, "text", 800))
        rl.addWidget(label(tr("login_sub", lang), 14, "text_muted"))
        rl.addSpacing(22)
        rl.addWidget(label(tr("username", lang), 12, "text_muted", 700))
        self.username = QLineEdit("super_admin"); self.username.setFixedHeight(48)
        rl.addWidget(self.username)
        rl.addSpacing(6)
        rl.addWidget(label(tr("password", lang), 12, "text_muted", 700))
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password); self.password.setPlaceholderText("super_admin"); self.password.setFixedHeight(48)
        rl.addWidget(self.password)
        self.error = label("", 12, "danger", 600); self.error.setFixedHeight(20)
        rl.addWidget(self.error)
        login = Button(tr("sign_in", lang), "primary", "next", "lg"); login.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        login.clicked.connect(self.try_login)
        self.password.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(self.password.setFocus)
        rl.addWidget(login)
        links = QHBoxLayout(); links.setSpacing(4)
        reg = Button(tr("register", lang), "ghost", "user", "sm"); reg.clicked.connect(self.open_register)
        forgot = Button(tr("forgot", lang), "ghost", "lock", "sm"); forgot.clicked.connect(self.open_forgot)
        links.addWidget(reg); links.addStretch(); links.addWidget(forgot)
        rl.addLayout(links)
        rl.addWidget(label(tr("first_login", lang), 12, "text_soft"))
        rl.addStretch()
        root.addWidget(right, 1)
        self.form = right
        QTimer.singleShot(0, self.password.setFocus)

    def open_register(self):
        d = RegisterDialog(self.db, self)
        if d.exec() == QDialog.DialogCode.Accepted and d.user:
            self.user = d.user
            self.db.log(d.user, "Вход", d.user["username"], "Вход после регистрации")
            self.accept()

    def open_forgot(self):
        login = self.username.text().strip()
        if ForgotPasswordDialog(self.db, login if "@" in login else "", self).exec() == QDialog.DialogCode.Accepted:
            self.password.clear(); self.password.setFocus()

    def try_login(self):
        if not self.username.text().strip() or not self.password.text():
            self.error.setText(tr("login_empty", self.lang)); self._shake(); return
        user = self.db.authenticate(self.username.text(), self.password.text())
        if not user:
            self.db.log({"username": self.username.text().strip()}, "Неудачный вход", self.username.text().strip(), "Неверный логин или пароль")
            self.error.setText(tr("login_error", self.lang))
            self.mascot.set_mood("think")
            self._shake()
            return
        self.user = user
        self.db.log(user, "Вход", user["username"], "Успешный вход")
        self.mascot.set_mood("happy")
        self.accept()

    def _shake(self):
        group = QSequentialAnimationGroup(self)
        base = self.form.pos()
        for dx in (14, -12, 9, -6, 3, 0):
            a = QPropertyAnimation(self.form, b"pos"); a.setDuration(45); a.setEndValue(base + QPoint(dx, 0)); group.addAnimation(a)
        group.start()


class _LoginArt(QWidget):
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#22305A")); g.setColorAt(1, QColor("#0F1730"))
        p.fillRect(self.rect(), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(242, 138, 60, 40)); p.drawEllipse(QPoint(self.width() - 40, 90), 160, 160)
        p.setBrush(QColor(185, 243, 107, 22)); p.drawEllipse(QPoint(60, self.height() - 30), 120, 120)


class _BrandMark(QWidget):
    def __init__(self, size=38):
        super().__init__(); self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, self.width(), self.height()); g.setColorAt(0, QColor("#FFB37A")); g.setColorAt(1, QColor("#F28A3C"))
        path = QPainterPath(); path.addRoundedRect(QRectF(self.rect()), 12, 12); p.fillPath(path, g)
        s = self.width() * 0.56
        icons.paint(p, "home", "#FFFFFF", QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s), 2.4)


class UserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый пользователь")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 24, 26, 20); layout.setSpacing(14)
        layout.addWidget(label("Новый пользователь", 20, "text", 800))
        form = QFormLayout(); form.setSpacing(10)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.role = QComboBox()
        self.role.addItems(["viewer", "analyst", "editor", "super_admin"])
        form.addRow("Логин", self.username); form.addRow("Пароль", self.password); form.addRow("Роль", self.role)
        layout.addLayout(form)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept_checked); box.rejected.connect(self.reject); layout.addWidget(box)

    def accept_checked(self):
        username = self.username.text().strip()
        if len(username) < 3 or not username.replace("_", "").isalnum() or not self.password.text():
            QMessageBox.warning(self, "Проверь данные", "Логин: минимум 3 латинских символа, пароль не должен быть пустым.")
            return
        if len(self.password.text()) < 8:
            QMessageBox.warning(self, "Слабый пароль", "Пароль должен содержать минимум 8 символов.")
            return
        if not self.role.currentText():
            QMessageBox.warning(self, "Не хватает данных", "Укажи логин и пароль.")
            return
        self.accept()


class GoogleReviewWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    @Slot()
    def run(self):
        try:
            places = search_place(self.query)
            if not places:
                raise GooglePlacesError("Google Places не нашёл подходящее место. Проверьте название и адрес.")
            place = get_place_details(places[0]["id"])
            self.finished.emit((place, normalize_reviews(place)))
        except Exception as error:
            self.failed.emit(str(error))


class ClaudeWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: ClaudeEngine, history: list[dict], context: str, lang: str):
        super().__init__()
        self.engine, self.history, self.context, self.lang = engine, history, context, lang

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.engine.ask(self.history, self.context, self.lang))
        except Exception as error:
            self.failed.emit(str(error))


class DevelopmentDialog(QDialog):
    def __init__(self, parent=None, item: dict | None = None):
        super().__init__(parent)
        self.item = item or {}
        self.setWindowTitle("Добавить ЖК" if not item else "Редактировать ЖК")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 20); layout.setSpacing(12)
        layout.addWidget(label("Данные жилого комплекса", 22, "text", 800))
        layout.addWidget(label("Поля со * обязательны. Город фиксирован: Астана.", 12, "text_muted"))
        form = QFormLayout(); form.setSpacing(10); form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit(self.item.get("name", "")); self.city = QLineEdit(self.item.get("city", "Астана")); self.city.setReadOnly(True)
        self.district = QLineEdit(self.item.get("district", "")); self.address = QLineEdit(self.item.get("address", ""))
        self.deal = QComboBox(); self.deal.addItems(["Аренда", "Покупка"]); self.deal.setCurrentText(self.item.get("deal_type", "Покупка"))
        self.rent = QSpinBox(); self.rent.setRange(0, 2_000_000_000); self.rent.setGroupSeparatorShown(True); self.rent.setValue(int(self.item.get("rental_price", 0) or 0))
        self.purchase = QSpinBox(); self.purchase.setRange(0, 2_000_000_000); self.purchase.setGroupSeparatorShown(True); self.purchase.setValue(int(self.item.get("purchase_price", 0) or 0))
        self.lat = QLineEdit(str(self.item.get("lat", "51.1694"))); self.lng = QLineEdit(str(self.item.get("lng", "71.4491")))
        self.maps = QLineEdit(self.item.get("google_maps_url", "")); self.gis = QLineEdit(self.item.get("two_gis_url", ""))
        self.notes = QPlainTextEdit(self.item.get("notes", "")); self.notes.setFixedHeight(70)
        for name, widget in [("Название *", self.name), ("Город *", self.city), ("Район", self.district), ("Адрес", self.address), ("Цель", self.deal), ("Аренда, ₸/мес.", self.rent), ("Покупка, ₸", self.purchase), ("Широта", self.lat), ("Долгота", self.lng), ("Google Maps URL", self.maps), ("2GIS URL", self.gis), ("Заметка", self.notes)]:
            form.addRow(name, widget)
        layout.addLayout(form)
        layout.addWidget(label("Отзывы добавляются из Google Places API, импортированного файла или демо-набора (с пометкой источника).", 12, "text_muted"))
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept_checked); box.rejected.connect(self.reject); layout.addWidget(box)

    def accept_checked(self):
        if not self.name.text().strip() or not self.city.text().strip():
            QMessageBox.warning(self, "Не хватает данных", "Заполни название ЖК и город."); return
        try:
            lat = float(self.lat.text().replace(",", ".")); lng = float(self.lng.text().replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, "Неверные координаты", "Широта и долгота должны быть числами."); return
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            QMessageBox.warning(self, "Неверные координаты", "Широта: от -90 до 90, долгота: от -180 до 180."); return
        for field_name, value in [("Google Maps URL", self.maps.text().strip()), ("2GIS URL", self.gis.text().strip())]:
            if value and urllib.parse.urlparse(value).scheme not in {"http", "https"}:
                QMessageBox.warning(self, "Неверная ссылка", f"{field_name} должна начинаться с http:// или https://."); return
        self.accept()

    def values(self) -> dict:
        try: lat, lng = float(self.lat.text().replace(",", ".")), float(self.lng.text().replace(",", "."))
        except ValueError: lat, lng = 51.1694, 71.4491
        rent, purchase = self.rent.value(), self.purchase.value()
        return {"name": self.name.text().strip(), "city": self.city.text().strip(), "district": self.district.text().strip(), "address": self.address.text().strip(), "deal_type": self.deal.currentText(), "rental_price": rent, "purchase_price": purchase, "price_from": rent if self.deal.currentText() == "Аренда" else purchase, "lat": lat, "lng": lng, "google_maps_url": self.maps.text().strip(), "two_gis_url": self.gis.text().strip(), "notes": self.notes.toPlainText().strip()}


# ───────────────────────── Shell widgets ─────────────────────────

class NavButton(QPushButton, _Hover):
    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__(text, parent)
        self.icon_name = icon_name
        self.badge = 0
        self.setCheckable(True)
        self._active = 0.0
        self._init_hover()
        from PySide6.QtCore import QVariantAnimation
        self._act = QVariantAnimation(self); self._act.setDuration(260); self._act.setEasingCurve(QEasingCurve.OutCubic)
        self._act.valueChanged.connect(lambda v: (setattr(self, "_active", float(v)), self.update()))
        self.toggled.connect(lambda on: (self._act.stop(), self._act.setStartValue(self._active), self._act.setEndValue(1.0 if on else 0.0), self._act.start()))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setFont(font(13, 600))

    def enterEvent(self, e): self._animate_hover(1.0); super().enterEvent(e)
    def leaveEvent(self, e): self._animate_hover(0.0); super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        bg = QColor(255, 255, 255, int(14 * self._hover + 4 * self._active))
        path = QPainterPath(); path.addRoundedRect(r, 14, 14); p.fillPath(path, bg)
        if self._active > 0:
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(r.topLeft(), r.topRight())
            a = QColor(T["accent"]); a.setAlpha(int(255 * self._active)); b = QColor(T["accent_glow"]); b.setAlpha(int(255 * self._active))
            g.setColorAt(0, a); g.setColorAt(1, b)
            w = r.width() * (0.3 + 0.7 * self._active)
            ap = QPainterPath(); ap.addRoundedRect(QRectF(r.left(), r.top(), w, r.height()), 14, 14); p.fillPath(ap, g)
        fg = _mix(QColor(T["nav_muted"]), QColor("#FFFFFF"), max(self._hover * 0.7, self._active))
        icons.paint(p, self.icon_name, fg.name(), QRectF(r.left() + 14, r.center().y() - 10, 20, 20))
        p.setPen(fg); p.setFont(self.font())
        p.drawText(QRectF(r.left() + 46, r.top(), r.width() - 80, r.height()), Qt.AlignVCenter, self.text())
        if self.badge:
            br = QRectF(r.right() - 34, r.center().y() - 10, 24, 20)
            bp = QPainterPath(); bp.addRoundedRect(br, 10, 10)
            p.fillPath(bp, QColor("#FFFFFF") if self._active > 0.5 else QColor(T["accent"]))
            p.setPen(QColor(T["accent"]) if self._active > 0.5 else QColor("#FFFFFF")); p.setFont(font(11, 800))
            p.drawText(br, Qt.AlignCenter, str(self.badge))


class Sidebar(QFrame):
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(0, 0, 0, self.height()); g.setColorAt(0, QColor(T["nav2"])); g.setColorAt(1, QColor(T["nav"]))
        p.fillRect(self.rect(), g)
        p.setPen(Qt.NoPen); p.setBrush(QColor(242, 138, 60, 26)); p.drawEllipse(QPoint(self.width(), 0), 140, 140)


class TopBar(QFrame):
    def paintEvent(self, _):
        p = QPainter(self)
        c = QColor(T["bg"]); c.setAlpha(235)
        p.fillRect(self.rect(), c)
        p.setPen(QColor(T["border"])); p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class FloatingDomi(QWidget):
    clicked = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedSize(300, 104)
        self.mascot = Mascot(84, self, interactive=True)
        self.mascot.move(self.width() - 92, 14)
        self.mascot.clicked.connect(self.clicked.emit)
        self._bubble = 0.0
        from PySide6.QtCore import QVariantAnimation
        self._anim = QVariantAnimation(self); self._anim.setDuration(320); self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_bubble", float(v)), self.update()))
        self._cycle = QTimer(self); self._cycle.timeout.connect(self._pulse); self._cycle.start(9000)
        QTimer.singleShot(1800, self._pulse)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _pulse(self):
        if not self.isVisible():
            return
        self.show_bubble(True)
        QTimer.singleShot(3800, lambda: self.show_bubble(False))

    def show_bubble(self, on: bool):
        try:
            self._anim.stop(); self._anim.setStartValue(self._bubble); self._anim.setEndValue(1.0 if on else 0.0); self._anim.start()
        except RuntimeError:
            pass

    def mousePressEvent(self, e):
        if self._bubble > 0.3:
            self.clicked.emit()

    def paintEvent(self, _):
        if self._bubble <= 0.01:
            return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(min(1.0, self._bubble))
        f = font(12, 700); fm = QFontMetrics(f)
        w = fm.horizontalAdvance(self.text) + 28
        r = QRectF(self.width() - 96 - w, 22, w, 38)
        r.translate(12 * (1 - self._bubble), 0)
        path = QPainterPath(); path.addRoundedRect(r, 19, 19)
        tail = QPainterPath(); tail.moveTo(r.right() - 4, r.center().y() - 6); tail.lineTo(r.right() + 10, r.center().y() + 4); tail.lineTo(r.right() - 6, r.center().y() + 8)
        p.fillPath(path.united(tail), QColor(T["nav"]))
        p.setPen(QColor("#FFFFFF")); p.setFont(f); p.drawText(r, Qt.AlignCenter, self.text)


class ChatBubble(QFrame):
    def __init__(self, text: str, mine: bool, parent=None):
        super().__init__(parent)
        self.mine = mine
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 12, 18, 12)
        self.label = QLabel(text); self.label.setWordWrap(True); self.label.setTextFormat(Qt.PlainText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setFont(font(14, 500))
        self.label.setStyleSheet(f"color:{'#FFFFFF' if mine else T['text']};background:transparent;")
        self.label.setMaximumWidth(560)
        lay.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(r, 20, 20)
        corner = QPainterPath()
        if self.mine:
            corner.addRoundedRect(QRectF(r.right() - 22, r.bottom() - 22, 22, 22), 6, 6)
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(r.topLeft(), r.bottomRight()); g.setColorAt(0, QColor(T["accent_glow"])); g.setColorAt(1, QColor(T["accent"]))
            p.fillPath(path.united(corner), g)
        else:
            corner.addRoundedRect(QRectF(r.left(), r.bottom() - 22, 22, 22), 6, 6)
            full = path.united(corner)
            p.fillPath(full, QColor(T["surface"]))
            p.setPen(QColor(T["border"])); p.drawPath(full)


class TypingBubble(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 44)
        self._t = 0.0
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick); self._timer.start(30)

    def _tick(self):
        self._t += 0.03; self.update()

    def paintEvent(self, _):
        import math
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(r, 20, 20)
        p.fillPath(path, QColor(T["surface"])); p.setPen(QColor(T["border"])); p.drawPath(path)
        p.setPen(Qt.NoPen)
        for i in range(3):
            y = r.center().y() - 4 * max(0.0, math.sin(self._t * 7 - i * 0.7))
            c = QColor(T["accent"]); c.setAlpha(140 + int(115 * max(0.0, math.sin(self._t * 7 - i * 0.7))))
            p.setBrush(c); p.drawEllipse(QPoint(int(r.center().x() - 14 + i * 14), int(y)), 4, 4)


class Palette(QWidget):
    """Командная палитра (⌘K / Ctrl+K): поиск по ЖК, разделам и действиям."""

    def __init__(self, window: "HouseCheckWindow"):
        super().__init__(window.centralWidget())
        self.win = window
        self.setGeometry(window.centralWidget().rect())
        self.card = Card("surface", 26, hover=False, parent=self)
        self.card.setFixedWidth(640)
        lay = self.card.layout_(); self.card.set_padding(16, 16, 16, 14)
        self.search = SearchBox(tr("palette_ph", window.language), "Esc", 50)
        lay.addWidget(self.search)
        self.list = QListWidget(); self.list.setObjectName("palette"); self.list.setIconSize(QSize(20, 20)); self.list.setFixedHeight(300)
        self.list.setFont(font(14, 500))
        lay.addWidget(self.list)
        self.search.edit.textChanged.connect(self.populate)
        self.search.edit.installEventFilter(self)
        self.list.itemActivated.connect(self.activate)
        self.list.itemClicked.connect(self.activate)
        self.populate("")
        self.card.move((self.width() - self.card.width()) // 2, 90)
        self.card.adjustSize()
        eff = QGraphicsOpacityEffect(self); self.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", self); a.setDuration(180); a.setStartValue(0.0); a.setEndValue(1.0)
        a.finished.connect(lambda: self.setGraphicsEffect(None)); a.start()
        s = QPropertyAnimation(self.card, b"pos", self); s.setDuration(260); s.setStartValue(self.card.pos() + QPoint(0, -16)); s.setEndValue(self.card.pos()); s.setEasingCurve(QEasingCurve.OutCubic); s.start()
        self.show(); self.raise_()
        self.search.edit.setFocus()

    def paintEvent(self, _):
        p = QPainter(self); p.fillRect(self.rect(), QColor(10, 15, 31, 120))

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close_()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.KeyPress:
            k = e.key()
            if k == Qt.Key_Escape:
                self.close_(); return True
            if k in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                while 0 <= row < self.list.count() and not (self.list.item(row).flags() & Qt.ItemIsSelectable):
                    row += 1 if k == Qt.Key_Down else -1
                if 0 <= row < self.list.count():
                    self.list.setCurrentRow(row)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem():
                    self.activate(self.list.currentItem())
                return True
        return False

    def _header(self, text):
        it = QListWidgetItem(text.upper()); it.setFlags(Qt.NoItemFlags); it.setFont(font(11, 800)); it.setForeground(QColor(T["text_soft"]))
        self.list.addItem(it)

    def populate(self, query: str):
        q = query.strip().lower()
        self.list.clear()
        w = self.win
        devs = [d for d in w.db.developments(query)] if q else w.db.developments()[:6]
        if devs:
            self._header(tr("nav_catalog", w.language))
            for d in devs[:8]:
                a = w.db.analysis_for(d["id"])
                it = QListWidgetItem(icons.icon("building", T["accent"]), f"{d['name']}    ·    {d.get('district') or 'Астана'}    ·    {a.overall or '—'}/100")
                it.setData(Qt.UserRole, ("dev", d["id"])); self.list.addItem(it)
        pages = [(k, tr("nav_" + k, w.language), ic) for k, ic in w.NAV if k in w.pages]
        pages = [x for x in pages if not q or q in x[1].lower()]
        if pages:
            self._header(tr("pages", w.language))
            for k, text, ic in pages:
                it = QListWidgetItem(icons.icon(ic, T["text_muted"]), text); it.setData(Qt.UserRole, ("page", k)); self.list.addItem(it)
        if q and len(q) > 2:
            self._header(tr("nav_assistant", w.language))
            it = QListWidgetItem(icons.icon("sparkle", T["accent"]), f"{tr('hero_ask', w.language)}: «{query}»"); it.setData(Qt.UserRole, ("ask", query)); self.list.addItem(it)
        self.list.setFixedHeight(min(380, max(60, self.list.count() * 44 + 8)))
        self.card.adjustSize()
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemIsSelectable:
                self.list.setCurrentRow(i); break

    def activate(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        kind, value = data
        self.close_()
        if kind == "dev":
            self.win.open_detail(int(value))
        elif kind == "page":
            self.win.show_page(value)
        elif kind == "ask":
            self.win.show_page("assistant"); self.win.ask(value)

    def close_(self):
        self.win._palette = None
        self.deleteLater()


# ───────────────────────── Main window ─────────────────────────

class HouseCheckWindow(FeaturePages, QMainWindow):
    NAV = [("home", "home"), ("catalog", "grid"), ("map", "map"), ("favorites", "heart"), ("compare", "compare"), ("comfort", "sliders"), ("analytics", "chart"), ("assistant", "sparkle")]
    CAT_NAMES = CAT_NAMES
    logged_out = Signal()

    def __init__(self, db: Database | None = None, user: dict | None = None, language: str = "ru"):
        super().__init__()
        self.db = db or Database(); self.user = user or {"username": "super_admin", "role": "super_admin"}
        self.current_id = None; self.compare_ids: set[int] = set(); self.language = language; self.theme = "light"
        self.current_page = "home"; self.price_mode = 0; self.sort_index = 0; self.district_filter = ""; self.class_filter = ""
        self.chat: list[dict] = []
        self.local_ai = LocalEngine(self.db); self.claude = ClaudeEngine()
        self._palette = None; self._google_thread = None; self._google_worker = None; self._claude_thread = None
        self.setWindowTitle("HouseCheck AI"); self.resize(1480, 940); self.setMinimumSize(1180, 760)
        self._logging_out = False
        self.build_ui()
        self.guard = SessionGuard(self)
        self._search_log_timer = QTimer(self); self._search_log_timer.setSingleShot(True); self._search_log_timer.setInterval(1500)
        self._search_log_timer.timeout.connect(self._log_search)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.open_palette)

    # ---------- theme / build ----------
    def styles(self) -> str:
        return load_theme_stylesheet("dark" if self.is_dark_theme() else "light")

    def is_dark_theme(self) -> bool:
        if self.theme == "dark":
            return True
        if self.theme == "system":
            try:
                return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
            except Exception:
                return QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        return False

    def t(self, key: str, **kw) -> str:
        return tr(key, self.language, **kw)

    def build_ui(self):
        set_theme("dark" if self.is_dark_theme() else "light")
        QApplication.instance().setStyleSheet(self.styles())
        self.pages: dict[str, QWidget] = {}; self.nav: dict[str, NavButton] = {}
        root = QWidget(); outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self.sidebar())
        self.area = QWidget(); al = QVBoxLayout(self.area); al.setContentsMargins(0, 0, 0, 0); al.setSpacing(0)
        al.addWidget(self.top_bar())
        self.stack = AnimatedStack(); al.addWidget(self.stack, 1)
        outer.addWidget(self.area, 1)
        old = self.centralWidget()
        self.setCentralWidget(root)
        if old:
            old.deleteLater()
        for builder in [self.build_home, self.build_catalog, self.build_detail, self.build_map, self.build_favorites, self.build_compare, self.build_comfort, self.build_assistant, self.build_reviews, self.build_admin, self.build_analytics, self.build_history, self.build_profile]:
            builder()
        self.domi = FloatingDomi(self.t("ask_me"), self.area); self.domi.clicked.connect(lambda: self.show_page("assistant"))
        self.area.installEventFilter(self)
        self.apply_permissions()
        self.update_badges()
        self.show_page(self.current_page if self.current_page in self.pages else "home", animate=False)
        QTimer.singleShot(0, self._place_floating)

    def eventFilter(self, obj, e):
        if obj is getattr(self, "area", None) and e.type() == QEvent.Resize:
            self._place_floating()
        return super().eventFilter(obj, e)

    def _place_floating(self):
        try:
            self.domi.move(self.area.width() - self.domi.width() - 18, self.area.height() - self.domi.height() - 14)
            self.domi.raise_()
        except (RuntimeError, AttributeError):
            pass

    def rebuild_with_transition(self):
        shot = self.grab()
        overlay = QLabel(self); overlay.setPixmap(shot); overlay.setGeometry(self.rect()); overlay.show(); overlay.raise_()
        self.build_ui()
        overlay.raise_()
        eff = QGraphicsOpacityEffect(overlay); overlay.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", overlay); a.setDuration(420); a.setStartValue(1.0); a.setEndValue(0.0); a.setEasingCurve(QEasingCurve.InOutQuad)
        a.finished.connect(overlay.deleteLater); a.start()

    def sidebar(self):
        s = Sidebar(); s.setFixedWidth(256)
        l = QVBoxLayout(s); l.setContentsMargins(18, 26, 18, 20); l.setSpacing(4)
        brand = hbox(_BrandMark(40), vbox(label("HouseCheck", 17, "#FFFFFF", 800), label("AI · Астана", 11, "nav_muted", 600), spacing=0), None, spacing=12)
        l.addLayout(brand); l.addSpacing(26)
        l.addWidget(label(self.t("sec_work"), 10, "nav_muted", 800)); l.addSpacing(4)
        for key, ic in self.NAV:
            b = NavButton(self.t("nav_" + key), ic); b.clicked.connect(lambda _=False, route=key: self.show_page(route)); self.nav[key] = b; l.addWidget(b)
        l.addSpacing(16)
        l.addWidget(label(self.t("sec_data"), 10, "nav_muted", 800)); l.addSpacing(4)
        b = NavButton(self.t("nav_reviews"), "chat"); b.clicked.connect(lambda: self.show_page("reviews")); self.nav["reviews"] = b; l.addWidget(b)
        b = NavButton(self.t("nav_history"), "history"); b.clicked.connect(lambda: self.show_page("history")); self.nav["history"] = b; l.addWidget(b)
        b = NavButton(self.t("nav_profile"), "user"); b.clicked.connect(lambda: self.show_page("profile")); self.nav["profile"] = b; l.addWidget(b)
        if self.user.get("role") == "super_admin":
            admin = NavButton(self.t("nav_admin"), "settings"); admin.clicked.connect(lambda: self.show_page("admin")); self.nav["admin"] = admin; l.addWidget(admin)
        l.addStretch()
        promo = Card("accent", 22, clickable=True); promo.set_padding(16, 14, 12, 14); promo.clicked.connect(lambda: self.show_page("assistant"))
        m = Mascot(62); m.set_mood("happy")
        promo.layout_().addLayout(hbox(vbox(label(self.t("promo_title"), 13, "#FFFFFF", 800), label(self.t("promo_sub"), 11, "#FFF3E8", 500), spacing=2), None, m, spacing=6))
        l.addWidget(promo)
        l.addSpacing(8)
        note = label(self.t("sidebar_note"), 10, "nav_muted"); l.addWidget(note)

        def fit(e, base=Sidebar.resizeEvent):
            # в невысоком окне прячем промо-карточку, чтобы пункты меню не сжимались
            promo.setVisible(e.size().height() >= 900); note.setVisible(e.size().height() >= 800)
            base(s, e)
        s.resizeEvent = fit
        return s

    def top_bar(self):
        bar = TopBar(); bar.setFixedHeight(72)
        l = QHBoxLayout(bar); l.setContentsMargins(36, 0, 28, 0); l.setSpacing(12)
        self.top_search = SearchBox(self.t("search_ph"), "⌘K" if IS_MAC else "Ctrl K", 46)
        self.top_search.setMaximumWidth(520)
        self.top_search.edit.installEventFilter(self)
        self.top_search.edit.setReadOnly(True)
        self.top_search.edit.mousePressEvent = lambda e: self.open_palette()
        self.top_search.mousePressEvent = lambda e: self.open_palette()
        l.addWidget(self.top_search, 1)
        l.addStretch()
        theme_idx = ["light", "dark", "system"].index(self.theme)
        self.theme_switch = Segmented(["", "", ""], theme_idx, ["sun", "moon", "monitor"])
        self.theme_switch.setToolTip(f"{self.t('light')} / {self.t('dark')} / {self.t('system')}")
        self.theme_switch.changed.connect(self.theme_changed)
        l.addWidget(self.theme_switch)
        self.language_select = Segmented(["RU", "KZ", "EN"], ["ru", "kk", "en"].index(self.language))
        self.language_select.changed.connect(self.language_changed)
        l.addWidget(self.language_select)
        l.addSpacing(6)
        user_box = QFrame(); ul = QHBoxLayout(user_box); ul.setContentsMargins(0, 0, 0, 0); ul.setSpacing(10)
        ul.addWidget(Avatar(self.user.get("full_name") or self.user.get("username", "user").replace("_", " "), 40))
        ul.addLayout(vbox(label(self.user.get("full_name") or self.user.get("username", "user"), 13, "text", 700, False), label(self.user.get("role", "viewer"), 11, "text_muted", 600, False), spacing=0))
        self.role_label = user_box
        user_box.setCursor(Qt.PointingHandCursor); user_box.setToolTip(self.t("nav_profile"))
        user_box.mousePressEvent = lambda e: self.show_page("profile")
        l.addWidget(user_box)
        logout = IconButton("logout", self.t("logout"), "ghost"); logout.clicked.connect(lambda: self.logout()); l.addWidget(logout)
        return bar

    def open_palette(self):
        if self._palette is None:
            self._palette = Palette(self)

    # ---------- page scaffolding ----------
    def new_page(self, key: str, title: str, subtitle: str = "", scroll: bool = True):
        outer = QWidget()
        ol = QVBoxLayout(outer); ol.setContentsMargins(0, 0, 0, 0); ol.setSpacing(0)
        if scroll:
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            inner = QWidget(); sa.setWidget(inner); ol.addWidget(sa)
            outer.scroll = sa
        else:
            inner = QWidget(); ol.addWidget(inner)
        lay = QVBoxLayout(inner); lay.setContentsMargins(26, 24, 26, 120 if scroll else 24); lay.setSpacing(12)
        header = QHBoxLayout(); header.setContentsMargins(10, 0, 10, 4); header.setSpacing(10)
        if title:
            titles = vbox(label(title, 30, "text", 800), label(subtitle, 14, "text_muted") if subtitle else None, spacing=4)
            header.addLayout(titles, 1)
        lay.addLayout(header)
        self.pages[key] = outer; self.stack.addWidget(outer)
        return lay, header, outer

    def section_title(self, title: str, action_text: str = "", action=None):
        row = hbox(label(title, 19, "text", 800, False), None, spacing=8, margins=(10, 10, 10, 0))
        if action_text:
            b = Button(action_text, "ghost", "next", "sm"); b.clicked.connect(action); row.addWidget(b)
        return row

    def empty_state(self, title: str, sub: str, mood: str = "think", action_text: str = "", action=None) -> QWidget:
        c = Card("surface", 28, hover=False); c.set_padding(30, 34, 30, 34)
        m = Mascot(130); m.set_mood(mood)
        lay = c.layout_(); lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(m, 0, Qt.AlignCenter)
        t = label(title, 20, "text", 800); t.setAlignment(Qt.AlignCenter); lay.addWidget(t)
        s = label(sub, 14, "text_muted"); s.setAlignment(Qt.AlignCenter); lay.addWidget(s)
        if action_text:
            b = Button(action_text, "primary", "next"); b.clicked.connect(action); lay.addWidget(b, 0, Qt.AlignCenter)
        return c

    # ---------- reusable cards ----------
    def dev_card(self, item: dict, show_match: bool = True) -> Card:
        a = self.db.analysis_for(item["id"]); n = self.db.review_count(item["id"]); avg = self.db.avg_rating(item["id"])
        card = Card("surface", 24, clickable=True); card.set_padding(12, 12, 12, 14)
        card.selected = item["id"] in self.compare_ids
        card.clicked.connect(lambda i=item["id"]: self.open_detail(i))
        lay = card.layout_(); lay.setSpacing(10)
        cover = Cover(item["name"], 150, 18)
        cl = QHBoxLayout(cover); cl.setContentsMargins(12, 12, 12, 12)
        if item.get("housing_class"):
            cl.addWidget(Badge(item["housing_class"], "#FFFFFF", "#17233F"), 0, Qt.AlignTop)
        cl.addStretch()
        fav = IconButton("heart_fill" if item.get("favorite") else "heart", self.t("fav_add"), "white", "sm")
        if item.get("favorite"):
            fav.variant = "primary"
        fav.clicked.connect(lambda _=False, i=item["id"]: self.toggle_favorite(i))
        cl.addWidget(fav, 0, Qt.AlignTop)
        lay.addWidget(cover)
        ring = ScoreRing(58, 6); ring.set_value(a.overall if n else 0)
        name = label(item["name"], 17, "text", 800)
        addr = label(item.get("address") or item.get("district") or "Адрес не указан", 12, "text_muted")
        lay.addLayout(hbox(vbox(name, addr, spacing=2), ring, spacing=10, stretch_at=0, margins=(6, 0, 4, 0)))
        price_key = "purchase_price" if self.price_mode == 0 else "rental_price"
        price = money(item.get(price_key)) + ("" if self.price_mode == 0 or not item.get(price_key) else " / мес")
        info = hbox(IconBubble("wallet", "accent_soft", "accent", 30), vbox(label(self.t("price_buy") if self.price_mode == 0 else self.t("price_rent"), 10, "text_muted", 600), label(price, 14, "text", 800), spacing=0),
                    None, Stars(avg, 13) if n else label(self.t("no_reviews"), 11, "text_soft"), label(f"{avg:.1f}" if n else "", 12, "text", 700), spacing=8, margins=(6, 0, 6, 0))
        lay.addLayout(info)
        if show_match and any(self.db.preferences().values()) and n:
            m = personal_score(self.db, item["id"], self.db.preferences())
            bar = MeterBar(f"{m}% {self.t('match')}", "sparkle"); bar.set_value(m, 200)
            bar.setFixedHeight(26)
            lay.addWidget(bar)
        foot = QHBoxLayout(); foot.setContentsMargins(4, 4, 4, 0)
        cmp_btn = Chip(self.t("in_compare") if item["id"] in self.compare_ids else self.t("compare_btn"), item["id"] in self.compare_ids, "compare")
        cmp_btn.toggled.connect(lambda on, i=item["id"]: self.compare_changed(i, on))
        foot.addWidget(cmp_btn)
        foot.addWidget(label(self.t("reviews_n", n=n) if n else "", 11, "text_muted", 600))
        foot.addStretch()
        more = Button(self.t("details"), "soft", "next", "sm"); more.clicked.connect(lambda _=False, i=item["id"]: self.open_detail(i)); foot.addWidget(more)
        lay.addLayout(foot)
        return card

    def review_card(self, review: dict, dev_name: str | None = None) -> Card:
        c = Card("surface", 22, hover=True); c.set_padding(16, 14, 16, 14)
        lay = c.layout_(); lay.setSpacing(8)
        top = hbox(Avatar(review["author"], 40), vbox(label(review["author"], 14, "text", 700, False), label(review.get("published_at") or "", 11, "text_muted", 500, False), spacing=0),
                   None, Stars(review["rating"], 14), spacing=10)
        lay.addLayout(top)
        t = label(review["text"], 13, "text", 400); lay.addWidget(t)
        is_demo = review["source"] == DEMO_SOURCE
        tags = hbox(Badge(review["source"], "surface_muted" if is_demo else "positive_soft", "text_muted" if is_demo else "positive", 10), spacing=6)
        if dev_name:
            link = Button(dev_name, "ghost", "building", "sm")
            dev_id = review.get("development_id")
            link.clicked.connect(lambda _=False, i=dev_id: self.open_detail(i))
            tags.addWidget(link)
        tags.addStretch()
        lay.addLayout(tags)
        return c

    def stat_tile(self, icon_name: str, bg: str, fg: str, value, caption: str, suffix: str = "", decimals: int = 0) -> Card:
        c = Card("surface", 22); c.set_padding(18, 16, 18, 16)
        c.layout_().addLayout(hbox(IconBubble(icon_name, bg, fg, 48), vbox(CountLabel(value, 28, "text", suffix, decimals), label(caption, 12, "text_muted", 600), spacing=0), None, spacing=14))
        return c

    # ---------- pages ----------
    def build_home(self):
        lay, header, _ = self.new_page("home", "", "")
        self.home_lay = lay

    def refresh_home(self):
        lay = self.home_lay
        while lay.count() > 1:
            item = lay.takeAt(1)
            if item.widget(): item.widget().deleteLater()
            elif item.layout(): clear_layout(item.layout())
        hour = datetime.now().hour
        greet = self.t("morning" if hour < 12 else "afternoon" if hour < 18 else "evening")
        hero = Card("dark", 30, hover=False); hero.set_padding(34, 30, 24, 26)
        left = vbox(
            Badge("✦  HouseCheck AI · Астана", "#2B3A6B", "#FFB37A", 11),
            label(f"{greet}, {self.user.get('username', '')}!", 32, "#FFFFFF", 800),
            label(self.t("hero_text"), 15, "#C9D2E6", 400), 6, spacing=12)
        ctas = hbox(spacing=10)
        b1 = Button(self.t("hero_cta"), "primary", "search", "lg"); b1.clicked.connect(lambda: self.show_page("catalog"))
        b2 = Button(self.t("hero_ask"), "white", "sparkle", "lg"); b2.clicked.connect(lambda: self.show_page("assistant"))
        ctas.addWidget(b1); ctas.addWidget(b2); ctas.addStretch(); left.addLayout(ctas)
        big = Mascot(190); big.set_mood("happy")
        hero.layout_().addLayout(hbox(left, 20, big, spacing=10, stretch_at=0))
        lay.addWidget(hero); fade_in(hero, 0, 500)

        devs = self.db.developments()
        scores = [self.db.analysis_for(d["id"]).overall for d in devs if self.db.review_count(d["id"])]
        stats = QGridLayout(); stats.setSpacing(4)
        tiles = [
            self.stat_tile("building", "accent_soft", "accent", len(devs), self.t("stat_complexes")),
            self.stat_tile("chat", "sky", "#5B8DEF", self.db.total_reviews(), self.t("stat_reviews")),
            self.stat_tile("trophy", "mint", "positive", sum(scores) / len(scores) if scores else 0, self.t("stat_avg")),
            self.stat_tile("heart", "lilac", "#7B6CF6", len(self.db.favorites()), self.t("stat_fav")),
        ]
        for i, tile in enumerate(tiles):
            stats.addWidget(tile, 0, i); fade_in(tile, 80 + i * 70)
        lay.addLayout(stats)

        lay.addLayout(self.section_title(self.t("for_you"), self.t("see_all"), lambda: self.show_page("catalog")))
        prefs = self.db.preferences()
        ranked = sorted([d for d in devs if self.db.review_count(d["id"])], key=lambda d: personal_score(self.db, d["id"], prefs), reverse=True)[:3]
        grid = ResponsiveGrid(320, 4); lay.addWidget(grid)
        grid.set_items([self.dev_card(d) for d in ranked])

        lay.addLayout(self.section_title(self.t("fresh_reviews"), self.t("see_all"), lambda: self.show_page("reviews")))
        rgrid = ResponsiveGrid(380, 4); lay.addWidget(rgrid)
        rgrid.set_items([self.review_card(r, r["development_name"]) for r in self.db.all_reviews()[:4]])

    def build_catalog(self):
        lay, h, outer = self.new_page("catalog", self.t("nav_catalog"), self.t("catalog_sub"))
        self.import_button = Button(self.t("import"), "secondary", "upload"); self.import_button.clicked.connect(self.import_file); h.addWidget(self.import_button)
        self.add_button = Button(self.t("add"), "primary", "plus"); self.add_button.clicked.connect(self.add_development); h.addWidget(self.add_button)
        bar = Card("surface", 24, hover=False); bar.set_padding(14, 12, 14, 12)
        self.search = SearchBox(self.t("search_ph"), "", 46)
        self.search.edit.textChanged.connect(lambda _: (self._catalog_timer.start(), self._search_log_timer.start()))
        self._catalog_timer = QTimer(self); self._catalog_timer.setSingleShot(True); self._catalog_timer.setInterval(160); self._catalog_timer.timeout.connect(self.refresh_catalog)
        self.price_switch = Segmented([self.t("buy"), self.t("rent")], self.price_mode)
        self.price_switch.changed.connect(lambda i: (setattr(self, "price_mode", i), self.refresh_catalog()))
        self.sort_select = QComboBox(); self.sort_select.addItems([self.t(k) for k in ["sort_comfort", "sort_match", "sort_cheap", "sort_expensive", "sort_reviews", "sort_name"]])
        self.sort_select.setCurrentIndex(self.sort_index); self.sort_select.setFixedHeight(44); self.sort_select.setMinimumWidth(190)
        self.sort_select.currentIndexChanged.connect(lambda i: (setattr(self, "sort_index", i), self.refresh_catalog()))
        bar.layout_().addLayout(hbox(self.search, self.price_switch, self.sort_select, spacing=12, stretch_at=0))
        chips = QHBoxLayout(); chips.setSpacing(8)
        self.district_chips: dict[str, Chip] = {}
        districts = sorted({d.get("district") for d in self.db.developments() if d.get("district")})
        for key in [""] + districts:
            text = self.t("all") if not key else key.replace(" район", "").replace("район ", "")
            c = Chip(text, key == self.district_filter, "pin" if key else None)
            c.clicked.connect(lambda _=False, k=key: self.set_district(k))
            self.district_chips[key] = c; chips.addWidget(c)
        chips.addStretch()
        bar.layout_().addLayout(chips)
        chips = QHBoxLayout(); chips.setSpacing(8)
        chips.addWidget(label(self.t("klass") + ":", 12, "text_muted", 700, False))
        self.class_chips: dict[str, Chip] = {}
        for k in ["Эконом", "Комфорт", "Комфорт+", "Бизнес", "Премиум"]:
            c = Chip(k, k == self.class_filter); c.clicked.connect(lambda _=False, x=k: self.set_class(x)); self.class_chips[k] = c; chips.addWidget(c)
        chips.addStretch()
        bar.layout_().addLayout(chips)
        lay.addWidget(bar)
        self.found_label = label("", 13, "text_muted", 600); self.found_label.setContentsMargins(12, 0, 0, 0)
        lay.addWidget(self.found_label)
        self.catalog_grid = ResponsiveGrid(330, 4); lay.addWidget(self.catalog_grid)
        lay.addStretch()
        # плавающий лоток сравнения
        self.tray = Card("dark", 24, hover=False, parent=outer); self.tray.set_padding(20, 10, 12, 10)
        self.compare_count = label("", 14, "#FFFFFF", 700, False)
        go = Button(self.t("compare_btn"), "primary", "compare"); go.clicked.connect(lambda: self.show_page("compare"))
        clr = Button(self.t("clear"), "white", "close"); clr.clicked.connect(self.clear_compare)
        self.tray.layout_().addLayout(hbox(IconBubble("compare", "#2B3A6B", "#FFB37A", 38), self.compare_count, None, clr, go, spacing=12))
        self.tray.setFixedSize(560, 84); self.tray.hide()
        outer.installEventFilter(self)
        self._tray_parent = outer
        outer.resizeEvent = lambda e, o=outer: self._place_tray()

    def _log_search(self):
        try:
            q = self.search.edit.text().strip()
        except (RuntimeError, AttributeError):
            return
        if len(q) >= 2:
            self.log("Поиск", q, self.found_label.text())

    def _place_tray(self):
        if hasattr(self, "tray"):
            o = self._tray_parent
            self.tray.move((o.width() - self.tray.width()) // 2, o.height() - self.tray.height() - 18)

    def set_district(self, key):
        self.district_filter = key
        for k, c in self.district_chips.items():
            c.blockSignals(True); c.setChecked(k == key); c._toggled(k == key); c.blockSignals(False)
        self.refresh_catalog()

    def set_class(self, key):
        self.class_filter = "" if self.class_filter == key else key
        for k, c in self.class_chips.items():
            c.blockSignals(True); c.setChecked(k == self.class_filter); c._toggled(k == self.class_filter); c.blockSignals(False)
        self.refresh_catalog()

    def refresh_catalog(self, animate: bool = True):
        if not hasattr(self, "catalog_grid"):
            return
        items = self.db.developments(self.search.edit.text())
        if self.district_filter:
            items = [x for x in items if x.get("district") == self.district_filter]
        if self.class_filter:
            items = [x for x in items if x.get("housing_class") == self.class_filter]
        prefs = self.db.preferences()
        price_key = "purchase_price" if self.price_mode == 0 else "rental_price"
        keyf = [
            lambda d: -self.db.analysis_for(d["id"]).overall,
            lambda d: -personal_score(self.db, d["id"], prefs),
            lambda d: (not d.get(price_key), d.get(price_key) or 0),
            lambda d: -(d.get(price_key) or 0),
            lambda d: -self.db.review_count(d["id"]),
            lambda d: d["name"].lower(),
        ][self.sort_index]
        items.sort(key=keyf)
        self.found_label.setText(self.t("found", n=len(items)))
        if items:
            self.catalog_grid.set_items([self.dev_card(d) for d in items], animate)
        else:
            self.catalog_grid.set_items([self.empty_state(self.t("empty_search"), self.t("empty_search_sub"))])
        self.update_tray()
        self.statusBar().hide()

    def update_tray(self):
        if not hasattr(self, "tray"):
            return
        n = len(self.compare_ids)
        self.compare_count.setText(self.t("selected", n=n))
        was = self.tray.isVisible()
        self.tray.setVisible(n > 0 and self.current_page == "catalog")
        if self.tray.isVisible():
            self._place_tray(); self.tray.raise_()
            if not was:
                end = self.tray.pos()
                a = QPropertyAnimation(self.tray, b"pos", self.tray); a.setDuration(380); a.setStartValue(end + QPoint(0, 90)); a.setEndValue(end); a.setEasingCurve(QEasingCurve.OutBack); a.start()
        self.update_badges()

    def build_detail(self):
        lay, h, _ = self.new_page("detail", "", "")
        self.detail_lay = lay

    def render_detail(self):
        if not self.current_id or not hasattr(self, "detail_lay"):
            return
        item = self.db.get_development(self.current_id)
        if not item:
            return
        lay = self.detail_lay
        while lay.count() > 1:
            it = lay.takeAt(1)
            if it.widget(): it.widget().deleteLater()
            elif it.layout(): clear_layout(it.layout())
        reviews = self.db.reviews_for(self.current_id); result: AnalysisResult = self.db.analysis_for(self.current_id)
        prefs = self.db.preferences()
        # hero
        hero = Card("surface", 28, hover=False); hero.set_padding(12, 12, 12, 12)
        cover = Cover(item["name"], 280, 22)
        cl = QVBoxLayout(cover); cl.setContentsMargins(22, 18, 22, 22)
        back = Button(self.t("back"), "white", "back", "sm"); back.clicked.connect(lambda: self.show_page(self._back_page))
        top = hbox(back, None, spacing=8)
        if item.get("housing_class"): top.addWidget(Badge(item["housing_class"], "#FFFFFF", "#17233F", 12))
        if item.get("district"): top.addWidget(Badge(item["district"], "#17233F", "#FFFFFF", 12))
        cl.addLayout(top); cl.addStretch()
        self.detail_title = label(item["name"], 38, "#FFFFFF", 800)
        self.detail_meta = label(" · ".join(x for x in [item.get("city"), item.get("address"), item.get("deal_type")] if x), 14, "#F3F5FA", 500)
        cl.addWidget(self.detail_title); cl.addWidget(self.detail_meta)
        hero.layout_().addWidget(cover)
        actions = hbox(spacing=10, margins=(8, 8, 8, 2))
        self.detail_favorite = Button(self.t("fav_in") if item.get("favorite") else self.t("fav_add"), "primary" if item.get("favorite") else "secondary", "heart_fill" if item.get("favorite") else "heart")
        self.detail_favorite.clicked.connect(self.toggle_current_favorite); actions.addWidget(self.detail_favorite)
        in_cmp = self.current_id in self.compare_ids
        cmpb = Button(self.t("in_compare") if in_cmp else self.t("compare_btn"), "dark" if in_cmp else "secondary", "compare")
        cmpb.clicked.connect(lambda: (self.compare_changed(self.current_id, self.current_id not in self.compare_ids), self.render_detail())); actions.addWidget(cmpb)
        gm = Button("Google Maps", "secondary", "pin"); gm.clicked.connect(lambda: self.open_google_maps()); actions.addWidget(gm)
        if item.get("two_gis_url"):
            g2 = Button("2GIS", "secondary", "external"); g2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(item["two_gis_url"]))); actions.addWidget(g2)
        actions.addStretch()
        self.sync_button = Button(self.t("sync"), "soft", "refresh"); self.sync_button.clicked.connect(self.sync_google_reviews); actions.addWidget(self.sync_button)
        ed = IconButton("edit", self.t("edit")); ed.clicked.connect(self.edit_current); actions.addWidget(ed)
        de = IconButton("trash", self.t("delete"), "danger"); de.clicked.connect(lambda: self.delete_development(self.current_id)); actions.addWidget(de)
        self._detail_manage = [ed, de]
        hero.layout_().addLayout(actions)
        lay.addWidget(hero); fade_in(hero, 0, 380)

        cols = QHBoxLayout(); cols.setSpacing(4)
        left = QVBoxLayout(); left.setSpacing(4); right = QVBoxLayout(); right.setSpacing(4)
        # score card
        sc = Card("dark", 26, hover=False); sc.set_padding(24, 20, 24, 22)
        ring = ScoreRing(124, 12, "/ 100"); ring.on_dark = True; ring.set_value(result.overall if reviews else 0)
        mine = ScoreRing(84, 8, self.t("personal")); mine.on_dark = True; mine.set_value(personal_score(self.db, self.current_id, prefs) if reviews else 0)
        self.detail_score = ring
        self.detail_mood = label(f"{result.mood}. " + (f"Оценка рассчитана по {len(reviews)} отзывам." if reviews else "Нет отзывов — оценка не рассчитывается."), 13, "#C9D2E6")
        self.detail_mood.setMinimumWidth(160)
        sc.layout_().addLayout(hbox(ring, mine, None, spacing=14))
        sc.layout_().addWidget(label(self.t("comfort_index"), 18, "#FFFFFF", 800, False))
        sc.layout_().addWidget(self.detail_mood)
        left.addWidget(sc); fade_in(sc, 80)
        cat = Card("surface", 26, hover=False); cat.set_padding(22, 18, 22, 18)
        cat.layout_().addWidget(label(self.t("by_categories"), 17, "text", 800))
        self.bars = {}
        for i, c in enumerate(CATS):
            bar = MeterBar(CAT_NAMES[self.language][c], CAT_ICONS[c]); bar.set_value(result.categories.get(c, 0) if reviews else 0, 150 + i * 90)
            self.bars[c] = bar; cat.layout_().addWidget(bar)
        left.addWidget(cat); fade_in(cat, 140)
        pc = Card("surface", 26, hover=False); pc.set_padding(22, 18, 22, 18)
        pc.layout_().addWidget(label(self.t("pros"), 15, "positive", 800))
        prow = QHBoxLayout(); prow.setSpacing(6)
        for p in (result.pros or ["недостаточно данных"]):
            prow.addWidget(Badge("✓  " + p, "positive_soft", "positive", 12))
        prow.addStretch(); pc.layout_().addLayout(prow)
        pc.layout_().addWidget(label(self.t("cons"), 15, "warning", 800))
        crow = QHBoxLayout(); crow.setSpacing(6)
        for p in (result.cons or ["повторяющихся сигналов нет"]):
            crow.addWidget(Badge("!  " + p, "warning_soft", "warning", 12))
        crow.addStretch(); pc.layout_().addLayout(crow)
        self.pros, self.cons = pc, pc
        left.addWidget(pc); fade_in(pc, 200)
        if reviews:
            ai = self.ai_explanation_card(reviews, result); left.addWidget(ai); fade_in(ai, 230)
        info = Card("surface", 26, hover=False); info.set_padding(22, 18, 22, 18)
        info.layout_().addWidget(label(self.t("about"), 17, "text", 800))
        g = QGridLayout(); g.setHorizontalSpacing(16); g.setVerticalSpacing(14)
        facts = [("klass", "layers", item.get("housing_class") or "—"), ("year", "calendar", str(item.get("year_built") or "—")), ("floors", "building", str(item.get("floors") or "—")),
                 ("units", "home", str(item.get("units") or "—")), ("price_buy", "wallet", money(item.get("purchase_price"))), ("price_rent", "wallet", money(item.get("rental_price")))]
        for i, (k, ic, v) in enumerate(facts):
            g.addLayout(hbox(IconBubble(ic, "surface_muted", "accent", 38), vbox(label(self.t(k), 11, "text_muted", 600), label(v, 15, "text", 800), spacing=0), None, spacing=10), i // 3, i % 3)
        info.layout_().addLayout(g)
        left.addWidget(info); fade_in(info, 260)
        mp = Card("surface", 26, hover=False); mp.set_padding(14, 14, 14, 14)
        mp.layout_().addWidget(label(self.t("location"), 17, "text", 800))
        mini = AstanaMap(); mini.setFixedHeight(260); mini.zoom = 2.2
        mini.set_items([item], {item["id"]: result.overall if reviews else 0}); mini.select(item["id"])
        QTimer.singleShot(0, lambda m=mini, it=item: self._center_map(m, it))
        mini.pin_clicked.connect(lambda _: self.open_google_maps())
        mp.layout_().addWidget(mini)
        self.map_text = label(f"{item.get('address') or 'Адрес не указан'} · {item.get('lat')}, {item.get('lng')}", 12, "text_muted")
        mp.layout_().addWidget(self.map_text)
        left.addWidget(mp)
        left.addStretch()
        # reviews column
        rh = hbox(label(self.t("reviews_title"), 19, "text", 800), Badge(str(len(reviews)), "accent_soft", "accent", 12), None, spacing=8, margins=(10, 8, 10, 4))
        right.addLayout(rh)
        if reviews:
            for i, r in enumerate(reviews):
                w = self.review_card(r); right.addWidget(w); fade_in(w, 120 + i * 50)
        else:
            right.addWidget(self.empty_state(self.t("no_reviews"), "Нажмите «Обновить отзывы Google» или импортируйте файл.", "think"))
        nc = Card("surface", 26, hover=False); nc.set_padding(20, 18, 20, 18)
        nc.layout_().addWidget(label(self.t("notes"), 17, "text", 800))
        self.notes = QPlainTextEdit(); self.notes.setObjectName("note"); self.notes.setPlaceholderText(self.t("notes_ph")); self.notes.setFixedHeight(120)
        self.notes.setPlainText(item.get("notes", "")); self.notes.document().setModified(False)
        nc.layout_().addWidget(self.notes)
        sb = Button(self.t("save_note"), "primary", "check"); sb.clicked.connect(self.save_notes)
        nc.layout_().addLayout(hbox(None, sb))
        right.addWidget(nc)
        right.addStretch()
        cols.addLayout(left, 5); cols.addLayout(right, 6)
        lay.addLayout(cols)
        self.apply_permissions()
        if hasattr(self.pages["detail"], "scroll"):
            self.pages["detail"].scroll.verticalScrollBar().setValue(0)

    def _center_map(self, m: AstanaMap, item):
        pt = m.project(item["lat"], item["lng"])
        m.offset += QPoint(int(m.width() / 2 - pt.x()), int(m.height() / 2 - pt.y() + 20))
        m.update()

    def build_map(self):
        lay, h, _ = self.new_page("map", self.t("nav_map"), self.t("map_sub"), scroll=False)
        row = QHBoxLayout(); row.setSpacing(4)
        mc = Card("surface", 28, hover=False); mc.set_padding(8, 8, 8, 8)
        self.big_map = AstanaMap(); self.big_map.pin_clicked.connect(self.map_select)
        mc.layout_().addWidget(self.big_map)
        row.addWidget(mc, 3)
        side = QVBoxLayout(); side.setSpacing(4)
        self.map_info = Card("dark", 26, hover=False); self.map_info.set_padding(20, 18, 20, 18)
        side.addWidget(self.map_info)
        lc = Card("surface", 26, hover=False); lc.set_padding(10, 12, 10, 12)
        self.map_list = QListWidget(); self.map_list.setObjectName("palette"); self.map_list.setFont(font(13, 600))
        self.map_list.currentItemChanged.connect(lambda cur, _: cur and cur.data(Qt.UserRole) and self.map_select(int(cur.data(Qt.UserRole)), False))
        self.map_list.itemDoubleClicked.connect(self.map_opened)
        lc.layout_().addWidget(self.map_list)
        side.addWidget(lc, 1)
        sw = QWidget(); sw.setLayout(side); sw.setFixedWidth(360)
        row.addWidget(sw)
        lay.addLayout(row, 1)

    def refresh_map(self):
        if not hasattr(self, "big_map"):
            return
        items = self.db.developments()
        scores = {d["id"]: (self.db.analysis_for(d["id"]).overall if self.db.review_count(d["id"]) else 0) for d in items}
        self.big_map.set_items(items, scores)
        self.map_list.blockSignals(True); self.map_list.clear()
        for d in sorted(items, key=lambda x: -scores[x["id"]]):
            it = QListWidgetItem(icons.icon("pin", score_color(scores[d["id"]])), f"{d['name']}   ·   {scores[d['id']] or '—'}")
            it.setData(Qt.UserRole, d["id"]); self.map_list.addItem(it)
        if not items:
            self.map_list.addItem("Нет ЖК. Добавьте комплекс или импортируйте данные.")
        self.map_list.blockSignals(False)
        self.map_select(self.current_id or (items[0]["id"] if items else None), False)

    def map_select(self, dev_id, from_map: bool = True):
        if not dev_id:
            return
        item = self.db.get_development(dev_id)
        if not item:
            return
        self.big_map.select(dev_id)
        a = self.db.analysis_for(dev_id); n = self.db.review_count(dev_id)
        lay = self.map_info.layout_(); clear_layout(lay)
        ring = ScoreRing(86, 8); ring.on_dark = True; ring.set_value(a.overall if n else 0)
        lay.addLayout(hbox(vbox(label(item["name"], 20, "#FFFFFF", 800), label(item.get("address") or item.get("district") or "Астана", 12, "#C9D2E6"), label(self.t("reviews_n", n=n), 12, "#FFB37A", 700), spacing=4), ring, spacing=10, stretch_at=0))
        b1 = Button(self.t("open"), "primary", "next"); b1.clicked.connect(lambda: self.open_detail(dev_id))
        b2 = Button("Google Maps", "white", "external"); b2.clicked.connect(lambda: self.open_google_maps(dev_id))
        lay.addLayout(hbox(b1, b2, None, spacing=8))
        fade_in(self.map_info, 0, 260)
        if from_map:
            for i in range(self.map_list.count()):
                if self.map_list.item(i).data(Qt.UserRole) == dev_id:
                    self.map_list.blockSignals(True); self.map_list.setCurrentRow(i); self.map_list.blockSignals(False)

    def map_opened(self, row: QListWidgetItem):
        if row.data(Qt.UserRole): self.open_detail(int(row.data(Qt.UserRole)))

    def build_favorites(self):
        lay, h, _ = self.new_page("favorites", self.t("nav_favorites"), self.t("fav_sub"))
        self.favorite_grid = ResponsiveGrid(330, 4); lay.addWidget(self.favorite_grid); lay.addStretch()

    def refresh_favorites(self):
        if not hasattr(self, "favorite_grid"): return
        items = self.db.favorites()
        if items:
            self.favorite_grid.set_items([self.dev_card(d) for d in items])
        else:
            self.favorite_grid.set_items([self.empty_state(self.t("fav_empty"), self.t("fav_empty_sub"), "happy", self.t("nav_catalog"), lambda: self.show_page("catalog"))])

    def build_compare(self):
        lay, h, _ = self.new_page("compare", self.t("nav_compare"), self.t("compare_sub"))
        self.compare_layout = QHBoxLayout(); self.compare_layout.setSpacing(4)
        lay.addLayout(self.compare_layout); lay.addStretch()

    def refresh_compare(self):
        if not hasattr(self, "compare_layout"): return
        clear_layout(self.compare_layout)
        items = [x for x in (self.db.get_development(i) for i in self.compare_ids) if x]
        if not items:
            self.compare_layout.addWidget(self.empty_state(self.t("compare_empty"), self.t("compare_empty_sub"), "think", self.t("nav_catalog"), lambda: self.show_page("catalog")))
            return
        analyses = {i["id"]: self.db.analysis_for(i["id"]) for i in items}
        prefs = self.db.preferences()
        metrics = [("comfort_index", lambda d: analyses[d["id"]].overall, True), ("personal", lambda d: personal_score(self.db, d["id"], prefs), True)]
        metrics += [(c, (lambda d, c=c: analyses[d["id"]].categories.get(c, 0)), True) for c in CATS]
        best = {}
        for key, getter, higher in metrics:
            vals = [getter(d) for d in items]
            best[key] = max(vals) if len(items) > 1 else None
        best_price = min((d.get("purchase_price") or 10**12) for d in items) if len(items) > 1 else None
        winner = max(items, key=lambda d: analyses[d["id"]].overall)
        for idx, d in enumerate(items):
            c = Card("surface", 26, hover=True); c.set_padding(12, 12, 12, 16); c.selected = d is winner and len(items) > 1
            l = c.layout_()
            cov = Cover(d["name"], 130, 18); cvl = QHBoxLayout(cov); cvl.setContentsMargins(10, 10, 10, 10)
            if c.selected: cvl.addWidget(Badge("🏆  Лидер", "#FFFFFF", "#17233F", 11), 0, Qt.AlignTop)
            cvl.addStretch()
            rm = IconButton("close", self.t("remove"), "white", "sm"); rm.clicked.connect(lambda _=False, i=d["id"]: (self.compare_changed(i, False), self.refresh_compare())); cvl.addWidget(rm, 0, Qt.AlignTop)
            l.addWidget(cov)
            ring = ScoreRing(96, 9); ring.set_value(analyses[d["id"]].overall)
            l.addLayout(hbox(None, ring, None))
            nm = label(d["name"], 18, "text", 800); nm.setAlignment(Qt.AlignCenter); l.addWidget(nm)
            sub = label(f"{d.get('housing_class') or '—'} · {d.get('district') or 'Астана'}", 12, "text_muted"); sub.setAlignment(Qt.AlignCenter); l.addWidget(sub)
            l.addWidget(Divider())
            for key, getter, _ in metrics:
                v = getter(d)
                name = self.t(key) if key in ("comfort_index", "personal") else CAT_NAMES[self.language][key]
                is_best = best[key] is not None and v == best[key]
                val = label(f"{v}" + ("  ★" if is_best else ""), 14, "positive" if is_best else "text", 800, False)
                l.addLayout(hbox(IconBubble(CAT_ICONS.get(key, "sparkle"), "positive_soft" if is_best else "surface_muted", "positive" if is_best else "text_muted", 30), label(name, 13, "text_muted", 600, False), None, val, spacing=10))
            l.addWidget(Divider())
            for k, field in [("price_buy", "purchase_price"), ("price_rent", "rental_price")]:
                is_best = field == "purchase_price" and best_price is not None and d.get(field) == best_price
                l.addLayout(hbox(label(self.t(k), 13, "text_muted", 600, False), None, label(money(d.get(field)), 14, "positive" if is_best else "text", 800, False)))
            l.addLayout(hbox(label(self.t("nav_reviews"), 13, "text_muted", 600, False), None, label(str(self.db.review_count(d["id"])), 14, "text", 800, False)))
            ob = Button(self.t("details"), "soft", "next"); ob.clicked.connect(lambda _=False, i=d["id"]: self.open_detail(i)); ob.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            l.addWidget(ob)
            self.compare_layout.addWidget(c, 1); fade_in(c, idx * 90)
        if len(items) < 3:
            slot = Card("muted", 26, clickable=True); slot.clicked.connect(lambda: self.show_page("catalog"))
            sl = slot.layout_(); sl.setAlignment(Qt.AlignCenter)
            sl.addWidget(IconBubble("plus", "accent_soft", "accent", 64), 0, Qt.AlignCenter)
            t = label(self.t("add_slot"), 15, "text_muted", 700); t.setAlignment(Qt.AlignCenter); sl.addWidget(t)
            self.compare_layout.addWidget(slot, 1)

    def build_comfort(self):
        lay, h, _ = self.new_page("comfort", self.t("nav_comfort"), self.t("comfort_sub"))
        save = Button(self.t("save_profile"), "primary", "check"); save.clicked.connect(self.save_preferences); h.addWidget(save)
        lay.addLayout(self.section_title(self.t("presets")))
        prow = QHBoxLayout(); prow.setSpacing(4)
        for key, ic, values in PRESETS:
            c = Card("surface", 22, clickable=True); c.set_padding(16, 14, 16, 14)
            c.layout_().addLayout(hbox(IconBubble(ic, "accent_soft", "accent", 40), label(self.t(key), 13, "text", 700), None, spacing=10))
            c.clicked.connect(lambda preset=values: self.apply_profile(preset))
            prow.addWidget(c, 1)
        lay.addLayout(prow)
        row = QHBoxLayout(); row.setSpacing(4)
        box = Card("surface", 26, hover=False); box.set_padding(24, 20, 24, 20)
        box.layout_().addWidget(label(self.t("criteria_title"), 17, "text", 800))
        grid = QGridLayout(); grid.setHorizontalSpacing(28); grid.setVerticalSpacing(14)
        self.sliders = {}; self.preference_labels = {}; prefs = self.db.preferences()
        for i, criterion in enumerate(CRITERIA):
            s = QSlider(Qt.Horizontal); s.setRange(0, 5); s.setValue(prefs.get(criterion, 0)); s.setCursor(Qt.PointingHandCursor)
            out = label(str(s.value()), 15, "accent", 800, False); out.setFixedWidth(20)
            s.valueChanged.connect(lambda value, key=criterion, output=out: self.slider_changed(key, value, output))
            self.sliders[criterion] = s; self.preference_labels[criterion] = out
            cell = vbox(hbox(IconBubble(CRITERIA_ICONS[criterion], "surface_muted", "accent", 30), label(criterion, 13, "text", 600), None, out, spacing=8), s, spacing=6)
            grid.addLayout(cell, i // 2, i % 2)
        box.layout_().addLayout(grid)
        row.addWidget(box, 3)
        self.live_card = Card("dark", 26, hover=False); self.live_card.set_padding(22, 20, 22, 20); self.live_card.setFixedWidth(380)
        row.addWidget(self.live_card, 0, Qt.AlignTop)
        lay.addLayout(row)
        self._live_timer = QTimer(self); self._live_timer.setSingleShot(True); self._live_timer.setInterval(180); self._live_timer.timeout.connect(self.refresh_live_top)
        self.refresh_live_top()

    def current_slider_prefs(self) -> dict[str, int]:
        return {k: s.value() for k, s in self.sliders.items()}

    def refresh_live_top(self):
        if not hasattr(self, "live_card"):
            return
        lay = self.live_card.layout_(); clear_layout(lay)
        m = Mascot(70); m.set_mood("happy")
        lay.addLayout(hbox(vbox(label(self.t("live_top"), 17, "#FFFFFF", 800), label(self.t("for_you_sub"), 12, "#C9D2E6"), spacing=2), None, m))
        prefs = self.current_slider_prefs()
        devs = [d for d in self.db.developments() if self.db.review_count(d["id"])]
        ranked = sorted(devs, key=lambda d: personal_score(self.db, d["id"], prefs), reverse=True)[:5]
        for i, d in enumerate(ranked):
            sc = personal_score(self.db, d["id"], prefs)
            row = Card("glass", 16, clickable=True); row.set_padding(12, 4, 12, 4)
            row.clicked.connect(lambda i_=d["id"]: self.open_detail(i_))
            medal = ["🥇", "🥈", "🥉", "4", "5"][i]
            row.layout_().addLayout(hbox(label(medal, 15, "#FFFFFF", 800, False), label(d["name"], 13, "#FFFFFF", 700, False), None, label(f"{sc}%", 14, "#FFB37A", 800, False), spacing=10))
            lay.addWidget(row); fade_in(row, i * 50, 260)

    def build_assistant(self):
        lay, h, _ = self.new_page("assistant", "", "", scroll=False)
        row = QHBoxLayout(); row.setSpacing(4)
        chat = Card("surface", 28, hover=False); chat.set_padding(0, 0, 0, 0)
        cl = chat.layout_(); cl.setSpacing(0)
        head = QWidget(); hl = QHBoxLayout(head); hl.setContentsMargins(22, 16, 18, 12)
        self.head_mascot = Mascot(56)
        self.chat_status = label(self.t("online"), 12, "positive", 600, False)
        hl.addWidget(self.head_mascot); hl.addLayout(vbox(label("Доми · " + self.t("nav_assistant"), 17, "text", 800, False), self.chat_status, spacing=0)); hl.addStretch()
        nb = Button(self.t("clear_chat"), "ghost", "refresh", "sm"); nb.clicked.connect(self.reset_chat); hl.addWidget(nb)
        cl.addWidget(head); cl.addWidget(Divider())
        self.chat_scroll = QScrollArea(); self.chat_scroll.setWidgetResizable(True); self.chat_scroll.setFrameShape(QFrame.NoFrame); self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); self.chat_lay = QVBoxLayout(inner); self.chat_lay.setContentsMargins(22, 16, 22, 16); self.chat_lay.setSpacing(12); self.chat_lay.addStretch()
        self.chat_scroll.setWidget(inner)
        cl.addWidget(self.chat_scroll, 1)
        self.chips_row = QHBoxLayout(); self.chips_row.setContentsMargins(22, 6, 22, 6); self.chips_row.setSpacing(8)
        cl.addLayout(self.chips_row)
        inp = QFrame(); il = QHBoxLayout(inp); il.setContentsMargins(22, 8, 16, 18)
        field = _InputPill(); fl = QHBoxLayout(field); fl.setContentsMargins(18, 4, 6, 4)
        self.question = QLineEdit(); self.question.setObjectName("chatInput"); self.question.setPlaceholderText(self.t("type_ph")); self.question.setFixedHeight(46)
        self.question.returnPressed.connect(lambda: self.ask(self.question.text()))
        fl.addWidget(self.question, 1)
        send = IconButton("send", "Send", "primary"); send.clicked.connect(lambda: self.ask(self.question.text())); fl.addWidget(send)
        il.addWidget(field)
        cl.addWidget(inp)
        row.addWidget(chat, 1)
        # side panel
        side = QVBoxLayout(); side.setSpacing(4)
        sc = Card("dark", 28, hover=False); sc.set_padding(22, 18, 22, 20)
        self.side_mascot = Mascot(150); self.side_mascot.set_mood("happy")
        sc.layout_().addWidget(self.side_mascot, 0, Qt.AlignCenter)
        on = self.claude.available
        sc.layout_().addWidget(Badge(("●  " + self.t("mode_claude")) if on else ("●  " + self.t("mode_local")), "#2B3A6B", "#B9F36B" if on else "#FFB37A", 12), 0, Qt.AlignCenter)
        sub = label(self.t("mode_claude_sub") if on else self.t("mode_local_sub"), 12, "#C9D2E6"); sub.setAlignment(Qt.AlignCenter)
        sc.layout_().addWidget(sub)
        side.addWidget(sc)
        pc = Card("surface", 26, hover=False); pc.set_padding(20, 18, 20, 18)
        pc.layout_().addWidget(label(self.t("prompt_tools"), 16, "text", 800))
        pc.layout_().addWidget(label(self.t("prompt_sub"), 12, "text_muted"))
        self.assistant_choice = QComboBox(); self.assistant_choice.setFixedHeight(42); self.assistant_choice.currentIndexChanged.connect(self.generate_prompt)
        pc.layout_().addWidget(self.assistant_choice)
        self.prompt = QPlainTextEdit(); self.prompt.setObjectName("note"); self.prompt.setReadOnly(True); self.prompt.setMinimumHeight(140)
        pc.layout_().addWidget(self.prompt, 1)
        copy = Button(self.t("copy"), "primary", "copy", "sm"); copy.clicked.connect(self.copy_prompt)
        ai = Button(self.t("open_chatgpt"), "secondary", "external", "sm"); ai.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://chatgpt.com/")))
        pc.layout_().addLayout(hbox(copy, ai, None, spacing=8))
        side.addWidget(pc, 1)
        sw = QWidget(); sw.setLayout(side); sw.setFixedWidth(380)
        row.addWidget(sw)
        lay.addLayout(row, 1)
        # восстановить диалог после перестройки UI
        if self.chat:
            for m in self.chat:
                self._add_bubble(m["text"], m["mine"], animate=False, cards=m.get("cards"))
            self._set_chips(TXT_CHIPS(self.language))
        else:
            QTimer.singleShot(200, lambda: self._bot_reply(self.local_ai.answer("", self.db.preferences(), self.language), typing=False))

    def reset_chat(self):
        self.chat.clear()
        while self.chat_lay.count() > 1:
            it = self.chat_lay.takeAt(1)
            if it.widget(): it.widget().deleteLater()
            elif it.layout(): clear_layout(it.layout())
        self._bot_reply(self.local_ai.answer("", self.db.preferences(), self.language), typing=False)

    def _scroll_chat(self):
        QTimer.singleShot(40, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def _add_bubble(self, text: str, mine: bool, animate: bool = True, cards=None):
        row = QHBoxLayout(); row.setSpacing(10)
        bubble = ChatBubble(text, mine)
        if mine:
            row.addStretch(); row.addWidget(bubble); row.addWidget(Avatar(self.user.get("username", "u").replace("_", " "), 34), 0, Qt.AlignBottom)
        else:
            m = Mascot(38); row.addWidget(m, 0, Qt.AlignBottom); row.addWidget(bubble); row.addStretch()
        self.chat_lay.addLayout(row)
        if animate:
            fade_in(bubble, 0, 280)
        if cards:
            self._add_cards(cards)
        self._scroll_chat()
        return bubble

    def _add_cards(self, ids):
        row = QHBoxLayout(); row.setContentsMargins(48, 0, 0, 0); row.setSpacing(4)
        for i in ids[:3]:
            d = self.db.get_development(i)
            if not d:
                continue
            a = self.db.analysis_for(i)
            c = Card("surface", 20, clickable=True); c.set_padding(8, 8, 12, 8); c.setMaximumWidth(260); c.setMinimumWidth(150)
            c.clicked.connect(lambda i_=i: self.open_detail(i_))
            cov = Cover(d["name"], 50, 12); cov.setFixedWidth(44)
            ring = ScoreRing(42, 5); ring.set_value(a.overall)
            c.layout_().addLayout(hbox(cov, vbox(label(d["name"], 13, "text", 800, False), label(money(d.get("purchase_price")), 11, "text_muted", 600, False), spacing=0), None, ring, spacing=8))
            row.addWidget(c); fade_in(c, 0, 360)
        row.addStretch()
        self.chat_lay.addLayout(row)

    def _set_chips(self, chips):
        clear_layout(self.chips_row)
        for text in chips[:3]:
            c = Chip(text, False, "sparkle"); c.setCheckable(False)
            c.clicked.connect(lambda _=False, q=text: self.ask(q))
            self.chips_row.addWidget(c)
        self.chips_row.addStretch()

    def ask(self, text: str):
        text = (text or "").strip()
        if not text or getattr(self, "_busy", False):
            return
        if not hasattr(self, "chat_lay"):
            return
        self.question.clear()
        self.chat.append({"text": text, "mine": True})
        self._add_bubble(text, True)
        self._busy = True
        self.typing = TypingBubble()
        row = QHBoxLayout(); row.addWidget(Mascot(38), 0, Qt.AlignBottom); row.addWidget(self.typing); row.addStretch()
        self._typing_row = row
        self.chat_lay.addLayout(row); self._scroll_chat()
        for m in (self.head_mascot, self.side_mascot): m.set_mood("think")
        self.chat_status.setText(self.t("thinking"))
        local = self.local_ai.answer(text, self.db.preferences(), self.language)
        self.log("Вопрос Доми", text, local["text"][:600])
        if self.claude.available:
            history = [{"role": "user" if m["mine"] else "assistant", "content": m["text"]} for m in self.chat]
            while history and history[0]["role"] != "user":
                history.pop(0)
            context = ClaudeEngine.build_context(self.db, self.db.preferences())
            self._claude_thread = QThread(self)
            self._claude_worker = ClaudeWorker(self.claude, history, context, self.language)
            self._claude_worker.moveToThread(self._claude_thread)
            self._claude_thread.started.connect(self._claude_worker.run)

            def ok(reply, local=local):
                ids = [d["id"] for d in self.db.developments() if d["name"].lower() in reply.lower()][:3]
                self._bot_reply({"text": reply, "cards": ids or local["cards"], "chips": local["chips"], "mood": "talk"})

            def fail(err, local=local):
                local = dict(local); local["text"] += "\n\n(Claude недоступен: " + err[:120] + " — ответил локальный режим.)"
                self._bot_reply(local)
            self._claude_worker.finished.connect(ok); self._claude_worker.failed.connect(fail)
            self._claude_worker.finished.connect(self._claude_thread.quit); self._claude_worker.failed.connect(self._claude_thread.quit)
            self._claude_thread.start()
        else:
            QTimer.singleShot(650 + min(900, len(local["text"]) * 3), lambda: self._bot_reply(local))

    def _bot_reply(self, reply: dict, typing: bool = True):
        try:
            if getattr(self, "_typing_row", None) is not None:
                clear_layout(self._typing_row); self.chat_lay.removeItem(self._typing_row); self._typing_row = None
        except RuntimeError:
            pass
        text = reply["text"]
        self.chat.append({"text": text, "mine": False, "cards": reply.get("cards")})
        bubble = self._add_bubble("" if typing else text, False)
        for m in (self.head_mascot, self.side_mascot): m.set_mood("talk")

        def finish():
            self._busy = False
            if reply.get("cards"):
                self._add_cards(reply["cards"])
            self._set_chips(reply.get("chips") or [])
            mood = reply.get("mood", "idle")
            for m in (self.head_mascot, self.side_mascot):
                try: m.set_mood("happy" if mood == "happy" else "idle")
                except RuntimeError: pass
            try: self.chat_status.setText(self.t("online"))
            except RuntimeError: pass
            self._scroll_chat()
        if not typing:
            finish(); return
        state = {"i": 0}
        timer = QTimer(self)

        def step():
            try:
                state["i"] = min(len(text), state["i"] + max(2, len(text) // 90))
                bubble.label.setText(text[: state["i"]])
                self._scroll_chat()
            except RuntimeError:
                timer.stop(); return
            if state["i"] >= len(text):
                timer.stop(); finish()
        timer.timeout.connect(step); timer.start(16)

    def build_reviews(self):
        lay, h, _ = self.new_page("reviews", self.t("nav_reviews"), self.t("reviews_sub"))
        bar = Card("surface", 24, hover=False); bar.set_padding(14, 12, 14, 12)
        self.review_search = SearchBox(self.t("search_ph"), "", 44)
        self.review_search.edit.textChanged.connect(lambda _: self._rev_timer.start())
        self._rev_timer = QTimer(self); self._rev_timer.setSingleShot(True); self._rev_timer.setInterval(160); self._rev_timer.timeout.connect(self.refresh_reviews)
        self.review_source = QComboBox(); self.review_source.setFixedHeight(44); self.review_source.setMinimumWidth(200)
        self.review_source.currentIndexChanged.connect(lambda _: self.refresh_reviews())
        self.rating_switch = Segmented([self.t("all"), "★5", "★4", "★≤3"], 0)
        self.rating_switch.changed.connect(lambda _: self.refresh_reviews())
        bar.layout_().addLayout(hbox(self.review_search, self.review_source, self.rating_switch, spacing=12, stretch_at=0))
        lay.addWidget(bar)
        self.review_count_label = label("", 13, "text_muted", 600); self.review_count_label.setContentsMargins(12, 0, 0, 0); lay.addWidget(self.review_count_label)
        self.all_reviews_grid = ResponsiveGrid(420, 4); lay.addWidget(self.all_reviews_grid); lay.addStretch()

    def refresh_reviews(self):
        if not hasattr(self, "all_reviews_grid"): return
        rows = self.db.all_reviews()
        sources = sorted({r["source"] for r in rows})
        cur = self.review_source.currentText()
        self.review_source.blockSignals(True); self.review_source.clear(); self.review_source.addItems([self.t("all_sources")] + sources)
        if cur in sources: self.review_source.setCurrentText(cur)
        self.review_source.blockSignals(False)
        q = self.review_search.edit.text().strip().lower()
        src = self.review_source.currentText()
        if q: rows = [r for r in rows if q in r["text"].lower() or q in r["development_name"].lower() or q in r["author"].lower()]
        if src in sources: rows = [r for r in rows if r["source"] == src]
        ri = self.rating_switch.index
        if ri == 1: rows = [r for r in rows if r["rating"] == 5]
        elif ri == 2: rows = [r for r in rows if r["rating"] == 4]
        elif ri == 3: rows = [r for r in rows if r["rating"] <= 3]
        self.review_count_label.setText(self.t("found", n=len(rows)))
        if rows:
            self.all_reviews_grid.set_items([self.review_card(r, r["development_name"]) for r in rows[:60]])
        else:
            self.all_reviews_grid.set_items([self.empty_state(self.t("empty_search"), self.t("empty_search_sub"))])

    def build_admin(self):
        lay, h, _ = self.new_page("admin", self.t("nav_admin"), self.t("admin_sub"))
        add = Button(self.t("add_user"), "primary", "plus"); add.clicked.connect(self.add_user); h.addWidget(add)
        info = Card("muted", 22, hover=False); info.set_padding(18, 12, 18, 12)
        info.layout_().addLayout(hbox(IconBubble("shield", "accent_soft", "accent", 36), label("Роль super_admin имеет полный доступ. Пароль первого входа: super_admin. Роли: viewer — просмотр, analyst — аналитика, editor — управление данными.", 13, "text_muted"), spacing=12, stretch_at=1))
        lay.addWidget(info)
        tc = Card("surface", 26, hover=False); tc.set_padding(10, 10, 10, 10)
        self.users_table = QTableWidget(0, 5); self.users_table.setHorizontalHeaderLabels(["Логин", "Роль", "Активен", "Создан", "Действия"]); self.users_table.setEditTriggers(QTableWidget.NoEditTriggers); self.users_table.verticalHeader().setVisible(False)
        self.users_table.setStyleSheet("QTableWidget{border:none;}")
        self.users_table.setShowGrid(False); self.users_table.setMinimumHeight(420)
        hh = self.users_table.horizontalHeader(); hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 5): hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        tc.layout_().addWidget(self.users_table)
        lay.addWidget(tc); lay.addStretch()

    # ---------- i18n / theme handlers ----------
    def language_changed(self, index: int):
        self.language = ["ru", "kk", "en"][index]
        QTimer.singleShot(260, self.rebuild_with_transition)

    def theme_changed(self, index: int):
        self.theme = ["light", "dark", "system"][index]
        QTimer.singleShot(260, self.rebuild_with_transition)

    def apply_theme(self):
        self.rebuild_with_transition()

    def retranslate_ui(self):
        self.rebuild_with_transition()

    # ---------- permissions ----------
    def can(self, permission: str) -> bool:
        role = self.user.get("role", "viewer")
        return role == "super_admin" or (permission == "read") or (permission == "manage" and role == "editor") or (permission == "assistant" and role in {"analyst", "editor"})

    def require_permission(self, permission: str) -> bool:
        if self.can(permission): return True
        QMessageBox.warning(self, "Недостаточно прав", "Эта операция недоступна для вашей роли.")
        return False

    def apply_permissions(self):
        manage = self.can("manage")
        if hasattr(self, "add_button"): self.add_button.setVisible(manage)
        if hasattr(self, "import_button"): self.import_button.setVisible(manage)
        try:
            if getattr(self, "sync_button", None) is not None: self.sync_button.setEnabled(manage)
            for w in getattr(self, "_detail_manage", []): w.setVisible(manage)
        except RuntimeError:
            pass
        if "admin" in self.nav: self.nav["admin"].setVisible(self.user.get("role") == "super_admin")

    # ---------- navigation ----------
    def refresh_all(self):
        self.refresh_page(self.current_page); self.update_badges()

    def update_badges(self):
        try:
            if "favorites" in self.nav: self.nav["favorites"].badge = len(self.db.favorites()); self.nav["favorites"].update()
            if "compare" in self.nav: self.nav["compare"].badge = len(self.compare_ids); self.nav["compare"].update()
        except RuntimeError:
            pass

    def show_page(self, key: str, animate: bool = True):
        if key not in self.pages: return
        if key != "detail":
            self._back_page = key
        self.current_page = key
        self.refresh_page(key)
        if animate:
            self.stack.go(self.pages[key])
        else:
            self.stack.setCurrentWidget(self.pages[key])
        for name, b in self.nav.items():
            b.blockSignals(True); b.setChecked(name == key); b.blockSignals(False)
            b._act.stop(); b._act.setStartValue(b._active); b._act.setEndValue(1.0 if name == key else 0.0); b._act.start()
        if hasattr(self, "domi"):
            self.domi.setVisible(key not in ("assistant",))
        if hasattr(self, "tray"):
            self.update_tray()
        if key == "assistant" and hasattr(self, "question"):
            QTimer.singleShot(300, self.question.setFocus)

    def refresh_page(self, key: str):
        {"home": self.refresh_home, "catalog": self.refresh_catalog, "detail": self.render_detail, "map": self.refresh_map,
         "favorites": self.refresh_favorites, "compare": self.refresh_compare, "comfort": self.refresh_live_top,
         "assistant": self.refresh_assistant, "reviews": self.refresh_reviews, "admin": self.refresh_users,
         "analytics": self.refresh_analytics, "history": self.refresh_history, "profile": self.refresh_profile}.get(key, lambda: None)()

    # ---------- users (логика сохранена) ----------
    def refresh_users(self):
        if not hasattr(self, "users_table"): return
        self.users_table.setRowCount(0)
        for user in self.db.users():
            row = self.users_table.rowCount(); self.users_table.insertRow(row)
            for col, value in enumerate([user["username"], user["role"], "Да" if user["active"] else "Нет", user["created_at"]]):
                item = QTableWidgetItem(str(value)); item.setFont(font(13, 700 if col == 0 else 500)); self.users_table.setItem(row, col, item)
            actions = QWidget(); layout = QHBoxLayout(actions); layout.setContentsMargins(4, 4, 4, 4); layout.setSpacing(6)
            reset = Button(self.t("password_btn"), "secondary", "shield", "sm"); reset.clicked.connect(lambda _, user_id=user["id"]: self.reset_user(user_id))
            remove = Button(self.t("delete"), "danger", "trash", "sm"); remove.setEnabled(user["username"] != "super_admin"); remove.clicked.connect(lambda _, user_id=user["id"]: self.remove_user(user_id))
            layout.addWidget(reset); layout.addWidget(remove); self.users_table.setCellWidget(row, 4, actions); self.users_table.setRowHeight(row, 52)

    def add_user(self):
        if not self.require_permission("manage"): return
        dialog = UserDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.add_user(dialog.username.text(), dialog.password.text(), dialog.role.currentText()); self.refresh_users(); toast(self, "Пользователь добавлен", "ok")
            except Exception as error: QMessageBox.warning(self, "Не удалось добавить", str(error))

    def reset_user(self, user_id: int):
        if not self.require_permission("manage"): return
        dialog = QDialog(self); dialog.setWindowTitle("Новый пароль"); layout = QFormLayout(dialog); layout.setContentsMargins(24, 22, 24, 18); password = QLineEdit(); password.setEchoMode(QLineEdit.Password); layout.addRow("Пароль", password); box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); box.accepted.connect(dialog.accept); box.rejected.connect(dialog.reject); layout.addRow(box)
        if dialog.exec() == QDialog.DialogCode.Accepted and password.text(): self.db.reset_user_password(user_id, password.text()); toast(self, "Пароль обновлён", "ok")

    def remove_user(self, user_id: int):
        if not self.require_permission("manage"): return
        if QMessageBox.question(self, "Удалить пользователя?", "Пользователь потеряет доступ к приложению.", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes: self.db.delete_user(user_id); self.refresh_users()

    # ---------- developments (логика сохранена) ----------
    def compare_changed(self, development_id: int, state):
        on = bool(state) and state != 0
        if on:
            if len(self.compare_ids) >= 3 and development_id not in self.compare_ids:
                toast(self, self.t("max3"), "warn"); self.refresh_catalog(False); return
            self.compare_ids.add(development_id); toast(self, self.t("added_compare"), "ok", 1600)
        else:
            self.compare_ids.discard(development_id)
        if self.current_page == "catalog":
            QTimer.singleShot(220, lambda: self.refresh_catalog(False))
        self.update_tray()

    def clear_compare(self): self.compare_ids.clear(); self.refresh_catalog(False); self.refresh_compare(); self.update_badges()

    def open_current_detail(self):
        if self.current_id: self.open_detail(self.current_id)

    def open_detail(self, development_id: int):
        if not development_id: return
        self.current_id = development_id; self.show_page("detail")

    def add_development(self):
        if not self.require_permission("manage"): return
        d = DevelopmentDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.add_development(d.values(), "manual"); toast(self, "ЖК добавлен", "ok"); self.log("Добавление ЖК", d.values()["name"], "Сохранено")
            except ValueError as error:
                QMessageBox.warning(self, "Не удалось добавить", str(error))
            self.refresh_all()

    def edit_current(self):
        if self.current_id: self.edit_development(self.current_id)

    def edit_development(self, development_id: int):
        if not self.require_permission("manage"): return
        item = self.db.get_development(development_id)
        if not item: return
        d = DevelopmentDialog(self, item)
        if d.exec() == QDialog.DialogCode.Accepted:
            try:
                self.db.update_development(development_id, d.values())
            except ValueError as error:
                QMessageBox.warning(self, "Проверьте данные", str(error)); return
            self.log("Изменение ЖК", d.values()["name"], "Сохранено")
            self.current_id = development_id; self.refresh_all(); toast(self, self.t("saved"), "ok")

    def delete_development(self, development_id: int):
        if not self.require_permission("manage"): return
        item = self.db.get_development(development_id)
        if item and QMessageBox.question(self, "Удалить ЖК?", f"Удалить «{item['name']}» и отзывы?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.db.delete_development(development_id); self.compare_ids.discard(development_id); self.log("Удаление ЖК", item["name"], "Удалён вместе с отзывами")
            if self.current_id == development_id: self.current_id = None
            self.show_page("catalog"); toast(self, "ЖК удалён", "ok")

    def toggle_favorite(self, development_id: int):
        on = self.db.toggle_favorite(development_id)
        toast(self, self.t("fav_added") if on else self.t("fav_removed"), "ok", 1600)
        self.update_badges()
        QTimer.singleShot(0, lambda: self.refresh_page(self.current_page))

    def toggle_current_favorite(self):
        if self.current_id: self.toggle_favorite(self.current_id)

    def import_file(self):
        if not self.require_permission("manage"): return
        path, _ = QFileDialog.getOpenFileName(self, "Импорт разрешённого экспорта", "", "HouseCheck data (*.json *.csv)")
        if not path: return
        try:
            developments, reviews = self.db.import_file(Path(path)); self.refresh_all()
            skipped = getattr(self.db, "last_import_errors", [])
            self.log("Импорт", Path(path).name, f"ЖК: {developments}, отзывов: {reviews}, пропущено: {len(skipped)}")
            QMessageBox.information(self, "Импорт завершён", f"Добавлено ЖК: {developments}\nДобавлено отзывов: {reviews}" + (f"\n\nПропущено записей с ошибками: {len(skipped)}\n" + "\n".join("• " + e for e in skipped[:10]) if skipped else ""))
        except Exception as error: QMessageBox.critical(self, "Ошибка импорта", str(error))

    def open_google_maps(self, development_id: int | None = None):
        development_id = development_id or self.current_id
        item = self.db.get_development(development_id) if development_id else None
        if not item: return
        url = item.get("google_maps_url") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(f'{item["name"]}, {item.get("address", "")}, {item.get("city", "")}')}"
        QDesktopServices.openUrl(QUrl(url))

    # ---------- comfort ----------
    def apply_profile(self, preset: dict[str, int]):
        for key, slider in self.sliders.items(): slider.setValue(preset.get(key, 0))
        self.refresh_live_top()

    def slider_changed(self, key: str, value: int, output: QLabel):
        output.setText(str(value)); self._live_timer.start()

    def save_preferences(self):
        for key, slider in self.sliders.items(): self.db.set_preference(key, slider.value())
        self.log("Профиль комфорта", ", ".join(f"{k}={s.value()}" for k, s in self.sliders.items() if s.value()), "Сохранён")
        toast(self, self.t("profile_saved"), "ok")

    # ---------- prompt export ----------
    def refresh_assistant(self):
        if not hasattr(self, "assistant_choice"): return
        current = self.assistant_choice.currentData(); self.assistant_choice.blockSignals(True); self.assistant_choice.clear()
        for item in self.db.developments(): self.assistant_choice.addItem(item["name"], item["id"])
        if current is not None:
            index = self.assistant_choice.findData(current)
            if index >= 0: self.assistant_choice.setCurrentIndex(index)
        self.assistant_choice.blockSignals(False); self.generate_prompt()

    def generate_prompt(self):
        if not hasattr(self, "prompt"): return
        development_id = self.assistant_choice.currentData(); item = self.db.get_development(int(development_id)) if development_id else None
        if not item: self.prompt.setPlainText("Добавьте или импортируйте ЖК, чтобы сформировать запрос."); return
        reviews = self.db.reviews_for(item["id"]); block = "\n".join(f"- {x['rating']}/5, {x['author']} ({x['source']}): {x['text']}" for x in reviews) or "Данных отзывов нет. Не придумывай факты и укажи, что данных недостаточно."
        question = self.question.text().strip() if hasattr(self, "question") else ""
        self.prompt.setPlainText(f"Ты — аналитик недвижимости. Проанализируй только приведённые отзывы о ЖК «{item['name']}», {item.get('city', '')}.\nВопрос: {question or 'Какие сильные и слабые стороны проживания здесь?'}\n\nУкажи количество отзывов, отдельно плюсы и риски по тишине, транспорту, безопасности, двору, парковке и сервису. Не выдумывай отсутствующие данные.\n\nОтзывы из базы HouseCheck AI:\n{block}")

    def copy_prompt(self): QApplication.clipboard().setText(self.prompt.toPlainText()); toast(self, self.t("copied"), "ok")

    def save_notes(self):
        if not self.current_id: return
        item = self.db.get_development(self.current_id)
        if item: item["notes"] = self.notes.toPlainText(); self.db.update_development(self.current_id, item); self.log("Заметка", item["name"], item["notes"][:200]); self.notes.document().setModified(False); toast(self, self.t("note_saved"), "ok")

    # ---------- Google Places (логика сохранена) ----------
    def sync_google_reviews(self):
        if not self.require_permission("manage"): return
        if not self.current_id: QMessageBox.information(self, "Google Reviews", "Сначала выберите ЖК."); return
        item = self.db.get_development(self.current_id)
        if getattr(self, "_google_thread", None) and self._google_thread.isRunning(): return
        self.sync_button.setEnabled(False); self.sync_button.setText(self.t("loading")); toast(self, "Google Places: загружаем отзывы…", "info")
        self._google_thread = QThread(self); self._google_worker = GoogleReviewWorker(f"{item['name']}, {item.get('address', '')}, {item.get('city', '')}"); self._google_worker.moveToThread(self._google_thread); self._google_thread.started.connect(self._google_worker.run); self._google_worker.finished.connect(self.google_reviews_loaded); self._google_worker.failed.connect(self.google_reviews_failed); self._google_worker.finished.connect(self._google_thread.quit); self._google_worker.failed.connect(self._google_thread.quit); self._google_thread.finished.connect(self.google_thread_finished); self._google_thread.start()

    def google_reviews_loaded(self, payload):
        place, reviews = payload; item = self.db.get_development(self.current_id)
        if not item: return
        update = dict(item); update["google_place_id"] = place.get("id", ""); update["google_maps_url"] = place.get("googleMapsUri", item.get("google_maps_url", "")); update["address"] = place.get("formattedAddress", item.get("address", ""))
        if place.get("location"): update["lat"] = place["location"].get("latitude", item["lat"]); update["lng"] = place["location"].get("longitude", item["lng"])
        self.db.update_development(self.current_id, update); self.db.clear_reviews_for_source(self.current_id, "Google Maps")
        skipped = 0
        for review in reviews:
            try:
                self.db.add_review(self.current_id, review["source"], review["rating"], review["author"], review["text"], review["published_at"])
            except ValueError:
                skipped += 1  # отзыв без текста или без оценки не сохраняем
        self.log("Google Places", item["name"], f"Загружено: {len(reviews) - skipped}, пропущено: {skipped}")
        self.render_detail(); toast(self, f"Google Places: загружено отзывов: {len(reviews)}", "ok")

    def google_reviews_failed(self, message: str):
        QMessageBox.warning(self, "Не удалось загрузить отзывы", message + "\n\nПроверь GOOGLE_PLACES_API_KEY и настройки Google Cloud.")
        toast(self, "Google Places: операция завершилась с ошибкой", "error")

    def google_thread_finished(self):
        try:
            self.sync_button.setEnabled(self.can("manage")); self.sync_button.setText(self.t("sync"))
        except RuntimeError:
            pass
        self._google_worker.deleteLater(); self._google_thread.deleteLater(); self._google_worker = None; self._google_thread = None

    def closeEvent(self, event):
        notes = getattr(self, "notes", None)
        try:
            modified = notes is not None and notes.document().isModified()
        except RuntimeError:
            modified = False
        if modified:
            choice = QMessageBox.question(self, "Несохранённая заметка", "Сохранить изменения перед выходом?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Cancel: event.ignore(); return
            if choice == QMessageBox.Save: self.save_notes()
        thread = getattr(self, "_google_thread", None)
        if thread and thread.isRunning():
            choice = QMessageBox.question(self, "Загрузка выполняется", "Остановить загрузку Google Places и закрыть программу?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if choice == QMessageBox.No: event.ignore(); return
            thread.requestInterruption(); thread.quit(); thread.wait(1000)
        ct = getattr(self, "_claude_thread", None)
        if ct and ct.isRunning():
            ct.quit(); ct.wait(1500)
        if getattr(self, "guard", None): self.guard.stop()
        if not self._logging_out:
            self.log("Выход", "", "Приложение закрыто")
            self.db.close(); QApplication.quit()
        event.accept()


class _InputPill(QFrame):
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor(T["surface_muted"])); p.setPen(QColor(T["border"])); p.drawPath(path)


def TXT_CHIPS(lang: str):
    from assistant_engine import TXT
    return TXT.get(lang, TXT["ru"])["chips"]


def main():
    from config import load_local_env
    load_local_env()
    app = QApplication(sys.argv); app.setApplicationName("HouseCheck AI"); app.setFont(font(13))
    set_theme("light"); app.setStyleSheet(load_theme_stylesheet("light"))
    app.setQuitOnLastWindowClosed(False)  # после «Выйти» снова показываем окно входа
    db = Database()
    state = {"window": None, "lang": "ru"}

    def start_session():
        old = state["window"]
        if old is not None:
            state["lang"] = old.language
            old.deleteLater()
        set_theme("light"); app.setStyleSheet(load_theme_stylesheet("light"))
        login = LoginDialog(db, state["lang"])
        if login.exec() != QDialog.DialogCode.Accepted:
            db.close(); app.quit(); return False
        window = HouseCheckWindow(db, login.user, state["lang"])
        window.logged_out.connect(lambda: QTimer.singleShot(0, start_session))
        state["window"] = window; window.show()
        return True

    if not start_session(): return
    sys.exit(app.exec())


if __name__ == "__main__": main()
