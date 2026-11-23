"""Отправка писем: отчёты, коды восстановления пароля.

Настройки SMTP берутся только из локального .env (в Git не попадают):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_SECURITY=ssl|starttls|none

Если SMTP не настроен, письмо не теряется: оно сохраняется в папку outbox
в виде .eml-файла, который можно открыть почтовой программой. Так приложение
работает и без интернета, и без почтового аккаунта.
"""

from __future__ import annotations

import mimetypes
import os
import smtplib
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from config import DATA_DIR, load_local_env
from validators import email_error

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


class MailError(Exception):
    """Понятная пользователю ошибка отправки."""


@dataclass
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    sender: str
    security: str  # ssl | starttls | none

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


@dataclass
class SendResult:
    delivered: bool          # True — ушло через SMTP, False — сохранено в outbox
    detail: str              # что произошло, для сообщения пользователю
    path: Path | None = None  # путь к .eml, если письмо сохранено локально


def load_settings() -> SmtpSettings:
    load_local_env()
    port_raw = os.getenv("SMTP_PORT", "").strip()
    security = os.getenv("SMTP_SECURITY", "").strip().lower() or ("ssl" if port_raw == "465" else "starttls")
    try:
        port = int(port_raw) if port_raw else (465 if security == "ssl" else 587)
    except ValueError:
        port = 587
    user = os.getenv("SMTP_USER", "").strip()
    return SmtpSettings(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=port,
        user=user,
        password=os.getenv("SMTP_PASSWORD", "").strip(),
        sender=os.getenv("SMTP_FROM", "").strip() or user,
        security=security if security in {"ssl", "starttls", "none"} else "starttls",
    )


def build_message(to: str, subject: str, body: str, sender: str, attachments: list[Path] | None = None, html: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender or "HouseCheck AI <no-reply@housecheck.local>"
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain="housecheck.local")
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for path in attachments or []:
        path = Path(path)
        if not path.exists():
            raise MailError(f"Файл вложения не найден: {path.name}")
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise MailError(f"Вложение {path.name} больше 15 МБ — почтовые сервисы его не примут.")
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return message


def save_to_outbox(message: EmailMessage, outbox: Path | None = None) -> Path:
    outbox = outbox or DATA_DIR / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = outbox / f"{stamp}.eml"
    path.write_bytes(bytes(message))
    return path


def send_email(to: str, subject: str, body: str, attachments: list[Path] | None = None, html: str | None = None,
               settings: SmtpSettings | None = None, timeout: float = 15.0, outbox: Path | None = None) -> SendResult:
    """Отправляет письмо. Ошибки переводятся в MailError с понятным текстом."""
    error = email_error(to)
    if error:
        raise MailError(error)
    settings = settings or load_settings()
    message = build_message(to.strip(), subject, body, settings.sender, attachments, html)

    if not settings.configured:
        path = save_to_outbox(message, outbox)
        return SendResult(False, "SMTP не настроен — письмо сохранено в папку outbox.", path)

    try:
        if settings.security == "ssl":
            server = smtplib.SMTP_SSL(settings.host, settings.port, timeout=timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.host, settings.port, timeout=timeout)
        with server:
            server.ehlo()
            if settings.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if settings.user:
                server.login(settings.user, settings.password)
            refused = server.send_message(message)
        if refused:
            raise MailError("Сервер отклонил адрес получателя: " + ", ".join(refused))
        return SendResult(True, f"Письмо отправлено на {to}.")
    except MailError:
        raise
    except smtplib.SMTPAuthenticationError:
        raise MailError("Почтовый сервер не принял логин или пароль (SMTP_USER / SMTP_PASSWORD). "
                        "Для Gmail и Mail.ru нужен «пароль приложения».") from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError(f"Сервер отклонил адрес получателя {to}.") from None
    except smtplib.SMTPSenderRefused:
        raise MailError("Сервер отклонил адрес отправителя (SMTP_FROM).") from None
    except (socket.timeout, TimeoutError):
        raise MailError("Почтовый сервер не ответил вовремя. Проверьте интернет и SMTP_HOST/SMTP_PORT.") from None
    except smtplib.SMTPException as exc:  # до OSError: SMTPException — его подкласс
        raise MailError(f"Ошибка почтового сервера: {exc}") from None
    except (socket.gaierror, ConnectionError, OSError) as exc:
        raise MailError(f"Не удалось подключиться к {settings.host}:{settings.port} — {exc}.") from None
