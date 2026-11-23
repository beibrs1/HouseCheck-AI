"""Новые окна и разделы HouseCheck AI.

* Регистрация, восстановление пароля по коду из письма, смена пароля, профиль.
* Аналитика: графики, таблица, методы принятия решений (WSM, TOPSIS), ИИ-прогноз.
* История действий с поиском и фильтрами.
* Отчёты (HTML/PDF/CSV/JSON) и отправка на e-mail.
* Завершение сеанса и автоматический выход при бездействии.

Класс FeaturePages — «примесь» к главному окну HouseCheckWindow.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QObject, QPointF, QRectF, Qt, QThread, QTimer, QUrl, QVariantAnimation, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QIntValidator, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QSizePolicy, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import analytics
import mailer
import reports
from ai_insights import explain_analysis, price_forecast
from database import AuthError, Database
from decision import agreement, alternatives_from_db, criteria_from_preferences, explain, topsis, weighted_sum
from mascot import Mascot
from theme_tokens import T
from ui_kit import (
    Avatar, Badge, Button, C, Card, IconBubble, SearchBox, Segmented, clear_layout, fade_in, font, hbox, label,
    money, score_color, toast, vbox,
)

IDLE_LOGOUT_MINUTES = 30


# ───────────────────────── Фоновые задачи ─────────────────────────

class _Job(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as error:  # noqa: BLE001 — показываем текст пользователю
            self.failed.emit(str(error))


def run_async(parent: QObject, fn, on_done, on_fail) -> None:
    """Выполняет fn в отдельном потоке (отправка почты не должна «замораживать» окно)."""
    thread = QThread(parent)
    job = _Job(fn)
    job.moveToThread(thread)
    thread.started.connect(job.run)
    job.done.connect(on_done)
    job.failed.connect(on_fail)
    job.done.connect(thread.quit)
    job.failed.connect(thread.quit)
    thread.finished.connect(job.deleteLater)
    thread.finished.connect(thread.deleteLater)
    parent._jobs = getattr(parent, "_jobs", []) + [(thread, job)]
    thread.start()


def open_folder(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent if Path(path).is_file() else path)))


# ───────────────────────── Базовое окно-форма ─────────────────────────

class FormDialog(QDialog):
    """Окно с заголовком, полями, строкой ошибки и главной кнопкой."""

    def __init__(self, title: str, subtitle: str = "", parent=None, width: int = 460):
        super().__init__(parent)
        self.setWindowTitle(f"HouseCheck AI — {title}")
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(34, 30, 34, 26)
        self.root.setSpacing(8)
        self.root.addWidget(label(title, 24, "text", 800))
        if subtitle:
            self.root.addWidget(label(subtitle, 13, "text_muted"))
        self.root.addSpacing(10)
        self.error = label("", 12, "danger", 600)
        self.error.setMinimumHeight(18)

    def field(self, caption: str, value: str = "", password: bool = False, placeholder: str = "", layout=None) -> QLineEdit:
        layout = layout or self.root
        layout.addWidget(label(caption, 12, "text_muted", 700))
        edit = QLineEdit(value)
        edit.setFixedHeight(44)
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.Password)
        edit.textEdited.connect(lambda _: self.error.setText(""))
        layout.addWidget(edit)
        return edit

    def finish(self, primary_text: str, on_primary, icon: str = "check") -> Button:
        self.root.addWidget(self.error)
        ok = Button(primary_text, "primary", icon, "lg")
        ok.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ok.clicked.connect(on_primary)
        cancel = Button("Отмена", "ghost", None, "lg")
        cancel.clicked.connect(self.reject)
        self.root.addLayout(hbox(cancel, ok, spacing=10, stretch_at=1))
        return ok

    def fail(self, text: str) -> None:
        self.error.setText(text)


# ───────────────────────── Регистрация ─────────────────────────

class RegisterDialog(FormDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__("Регистрация", "Создайте аккаунт, чтобы сохранять историю, профиль и отчёты.", parent)
        self.db = db
        self.user: dict | None = None
        self.full_name = self.field("Имя и фамилия *", placeholder="Айгерим Серикова")
        self.email = self.field("Электронная почта *", placeholder="name@mail.kz")
        self.username = self.field("Логин *", placeholder="aigerim")
        self.password = self.field("Пароль * (мин. 8 символов, буквы и цифры)", password=True)
        self.repeat = self.field("Повторите пароль *", password=True)
        self.strength = label("", 11, "text_muted", 600)
        self.root.addWidget(self.strength)
        self.password.textChanged.connect(self._strength)
        self.repeat.returnPressed.connect(self.submit)
        self.finish("Создать аккаунт", self.submit, "user")

    def _strength(self, text: str) -> None:
        score = sum([len(text) >= 8, len(text) >= 12, any(c.isdigit() for c in text), any(c.isupper() for c in text),
                     any(not c.isalnum() for c in text)])
        names = ["очень слабый", "слабый", "средний", "хороший", "надёжный", "отличный"]
        colors = ["danger", "danger", "warning", "warning", "positive", "positive"]
        self.strength.setText(f"Надёжность пароля: {names[score]}" if text else "")
        self.strength.setStyleSheet(f"color:{T[colors[score]]};")

    def submit(self) -> None:
        try:
            self.user = self.db.register_user(self.full_name.text(), self.email.text(), self.username.text(),
                                              self.password.text(), self.repeat.text())
        except AuthError as error:
            self.fail(str(error))
            return
        self.db.log(self.user, "Регистрация", self.user["email"], "Аккаунт создан")
        self.accept()


# ───────────────────────── Восстановление пароля ─────────────────────────

class ForgotPasswordDialog(QDialog):
    """Шаг 1 — почта → код на e-mail. Шаг 2 — код + новый пароль."""

    def __init__(self, db: Database, email: str = "", parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("HouseCheck AI — восстановление пароля")
        self.setMinimumWidth(480)
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.stack)
        self._cooldown = 0
        self._timer = QTimer(self); self._timer.setInterval(1000); self._timer.timeout.connect(self._tick)

        # шаг 1
        self.step1 = FormDialog("Забыли пароль?", "Введите почту, указанную в профиле. Мы отправим 6-значный код подтверждения.")
        self.email = self.step1.field("Электронная почта", email, placeholder="name@mail.kz")
        self.send_btn = self.step1.finish("Отправить код", self.send_code, "mail")
        self.step1.reject = self.reject
        self.email.returnPressed.connect(self.send_code)
        self.stack.addWidget(self.step1)

        # шаг 2
        self.step2 = FormDialog("Введите код", "Код действует 15 минут. Не больше 5 попыток.")
        self.sent_to = label("", 12, "text_muted"); self.step2.root.addWidget(self.sent_to)
        self.code = self.step2.field("Код из письма", placeholder="••••••")
        self.code.setMaxLength(6); self.code.setValidator(QIntValidator(0, 999999, self))
        self.code.setFont(font(22, 800)); self.code.setAlignment(Qt.AlignCenter); self.code.setFixedHeight(56)
        self.new_password = self.step2.field("Новый пароль", password=True)
        self.repeat = self.step2.field("Повторите новый пароль", password=True)
        self.resend = Button("Отправить код ещё раз", "ghost", "refresh", "sm")
        self.resend.clicked.connect(self.send_code)
        self.step2.root.addWidget(self.resend, 0, Qt.AlignLeft)
        self.step2.finish("Сменить пароль", self.confirm, "lock")
        self.step2.reject = self.reject
        self.repeat.returnPressed.connect(self.confirm)
        self.stack.addWidget(self.step2)

    def _tick(self) -> None:
        self._cooldown -= 1
        if self._cooldown <= 0:
            self._timer.stop(); self.resend.setEnabled(True); self.resend.setText("Отправить код ещё раз")
        else:
            self.resend.setText(f"Повторно через {self._cooldown} с")

    def send_code(self) -> None:
        if self._cooldown > 0:
            return
        email = self.email.text().strip()
        try:
            user, code = self.db.create_reset_code(email)
        except AuthError as error:
            self.step1.fail(str(error)); self.stack.setCurrentWidget(self.step1)
            return
        body = (f"Здравствуйте, {user.get('full_name') or user['username']}!\n\n"
                f"Код для восстановления пароля HouseCheck AI: {code}\n"
                "Код действует 15 минут. Если вы не запрашивали восстановление, просто удалите это письмо.\n")
        self.send_btn.setEnabled(False); self.resend.setEnabled(False)
        self.send_btn.setText("Отправляем…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(result: mailer.SendResult):
            QApplication.restoreOverrideCursor()
            self.send_btn.setEnabled(True); self.send_btn.setText("Отправить код")
            self.db.log(user, "Восстановление пароля", email, result.detail)
            if result.delivered:
                self.sent_to.setText(f"Код отправлен на {email}.")
            else:
                self.sent_to.setText(f"SMTP не настроен: письмо с кодом сохранено в {result.path}")
                QMessageBox.information(self, "Письмо сохранено локально",
                                        "Почтовый сервер не настроен (SMTP_* в .env), поэтому письмо с кодом сохранено "
                                        f"в файл:\n{result.path}\n\nОткройте его двойным щелчком — внутри будет код.")
                open_folder(result.path)
            self._cooldown = 30; self._timer.start(); self._tick()
            self.stack.setCurrentWidget(self.step2); self.code.setFocus()

        def failed(message: str):
            QApplication.restoreOverrideCursor()
            self.send_btn.setEnabled(True); self.send_btn.setText("Отправить код"); self.resend.setEnabled(True)
            self.db.log(user, "Ошибка почты", email, message)
            target = self.step1 if self.stack.currentWidget() is self.step1 else self.step2
            target.fail("Не удалось отправить письмо: " + message)

        run_async(self, lambda: mailer.send_email(email, "HouseCheck AI — код восстановления пароля", body), done, failed)

    def confirm(self) -> None:
        try:
            self.db.reset_password_with_code(self.email.text(), self.code.text(), self.new_password.text(), self.repeat.text())
        except AuthError as error:
            self.step2.fail(str(error))
            return
        self.db.log({"username": self.email.text()}, "Восстановление пароля", self.email.text(), "Пароль изменён по коду")
        QMessageBox.information(self, "Готово", "Пароль изменён. Войдите с новым паролем.")
        self.accept()


# ───────────────────────── Профиль и пароль ─────────────────────────

class ProfileDialog(FormDialog):
    def __init__(self, db: Database, user: dict, parent=None):
        super().__init__("Изменить профиль", f"Логин: {user['username']} · роль: {user.get('role', 'viewer')}", parent, 500)
        self.db, self.user_id = db, user["id"]
        self.updated: dict | None = None
        self.full_name = self.field("Имя и фамилия *", user.get("full_name", ""))
        self.email = self.field("Электронная почта *", user.get("email", ""), placeholder="name@mail.kz")
        self.phone = self.field("Телефон", user.get("phone", ""), placeholder="+7 701 123 45 67")
        self.root.addWidget(label("О себе", 12, "text_muted", 700))
        self.about = QPlainTextEdit(user.get("about", "")); self.about.setFixedHeight(80)
        self.about.setPlaceholderText("Например: ищу 2-комнатную квартиру для семьи, бюджет до 40 млн ₸")
        self.root.addWidget(self.about)
        self.finish("Сохранить", self.submit)

    def submit(self) -> None:
        try:
            self.updated = self.db.update_profile(self.user_id, self.full_name.text(), self.email.text(),
                                                  self.phone.text(), self.about.toPlainText())
        except AuthError as error:
            self.fail(str(error))
            return
        self.accept()


class ChangePasswordDialog(FormDialog):
    def __init__(self, db: Database, user: dict, parent=None):
        super().__init__("Смена пароля", "Для безопасности введите текущий пароль.", parent)
        self.db, self.user = db, user
        self.old = self.field("Текущий пароль", password=True)
        forgot = Button("Забыли пароль?", "ghost", None, "sm"); forgot.clicked.connect(self._forgot)
        self.root.addWidget(forgot, 0, Qt.AlignRight)
        self.new = self.field("Новый пароль (мин. 8 символов, буквы и цифры)", password=True)
        self.repeat = self.field("Повторите новый пароль", password=True)
        self.repeat.returnPressed.connect(self.submit)
        self.finish("Сменить пароль", self.submit, "lock")

    def _forgot(self) -> None:
        if not self.user.get("email"):
            self.fail("В профиле не указана почта — сначала добавьте её в «Изменить профиль».")
            return
        if ForgotPasswordDialog(self.db, self.user["email"], self).exec() == QDialog.DialogCode.Accepted:
            self.accept()

    def submit(self) -> None:
        try:
            self.db.change_password(self.user["id"], self.old.text(), self.new.text(), self.repeat.text())
        except AuthError as error:
            self.fail(str(error))
            return
        self.accept()


class SendReportDialog(FormDialog):
    def __init__(self, user: dict, parent=None):
        super().__init__("Отправить отчёт на почту", "Отчёт будет сформирован и приложен к письму.", parent, 480)
        self.to = self.field("Кому", user.get("email", ""), placeholder="name@mail.kz")
        self.subject = self.field("Тема", "HouseCheck AI — аналитический отчёт")
        self.root.addWidget(label("Формат вложения", 12, "text_muted", 700))
        self.format = QComboBox(); self.format.addItems(["PDF", "HTML", "CSV (Excel)"]); self.format.setFixedHeight(44)
        self.root.addWidget(self.format)
        self.root.addWidget(label("Сообщение", 12, "text_muted", 700))
        self.message = QPlainTextEdit("Здравствуйте!\n\nВо вложении отчёт HouseCheck AI по жилым комплексам Астаны.")
        self.message.setFixedHeight(90); self.root.addWidget(self.message)
        self.finish("Отправить", self.submit, "send")

    def submit(self) -> None:
        error = mailer.email_error(self.to.text())
        if error:
            self.fail(error)
            return
        if not self.subject.text().strip():
            self.fail("Укажите тему письма.")
            return
        self.accept()

    @property
    def extension(self) -> str:
        return ["pdf", "html", "csv"][self.format.currentIndex()]


# ───────────────────────── Графики ─────────────────────────

class _Animated(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._anim = QVariantAnimation(self); self._anim.setDuration(900); self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_t", float(v)), self.update()))
        QTimer.singleShot(120, self._anim.start)


class HBarChart(_Animated):
    """Горизонтальные столбцы: [(подпись, значение)]."""

    def __init__(self, items: list[tuple[str, float]], max_value: float | None = None, fmt=lambda v: f"{v:.0f}", color_by_score: bool = True, parent=None):
        super().__init__(parent)
        self.items, self.fmt, self.color_by_score = items, fmt, color_by_score
        self.max_value = max_value or max([v for _, v in items] + [1])
        self.setMinimumHeight(max(60, 34 * len(items)))

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        label_w = min(190, self.width() * 0.38)
        row_h = self.height() / max(1, len(self.items))
        for i, (name, value) in enumerate(self.items):
            y = i * row_h
            p.setPen(C("text")); p.setFont(font(12, 600))
            p.drawText(QRectF(0, y, label_w - 10, row_h), Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(name, Qt.ElideRight, int(label_w - 10)))
            bar = QRectF(label_w, y + row_h / 2 - 7, self.width() - label_w - 56, 14)
            bg = QPainterPath(); bg.addRoundedRect(bar, 7, 7); p.fillPath(bg, C("grid"))
            w = bar.width() * (value / self.max_value if self.max_value else 0) * self._t
            fill = QPainterPath(); fill.addRoundedRect(QRectF(bar.left(), bar.top(), max(0, w), bar.height()), 7, 7)
            p.fillPath(fill, QColor(score_color(int(value))) if self.color_by_score else C("accent"))
            p.setPen(C("text")); p.setFont(font(12, 800))
            p.drawText(QRectF(bar.right() + 6, y, 50, row_h), Qt.AlignVCenter | Qt.AlignLeft, self.fmt(value))


class ColumnChart(_Animated):
    """Вертикальные столбцы (гистограмма): [(подпись, значение)]."""

    def __init__(self, items: list[tuple[str, float]], parent=None):
        super().__init__(parent)
        self.items = items
        self.setMinimumHeight(210)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        n = max(1, len(self.items)); top = max([v for _, v in self.items] + [1])
        area = QRectF(8, 22, self.width() - 16, self.height() - 52)
        p.setPen(QPen(C("grid"), 1))
        for k in range(5):
            y = area.bottom() - area.height() * k / 4
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        slot = area.width() / n
        for i, (name, value) in enumerate(self.items):
            h = area.height() * value / top * self._t
            r = QRectF(area.left() + i * slot + slot * 0.2, area.bottom() - h, slot * 0.6, h)
            path = QPainterPath(); path.addRoundedRect(r, 8, 8)
            p.fillPath(path, C("accent") if value == top else C("accent_glow"))
            p.setPen(C("text")); p.setFont(font(12, 800))
            p.drawText(QRectF(r.left() - 10, r.top() - 20, r.width() + 20, 18), Qt.AlignCenter, f"{value:.0f}")
            p.setPen(C("text_muted")); p.setFont(font(12, 700))
            p.drawText(QRectF(area.left() + i * slot, area.bottom() + 6, slot, 22), Qt.AlignCenter, name)


class ScatterChart(_Animated):
    """Точки (x, y, подпись) и линия регрессии y = a·x + b."""

    def __init__(self, points: list[tuple[float, float, str]], line: tuple[float, float] | None, x_title: str, y_title: str, parent=None):
        super().__init__(parent)
        self.points, self.line, self.x_title, self.y_title = points, line, x_title, y_title
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self._hover = -1

    def _frame(self):
        xs = [x for x, _, _ in self.points] or [0, 1]; ys = [y for _, y, _ in self.points] or [0, 1]
        x0, x1 = min(xs) - 3, max(xs) + 3
        y0, y1 = 0, max(ys) * 1.12
        area = QRectF(52, 16, self.width() - 68, self.height() - 52)
        def to(x, y):
            return QPointF(area.left() + (x - x0) / (x1 - x0 or 1) * area.width(), area.bottom() - (y - y0) / (y1 - y0 or 1) * area.height())
        return area, to, (x0, x1, y0, y1)

    def mouseMoveEvent(self, e):
        _, to, _ = self._frame()
        pos = e.position()
        best, dist = -1, 14.0
        for i, (x, y, _) in enumerate(self.points):
            pt = to(x, y); d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d < dist:
                best, dist = i, d
        if best != self._hover:
            self._hover = best; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        area, to, (x0, x1, y0, y1) = self._frame()
        p.setPen(QPen(C("grid"), 1))
        p.setFont(font(10, 600))
        for k in range(5):
            y = area.bottom() - area.height() * k / 4
            p.setPen(QPen(C("grid"), 1)); p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(C("text_soft")); p.drawText(QRectF(0, y - 8, 46, 16), Qt.AlignRight | Qt.AlignVCenter, f"{y0 + (y1 - y0) * k / 4:.0f}")
        p.setPen(C("text_muted")); p.setFont(font(11, 700))
        p.drawText(QRectF(area.left(), area.bottom() + 10, area.width(), 20), Qt.AlignCenter, self.x_title)
        p.drawText(QRectF(area.left() + 4, 0, area.width(), 16), Qt.AlignLeft, self.y_title)
        if self.line:
            a, b = self.line
            pen = QPen(C("nav"), 2, Qt.DashLine); p.setPen(pen)
            p.drawLine(to(x0, a * x0 + b), to(x0 + (x1 - x0) * self._t, a * (x0 + (x1 - x0) * self._t) + b))
        for i, (x, y, name) in enumerate(self.points):
            pt = to(x, y)
            r = (7 if i != self._hover else 10) * self._t
            p.setPen(QPen(QColor("#FFFFFF"), 2)); p.setBrush(QColor(score_color(int(x))))
            p.drawEllipse(pt, r, r)
        if 0 <= self._hover < len(self.points):
            x, y, name = self.points[self._hover]
            pt = to(x, y)
            text = f"{name}: индекс {x:.0f}, {y:.1f} млн ₸"
            p.setFont(font(11, 700)); w = p.fontMetrics().horizontalAdvance(text) + 20
            box = QRectF(min(pt.x() + 12, self.width() - w - 4), max(2, pt.y() - 34), w, 26)
            path = QPainterPath(); path.addRoundedRect(box, 8, 8); p.fillPath(path, C("nav"))
            p.setPen(QColor("#FFFFFF")); p.drawText(box, Qt.AlignCenter, text)


class NumItem(QTableWidgetItem):
    """Ячейка с числом: показывает «23 500 000», а сортирует по значению."""

    def __init__(self, value: float):
        text = f"{value:,.0f}".replace(",", " ") if isinstance(value, int) or abs(value) >= 1000 else f"{value:g}"
        super().__init__(text)
        self.value = float(value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0.0)


def make_table(headers: list[str], rows: list[list], min_height: int = 260, sortable: bool = True,
               sort_col: int = -1, descending: bool = False) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setStyleSheet("QTableWidget{border:none;}")
    table.setMinimumHeight(min_height)
    fill_table(table, rows)
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setSectionResizeMode(0, QHeaderView.Stretch)
    if sortable:
        table.horizontalHeader().setSortIndicator(sort_col, Qt.DescendingOrder if descending else Qt.AscendingOrder)
    table.setSortingEnabled(sortable)
    return table


def fill_table(table: QTableWidget, rows: list[list]) -> None:
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = NumItem(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else QTableWidgetItem(str(value))
            item.setFont(font(12, 700 if c == 0 else 500))
            table.setItem(r, c, item)
        table.setRowHeight(r, 38)
    table.setSortingEnabled(sorting)


# ───────────────────────── Автовыход при бездействии ─────────────────────────

class SessionGuard(QObject):
    """Если пользователь ничего не делает IDLE_LOGOUT_MINUTES минут — сеанс завершается."""

    def __init__(self, window, minutes: int = IDLE_LOGOUT_MINUTES):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(minutes * 60 * 1000)
        self.timer.timeout.connect(lambda: self.window.logout(auto=True))
        QApplication.instance().installEventFilter(self)
        self.timer.start()

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel):
            self.timer.start()
        return False

    def stop(self):
        self.timer.stop()
        try:
            QApplication.instance().removeEventFilter(self)
        except RuntimeError:
            pass


# ───────────────────────── Страницы главного окна ─────────────────────────

class FeaturePages:
    """Методы для HouseCheckWindow: профиль, аналитика, история, отчёты, выход."""

    def L(self, ru: str, kk: str, en: str) -> str:
        return {"ru": ru, "kk": kk, "en": en}.get(self.language, ru)

    def log(self, action: str, query: str = "", result: str = "") -> None:
        self.db.log(self.user, action, query, result)

    # ───── профиль ─────
    def build_profile(self):
        lay, h, _ = self.new_page("profile", self.L("Мой профиль", "Менің профилім", "My profile"),
                                  self.L("Личные данные, безопасность и активность", "Жеке деректер, қауіпсіздік және белсенділік", "Personal data, security and activity"))
        self.profile_lay = lay

    def refresh_profile(self):
        if not hasattr(self, "profile_lay"):
            return
        lay = self.profile_lay
        while lay.count() > 1:
            it = lay.takeAt(1)
            if it.widget(): it.widget().deleteLater()
            elif it.layout(): clear_layout(it.layout())
        u = self.db.get_user(self.user["id"]) if self.user.get("id") else self.user
        self.user.update(u or {})
        u = self.user
        hero = Card("dark", 28, hover=False); hero.set_padding(30, 26, 26, 26)
        name = u.get("full_name") or u.get("username", "")
        info = vbox(label(name, 28, "#FFFFFF", 800), label(f"@{u.get('username')} · {u.get('role')}", 14, "#C9D2E6", 600), spacing=4)
        btns = hbox(spacing=10)
        e = Button(self.L("Изменить профиль", "Профильді өзгерту", "Edit profile"), "primary", "edit"); e.clicked.connect(self.edit_profile)
        pw = Button(self.L("Сменить пароль", "Құпиясөзді өзгерту", "Change password"), "white", "lock"); pw.clicked.connect(self.change_password)
        out = Button(self.t("logout"), "white", "logout"); out.clicked.connect(lambda: self.logout())
        btns.addWidget(e); btns.addWidget(pw); btns.addWidget(out); btns.addStretch()
        info.addSpacing(10); info.addLayout(btns)
        m = Mascot(120); m.set_mood("happy")
        hero.layout_().addLayout(hbox(Avatar(name, 96), info, None, m, spacing=22, stretch_at=1))
        lay.addWidget(hero); fade_in(hero, 0, 420)

        details = Card("surface", 26, hover=False); details.set_padding(24, 20, 24, 20)
        details.layout_().addWidget(label(self.L("Личные данные", "Жеке деректер", "Personal details"), 18, "text", 800))
        g = QGridLayout(); g.setHorizontalSpacing(24); g.setVerticalSpacing(16)
        facts = [("user", self.L("Имя и фамилия", "Аты-жөні", "Full name"), u.get("full_name") or "—"),
                 ("mail", "E-mail", u.get("email") or self.L("не указана", "көрсетілмеген", "not set")),
                 ("chat", self.L("Телефон", "Телефон", "Phone"), u.get("phone") or "—"),
                 ("shield", self.L("Роль", "Рөл", "Role"), u.get("role", "viewer")),
                 ("calendar", self.L("Аккаунт создан", "Аккаунт құрылды", "Created"), u.get("created_at") or "—"),
                 ("history", self.L("Последний вход", "Соңғы кіру", "Last sign-in"), u.get("last_login") or "—")]
        for i, (ic, k, v) in enumerate(facts):
            g.addLayout(hbox(IconBubble(ic, "surface_muted", "accent", 40), vbox(label(k, 11, "text_muted", 600), label(str(v), 14, "text", 700), spacing=0), None, spacing=12), i // 3, i % 3)
        details.layout_().addLayout(g)
        if u.get("about"):
            details.layout_().addWidget(label(self.L("О себе", "Өзім туралы", "About"), 12, "text_muted", 700))
            details.layout_().addWidget(label(u["about"], 14, "text"))
        if not u.get("email"):
            details.layout_().addWidget(Badge(self.L("Добавьте почту — она нужна для восстановления пароля и отчётов",
                                                     "Поштаны қосыңыз — ол құпиясөзді қалпына келтіру үшін қажет",
                                                     "Add an e-mail to recover your password and receive reports"), "warning_soft", "warning", 12))
        lay.addWidget(details); fade_in(details, 80)

        hist = self.db.history(user_id=u.get("id"))
        counts = {}
        for row in hist:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        stats = QGridLayout(); stats.setSpacing(4)
        tiles = [self.stat_tile("history", "accent_soft", "accent", len(hist), self.L("Действий в истории", "Тарихтағы әрекеттер", "Actions logged")),
                 self.stat_tile("search", "sky", "#5B8DEF", counts.get("Поиск", 0), self.L("Поисковых запросов", "Іздеу сұраулары", "Searches")),
                 self.stat_tile("sparkle", "mint", "positive", counts.get("Вопрос Доми", 0), self.L("Вопросов Доми", "Домиге сұрақтар", "Questions to Domi")),
                 self.stat_tile("download", "lilac", "#7B6CF6", counts.get("Отчёт", 0) + counts.get("Отчёт на почту", 0), self.L("Отчётов", "Есептер", "Reports"))]
        for i, t in enumerate(tiles):
            stats.addWidget(t, 0, i); fade_in(t, 120 + i * 60)
        lay.addLayout(stats)
        lay.addLayout(self.section_title(self.L("Последние действия", "Соңғы әрекеттер", "Recent activity"), self.L("Вся история", "Барлық тарих", "Full history"), lambda: self.show_page("history")))
        tc = Card("surface", 24, hover=False); tc.set_padding(10, 10, 10, 10)
        tc.layout_().addWidget(make_table([self.L("Действие", "Әрекет", "Action"), self.L("Запрос", "Сұрау", "Query"), self.L("Время", "Уақыт", "Time")],
                                          [[r["action"], r["query"], r["created_at"]] for r in hist[:8]], 200, False))
        lay.addWidget(tc)
        lay.addStretch()

    def edit_profile(self):
        d = ProfileDialog(self.db, self.user, self)
        if d.exec() == QDialog.DialogCode.Accepted and d.updated:
            self.user.update(d.updated)
            self.log("Профиль изменён", d.updated.get("email", ""), "Данные профиля обновлены")
            toast(self, self.L("Профиль сохранён", "Профиль сақталды", "Profile saved"), "ok")
            self.rebuild_with_transition()

    def change_password(self):
        if ChangePasswordDialog(self.db, self.user, self).exec() == QDialog.DialogCode.Accepted:
            self.log("Смена пароля", "", "Пароль изменён")
            toast(self, self.L("Пароль изменён", "Құпиясөз өзгертілді", "Password changed"), "ok")

    # ───── аналитика ─────
    def build_analytics(self):
        lay, h, _ = self.new_page("analytics", self.L("Аналитика", "Талдау", "Analytics"),
                                  self.L("Графики, расчёты, выбор лучшего ЖК и ИИ-прогноз цены", "Графиктер, есептеулер, үздік ТҮК таңдау және ЖИ болжамы", "Charts, calculations, best choice and AI price forecast"))
        chk = Button(self.L("Проверить данные", "Деректерді тексеру", "Check data"), "secondary", "database"); chk.clicked.connect(self.check_data)
        exp = Button(self.L("Экспорт отчёта", "Есепті экспорттау", "Export report"), "secondary", "download"); exp.clicked.connect(self.export_report)
        mail = Button(self.L("На почту", "Поштаға", "E-mail"), "primary", "mail"); mail.clicked.connect(self.email_report)
        for b in (chk, exp, mail):
            h.addWidget(b)
        self.analytics_lay = lay

    def refresh_analytics(self):
        if not hasattr(self, "analytics_lay"):
            return
        lay = self.analytics_lay
        while lay.count() > 1:
            it = lay.takeAt(1)
            if it.widget(): it.widget().deleteLater()
            elif it.layout(): clear_layout(it.layout())
        rows = analytics.rows_for_analysis(self.db)
        s = analytics.summary(rows)
        stats = QGridLayout(); stats.setSpacing(4)
        tiles = [self.stat_tile("trophy", "accent_soft", "accent", s["avg_index"], self.L("Средний индекс", "Орташа индекс", "Mean index") + f"  (σ = {s['stdev_index']})", "", 1),
                 self.stat_tile("target", "sky", "#5B8DEF", s["median_index"], self.L("Медиана индекса", "Индекс медианасы", "Median index"), "", 1),
                 self.stat_tile("wallet", "mint", "positive", s["median_price"] / 1e6, self.L("Медиана цены, млн ₸", "Баға медианасы, млн ₸", "Median price, M ₸"), "", 1),
                 self.stat_tile("chart", "lilac", "#7B6CF6", s["price_index_corr"], self.L("Корреляция цена ↔ комфорт", "Баға ↔ жайлылық корреляциясы", "Price ↔ comfort correlation"), "", 2)]
        for i, t in enumerate(tiles):
            stats.addWidget(t, 0, i); fade_in(t, i * 60)
        lay.addLayout(stats)
        banner = Card("accent", 24, hover=False); banner.set_padding(22, 14, 22, 14)
        banner.layout_().addLayout(hbox(IconBubble("sparkle", "#FFFFFF", "accent", 40),
                                        label(self.L(f"Лучший индекс комфорта — {s['best']}. Самый доступный — {s['cheapest']}. Лучшее соотношение цена/комфорт — {s['best_value']}.",
                                                     f"Ең жоғары жайлылық — {s['best']}. Ең қолжетімді — {s['cheapest']}. Баға/жайлылық бойынша үздік — {s['best_value']}.",
                                                     f"Best comfort — {s['best']}. Most affordable — {s['cheapest']}. Best value — {s['best_value']}."), 14, "#FFFFFF", 700), spacing=14, stretch_at=1))
        lay.addWidget(banner)

        def chart_card(title, sub, widget):
            c = Card("surface", 26, hover=False); c.set_padding(22, 18, 22, 18)
            c.layout_().addWidget(label(title, 17, "text", 800)); c.layout_().addWidget(label(sub, 12, "text_muted"))
            c.layout_().addWidget(widget)
            return c

        g = QGridLayout(); g.setSpacing(4)
        districts = analytics.by_district(rows)
        g.addWidget(chart_card(self.L("Индекс комфорта по районам", "Аудандар бойынша жайлылық", "Comfort by district"),
                               self.L("Среднее по ЖК района", "Аудан ТҮК-терінің орташасы", "Average across complexes"),
                               HBarChart([(d["district"], d["avg_index"]) for d in districts], 100)), 0, 0)
        dist = analytics.rating_distribution(self.db.all_reviews())
        g.addWidget(chart_card(self.L("Распределение оценок", "Бағалардың таралуы", "Rating distribution"),
                               self.L(f"Всего отзывов: {sum(dist.values())}", f"Барлық пікір: {sum(dist.values())}", f"Reviews: {sum(dist.values())}"),
                               ColumnChart([(f"{k}★", v) for k, v in dist.items()])), 0, 1)
        rated = [r for r in rows if r["reviews"] and r["price"]]
        model = analytics.linear_regression([r["index"] for r in rated], [r["price"] / 1e6 for r in rated])
        g.addWidget(chart_card(self.L("Цена и комфорт", "Баға мен жайлылық", "Price vs comfort"),
                               self.L(f"Пунктир — линейная регрессия, R² = {model.r2:.2f}. Наведите на точку.", f"Үзік сызық — регрессия, R² = {model.r2:.2f}.", f"Dashed — regression line, R² = {model.r2:.2f}. Hover a dot."),
                               ScatterChart([(r["index"], r["price"] / 1e6, r["name"]) for r in rated], (model.slope, model.intercept),
                                            self.L("Индекс комфорта", "Жайлылық индексі", "Comfort index"), self.L("млн ₸", "млн ₸", "M ₸"))), 1, 0)
        cats = analytics.category_averages(rows)
        CAT_NAMES = self.CAT_NAMES
        g.addWidget(chart_card(self.L("Средние баллы по категориям", "Санаттар бойынша орташа балл", "Average by category"),
                               self.L("По всем ЖК с отзывами", "Пікірі бар барлық ТҮК", "All complexes with reviews"),
                               HBarChart([(CAT_NAMES[self.language].get(k, k), v) for k, v in cats.items()], 100)), 1, 1)
        lay.addLayout(g)

        # ── принятие решения ──
        lay.addLayout(self.section_title(self.L("Выбор лучшего ЖК", "Үздік ТҮК таңдау", "Choosing the best complex")))
        dc = Card("surface", 26, hover=False); dc.set_padding(22, 18, 22, 18)
        dc.layout_().addWidget(label(self.L(
            "Два метода многокритериального выбора: взвешенная сумма (WSM) и TOPSIS — близость к идеальному решению. "
            "Веса категорий берутся из раздела «Мой комфорт», цена — критерий затрат (меньше — лучше).",
            "Екі әдіс: салмақталған қосынды (WSM) және TOPSIS. Санат салмақтары «Менің жайлылығым» бөлімінен алынады.",
            "Two multi-criteria methods: Weighted Sum (WSM) and TOPSIS. Category weights come from “My comfort”; price is a cost criterion."), 13, "text_muted"))
        self.price_weight = QSpinBox(); self.price_weight.setRange(0, 10); self.price_weight.setValue(getattr(self, "_price_w", 3)); self.price_weight.setFixedHeight(40)
        self.rating_weight = QSpinBox(); self.rating_weight.setRange(0, 10); self.rating_weight.setValue(getattr(self, "_rating_w", 2)); self.rating_weight.setFixedHeight(40)
        run = Button(self.L("Рассчитать", "Есептеу", "Calculate"), "primary", "target"); run.clicked.connect(self.run_decision)
        cfg = Button(self.L("Настроить приоритеты", "Басымдықтарды баптау", "Set priorities"), "ghost", "sliders"); cfg.clicked.connect(lambda: self.show_page("comfort"))
        dc.layout_().addLayout(hbox(label(self.L("Вес цены", "Баға салмағы", "Price weight"), 12, "text_muted", 700, False), self.price_weight,
                                    label(self.L("Вес средней оценки", "Орташа баға салмағы", "Rating weight"), 12, "text_muted", 700, False), self.rating_weight,
                                    None, cfg, run, spacing=10))
        self.decision_box = QVBoxLayout(); self.decision_box.setSpacing(10)
        dc.layout_().addLayout(self.decision_box)
        lay.addWidget(dc)
        self.run_decision(log=False)

        # ── ИИ-прогноз ──
        lay.addLayout(self.section_title(self.L("ИИ-прогноз справедливой цены", "ЖИ: әділ баға болжамы", "AI fair-price forecast")))
        fc = Card("surface", 26, hover=False); fc.set_padding(22, 18, 22, 18)
        forecast, r2 = price_forecast(self.db)
        fc.layout_().addWidget(label(self.L(
            f"Модель обучается на всех ЖК каталога (линейная регрессия «цена ~ индекс комфорта») и предсказывает, сколько должен стоить ЖК с таким комфортом. "
            f"R² = {r2:.2f}: модель объясняет {r2 * 100:.0f}% разброса цен — остальное зависит от класса, локации и года постройки, поэтому прогноз ориентировочный.",
            f"Модель «баға ~ жайлылық индексі» сызықтық регрессиясы. R² = {r2:.2f} — болжам шамамен.",
            f"Linear regression “price ~ comfort index” over the whole catalogue. R² = {r2:.2f}: the forecast is indicative only."), 13, "text_muted"))
        fc.layout_().addWidget(make_table([self.L("ЖК", "ТҮК", "Complex"), self.L("Цена, ₸", "Баға, ₸", "Price, ₸"), self.L("Прогноз, ₸", "Болжам, ₸", "Forecast, ₸"),
                                           self.L("Отклонение, %", "Ауытқу, %", "Deviation, %"), self.L("Вывод", "Қорытынды", "Verdict")],
                                          [[f.name, f.actual, f.predicted, f.deviation_pct, f.verdict] for f in forecast], 300, sort_col=3))
        lay.addWidget(fc)

        # ── таблица ──
        lay.addLayout(self.section_title(self.L("Таблица ЖК", "ТҮК кестесі", "Complexes table")))
        tc = Card("surface", 26, hover=False); tc.set_padding(16, 14, 16, 14)
        self.table_search = SearchBox(self.L("Фильтр по названию…", "Атауы бойынша сүзгі…", "Filter by name…"), "", 42)
        self.table_district = QComboBox(); self.table_district.setFixedHeight(42); self.table_district.setMinimumWidth(220)
        self.table_district.addItems([self.t("all")] + sorted({r["district"] for r in rows}))
        tc.layout_().addLayout(hbox(self.table_search, self.table_district, spacing=10, stretch_at=0))
        self.analytics_rows = rows
        self.data_table = make_table(["ЖК", self.L("Район", "Аудан", "District"), self.L("Класс", "Класс", "Class"), self.L("Цена, ₸", "Баға, ₸", "Price, ₸"),
                                      self.L("Индекс", "Индекс", "Index"), self.L("Оценка", "Баға", "Rating"), self.L("Отзывов", "Пікір", "Reviews")], [], 420, sort_col=4, descending=True)
        self.data_table.setToolTip(self.L("Нажмите на заголовок столбца для сортировки", "Сұрыптау үшін баған тақырыбын басыңыз", "Click a header to sort"))
        tc.layout_().addWidget(self.data_table)
        self.table_search.edit.textChanged.connect(lambda _: self._fill_data_table())
        self.table_district.currentIndexChanged.connect(lambda _: self._fill_data_table())
        self._fill_data_table()
        lay.addWidget(tc)
        lay.addStretch()

    def _fill_data_table(self):
        q = self.table_search.edit.text().strip().lower()
        d = self.table_district.currentText() if self.table_district.currentIndex() > 0 else ""
        rows = [r for r in self.analytics_rows if (not q or q in r["name"].lower()) and (not d or r["district"] == d)]
        self.data_table.setSortingEnabled(False)
        self._table_ids = [r["id"] for r in rows]
        fill_table(self.data_table, [[r["name"], r["district"], r["housing_class"], r["price"], r["index"], r["rating"], r["reviews"]] for r in rows])
        # после сортировки строки переставляются — храним id в самой ячейке
        for i, r in enumerate(rows):
            self.data_table.item(i, 0).setData(Qt.UserRole, r["id"])
        self.data_table.setSortingEnabled(True)
        if getattr(self.data_table, "_wired", False):
            return
        self.data_table._wired = True
        self.data_table.cellDoubleClicked.connect(lambda row, _c: self.open_detail(int(self.data_table.item(row, 0).data(Qt.UserRole))))

    def run_decision(self, log: bool = True):
        if not hasattr(self, "decision_box"):
            return
        self._price_w, self._rating_w = self.price_weight.value(), self.rating_weight.value()
        clear_layout(self.decision_box)
        criteria = criteria_from_preferences(self.db.preferences(), self._price_w, self._rating_w)
        alts = alternatives_from_db(self.db)
        if not alts:
            self.decision_box.addWidget(label(self.L("Нет ЖК с отзывами для расчёта.", "Есептеуге пікірі бар ТҮК жоқ.", "No complexes with reviews."), 13, "text_muted"))
            return
        wsm, tps = weighted_sum(alts, criteria), topsis(alts, criteria)
        rho = agreement(wsm, tps)
        tps_rank = {r.id: (r.rank, r.score) for r in tps}
        best_same = wsm[0].id == tps[0].id
        win = Card("dark", 22, hover=False); win.set_padding(20, 14, 20, 14)
        title = self.L("Рекомендуемое решение", "Ұсынылған шешім", "Recommended choice")
        text = (self.L(f"Оба метода выбрали «{wsm[0].name}» — решение устойчиво.", f"Екі әдіс те «{wsm[0].name}» таңдады.", f"Both methods pick “{wsm[0].name}” — a robust choice.")
                if best_same else
                self.L(f"WSM: «{wsm[0].name}», TOPSIS: «{tps[0].name}». Методы расходятся — сравните их на странице «Сравнение».",
                       f"WSM: «{wsm[0].name}», TOPSIS: «{tps[0].name}».", f"WSM picks “{wsm[0].name}”, TOPSIS picks “{tps[0].name}”."))
        open_btn = Button(self.L("Открыть", "Ашу", "Open"), "primary", "next", "sm"); open_btn.clicked.connect(lambda _=False, i=wsm[0].id: self.open_detail(i))
        win.layout_().addLayout(hbox(IconBubble("trophy", "#2B3A6B", "#FFB37A", 44),
                                     vbox(label(title, 12, "nav_muted", 800), label(text, 15, "#FFFFFF", 700), label(explain(wsm[0], criteria), 12, "#C9D2E6"), spacing=2),
                                     open_btn, spacing=14, stretch_at=1))
        self.decision_box.addWidget(win)
        total = sum(c.weight for c in criteria) or 1
        weights = " · ".join(f"{c.title} {c.weight / total:.0%}" for c in criteria)
        self.decision_box.addWidget(label(self.L("Нормированные веса: ", "Салмақтар: ", "Normalised weights: ") + weights, 12, "text_muted"))
        self.decision_box.addWidget(label(self.L(f"Согласованность методов (корреляция Спирмена ρ) = {rho}", f"Әдістердің келісімі ρ = {rho}", f"Method agreement (Spearman ρ) = {rho}"), 12, "text_muted", 700))
        self.decision_box.addWidget(make_table([self.L("ЖК", "ТҮК", "Complex"), self.L("Место WSM", "WSM орны", "WSM rank"), self.L("Балл WSM", "WSM балы", "WSM score"),
                                                self.L("Место TOPSIS", "TOPSIS орны", "TOPSIS rank"), self.L("Близость TOPSIS", "TOPSIS жақындығы", "TOPSIS closeness")],
                                               [[r.name, r.rank, r.score, tps_rank[r.id][0], tps_rank[r.id][1]] for r in wsm], 320, sort_col=1))
        if log:
            self.log("Выбор ЖК", f"цена×{self._price_w}, оценка×{self._rating_w}", f"WSM: {wsm[0].name}; TOPSIS: {tps[0].name}; ρ={rho}")
            toast(self, self.L("Расчёт выполнен", "Есептелді", "Calculated"), "ok", 1600)

    def check_data(self):
        issues = self.db.validate_data()
        self.log("Проверка данных", "", f"Найдено проблем: {len(issues)}")
        if not issues:
            QMessageBox.information(self, self.L("Проверка данных", "Деректерді тексеру", "Data check"),
                                    self.L("Ошибок не найдено: база цела, оценки 1–5, координаты в пределах Астаны, ссылки и почта корректны.",
                                           "Қате табылмады.", "No problems found."))
            return
        text = "\n".join("• " + i["text"] for i in issues[:30]) + (f"\n… и ещё {len(issues) - 30}" if len(issues) > 30 else "")
        if self.can("manage"):
            if QMessageBox.question(self, self.L("Найдены ошибки", "Қателер табылды", "Problems found"),
                                    text + "\n\n" + self.L("Исправить автоматически то, что возможно?", "Автоматты түзету керек пе?", "Fix automatically where possible?"),
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                fixed = self.db.repair_data()
                self.log("Исправление данных", "", f"Исправлено записей: {fixed}")
                toast(self, self.L(f"Исправлено записей: {fixed}", f"Түзетілді: {fixed}", f"Fixed: {fixed}"), "ok")
                self.refresh_all()
        else:
            QMessageBox.warning(self, self.L("Найдены ошибки", "Қателер табылды", "Problems found"), text)

    # ───── отчёты ─────
    def export_report(self):
        default = reports.default_report_path("pdf")
        path, _ = QFileDialog.getSaveFileName(self, self.L("Сохранить отчёт", "Есепті сақтау", "Save report"), str(default),
                                              "PDF (*.pdf);;HTML (*.html);;CSV — Excel (*.csv);;JSON (*.json)")
        if not path:
            return
        try:
            data = reports.build_report_data(self.db, self.user)
            saved = reports.save_report(data, Path(path))
        except Exception as error:  # noqa: BLE001
            self.log("Ошибка отчёта", path, str(error))
            QMessageBox.critical(self, self.L("Не удалось сохранить", "Сақталмады", "Could not save"), str(error))
            return
        self.log("Отчёт", saved.name, str(saved))
        box = QMessageBox(self); box.setWindowTitle(self.L("Отчёт сохранён", "Есеп сақталды", "Report saved")); box.setText(str(saved))
        open_btn = box.addButton(self.L("Открыть", "Ашу", "Open"), QMessageBox.AcceptRole); box.addButton("OK", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved)))

    def email_report(self):
        d = SendReportDialog(self.user, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        to, subject, body, ext = d.to.text().strip(), d.subject.text().strip(), d.message.toPlainText(), d.extension
        try:
            data = reports.build_report_data(self.db, self.user)
            path = reports.save_report(data, reports.default_report_path(ext))
        except Exception as error:  # noqa: BLE001
            QMessageBox.critical(self, self.L("Ошибка отчёта", "Есеп қатесі", "Report error"), str(error)); return
        html = reports.render_html(data)
        toast(self, self.L("Отправляем письмо…", "Хат жіберілуде…", "Sending…"), "info")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(result: mailer.SendResult):
            QApplication.restoreOverrideCursor()
            self.log("Отчёт на почту", to, result.detail)
            if result.delivered:
                toast(self, result.detail, "ok")
            else:
                QMessageBox.information(self, self.L("Письмо сохранено", "Хат сақталды", "E-mail saved"),
                                        self.L("SMTP не настроен (SMTP_HOST, SMTP_USER, SMTP_PASSWORD в .env), поэтому письмо с отчётом сохранено в файл:\n",
                                               "SMTP бапталмаған, хат файлға сақталды:\n", "SMTP is not configured, the e-mail was saved to:\n") + str(result.path))
                open_folder(result.path)

        def failed(message: str):
            QApplication.restoreOverrideCursor()
            self.log("Ошибка почты", to, message)
            QMessageBox.warning(self, self.L("Письмо не отправлено", "Хат жіберілмеді", "E-mail not sent"),
                                message + "\n\n" + self.L(f"Отчёт сохранён локально: {path}", f"Есеп сақталды: {path}", f"The report is saved locally: {path}"))

        run_async(self, lambda: mailer.send_email(to, subject, body, [path], html), done, failed)

    # ───── история ─────
    def build_history(self):
        lay, h, _ = self.new_page("history", self.L("История", "Тарих", "History"),
                                  self.L("Запросы, расчёты и результаты сохраняются в базе данных", "Сұраулар мен нәтижелер дерекқорда сақталады", "Requests and results are stored in the database"))
        exp = Button(self.L("Экспорт CSV", "CSV экспорт", "Export CSV"), "secondary", "download"); exp.clicked.connect(self.export_history); h.addWidget(exp)
        clr = Button(self.L("Очистить мою историю", "Тарихымды тазалау", "Clear my history"), "danger", "trash"); clr.clicked.connect(self.clear_history); h.addWidget(clr)
        bar = Card("surface", 24, hover=False); bar.set_padding(14, 12, 14, 12)
        self.history_search = SearchBox(self.L("Поиск по запросам и результатам…", "Сұраулар бойынша іздеу…", "Search requests and results…"), "", 44)
        self.history_action = QComboBox(); self.history_action.setFixedHeight(44); self.history_action.setMinimumWidth(200)
        self.history_from = QDateEdit(QDate.currentDate().addMonths(-1)); self.history_to = QDateEdit(QDate.currentDate())
        for w in (self.history_from, self.history_to):
            w.setCalendarPopup(True); w.setDisplayFormat("dd.MM.yyyy"); w.setFixedHeight(44)
        self.history_scope = Segmented([self.L("Мои", "Менің", "Mine"), self.L("Все пользователи", "Барлығы", "All users")], 0)
        self.history_scope.setVisible(self.user.get("role") == "super_admin")
        self._hist_timer = QTimer(self); self._hist_timer.setSingleShot(True); self._hist_timer.setInterval(200); self._hist_timer.timeout.connect(self.refresh_history)
        self.history_search.edit.textChanged.connect(lambda _: self._hist_timer.start())
        self.history_action.currentIndexChanged.connect(lambda _: self.refresh_history())
        self.history_from.dateChanged.connect(lambda _: self.refresh_history()); self.history_to.dateChanged.connect(lambda _: self.refresh_history())
        self.history_scope.changed.connect(lambda _: self.refresh_history())
        bar.layout_().addLayout(hbox(self.history_search, self.history_action, spacing=10, stretch_at=0))
        bar.layout_().addLayout(hbox(label(self.L("Период:", "Кезең:", "Period:"), 12, "text_muted", 700, False), self.history_from, label("—", 12, "text_muted"), self.history_to, None, self.history_scope, spacing=8))
        lay.addWidget(bar)
        self.history_count = label("", 13, "text_muted", 600); self.history_count.setContentsMargins(12, 0, 0, 0); lay.addWidget(self.history_count)
        tc = Card("surface", 24, hover=False); tc.set_padding(10, 10, 10, 10)
        self.history_table = make_table([self.L("Действие", "Әрекет", "Action"), self.L("Запрос", "Сұрау", "Query"), self.L("Результат", "Нәтиже", "Result"),
                                         self.L("Пользователь", "Пайдаланушы", "User"), self.L("Время", "Уақыт", "Time")], [], 480, sort_col=4, descending=True)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.history_table.setWordWrap(False)
        tc.layout_().addWidget(self.history_table)
        lay.addWidget(tc); lay.addStretch()

    def _history_rows(self) -> list[dict]:
        all_users = self.user.get("role") == "super_admin" and self.history_scope.index == 1
        action = self.history_action.currentText() if self.history_action.currentIndex() > 0 else ""
        return self.db.history(None if all_users else self.user.get("id"), self.history_search.edit.text(), action,
                               self.history_from.date().toString("yyyy-MM-dd"), self.history_to.date().toString("yyyy-MM-dd"))

    def refresh_history(self):
        if not hasattr(self, "history_table"):
            return
        cur = self.history_action.currentText()
        self.history_action.blockSignals(True); self.history_action.clear()
        self.history_action.addItems([self.L("Все действия", "Барлық әрекет", "All actions")] + self.db.history_actions())
        idx = self.history_action.findText(cur)
        self.history_action.setCurrentIndex(idx if idx > 0 else 0); self.history_action.blockSignals(False)
        rows = self._history_rows()
        self.history_count.setText(self.L(f"Записей: {len(rows)}", f"Жазбалар: {len(rows)}", f"Records: {len(rows)}"))
        fill_table(self.history_table, [[r["action"], r["query"], r["result"], r["username"], r["created_at"]] for r in rows])
        for i, r in enumerate(rows):
            self.history_table.item(i, 2).setToolTip(r["result"])

    def export_history(self):
        path, _ = QFileDialog.getSaveFileName(self, self.L("Экспорт истории", "Тарихты экспорттау", "Export history"),
                                              str(reports.REPORTS_DIR / f"history-{datetime.now():%Y%m%d}.csv"), "CSV (*.csv)")
        if not path:
            return
        rows = self._history_rows()
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Время", "Пользователь", "Действие", "Запрос", "Результат"])
                for r in rows:
                    w.writerow([r["created_at"], r["username"], r["action"], r["query"], r["result"]])
        except OSError as error:
            QMessageBox.critical(self, self.L("Ошибка", "Қате", "Error"), str(error)); return
        self.log("Экспорт истории", Path(path).name, f"Строк: {len(rows)}")
        toast(self, self.L(f"Сохранено строк: {len(rows)}", f"Сақталды: {len(rows)}", f"Saved {len(rows)} rows"), "ok")

    def clear_history(self):
        if QMessageBox.question(self, self.L("Очистить историю?", "Тарихты тазалау?", "Clear history?"),
                                self.L("Все ваши записи истории будут удалены без возможности восстановления.", "Барлық жазбалар жойылады.", "All your history records will be deleted permanently."),
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            n = self.db.clear_history(self.user.get("id"))
            toast(self, self.L(f"Удалено записей: {n}", f"Жойылды: {n}", f"Deleted: {n}"), "ok")
            self.refresh_history()

    # ───── ИИ: объяснение анализа на странице ЖК ─────
    def ai_explanation_card(self, reviews: list[dict], result) -> Card:
        ex = explain_analysis(reviews, result)
        card = Card("surface", 26, hover=False); card.set_padding(22, 18, 22, 18)
        color = {"высокая": ("positive_soft", "positive"), "средняя": ("warning_soft", "warning")}.get(ex.confidence, ("danger_soft", "danger"))
        card.layout_().addLayout(hbox(label(self.L("Как ИИ пришёл к выводу", "ЖИ қалай қорытынды жасады", "How the AI reached this"), 17, "text", 800, False), None,
                                      Badge(self.L(f"Уверенность: {ex.confidence} · {ex.confidence_pct}%", f"Сенімділік: {ex.confidence_pct}%", f"Confidence: {ex.confidence_pct}%"), *color, 12)))
        for r in ex.reasons:
            card.layout_().addWidget(label("•  " + r, 13, "text"))
        card.layout_().addWidget(label(self.L("Ограничения", "Шектеулер", "Limitations"), 13, "warning", 800))
        for r in ex.limitations:
            card.layout_().addWidget(label("–  " + r, 12, "text_muted"))
        return card

    # ───── выход ─────
    def logout(self, auto: bool = False):
        if getattr(self, "_logging_out", False):
            return
        self._logging_out = True
        self.log("Выход" if not auto else "Автовыход", "", "Сеанс завершён" + (f" после {IDLE_LOGOUT_MINUTES} мин бездействия" if auto else ""))
        if not self.close():  # пользователь отменил (несохранённая заметка)
            self._logging_out = False
            return
        if getattr(self, "guard", None):
            self.guard.stop()
        # закрываем доступ к защищённым данным текущего сеанса
        self.chat.clear(); self.compare_ids.clear(); self.user = {}
        QApplication.clipboard().clear()
        if auto:
            QMessageBox.information(None, "HouseCheck AI", f"Сеанс завершён автоматически: {IDLE_LOGOUT_MINUTES} минут без действий.")
        self.logged_out.emit()
