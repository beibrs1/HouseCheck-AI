"""Тесты почты и отчётов. Реальные письма не отправляются: SMTP подменяется заглушкой."""

import os
import smtplib
import tempfile
import unittest
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

import mailer
import reports
from tests.helpers import temp_db
from validators import email_error

SETTINGS = mailer.SmtpSettings("smtp.example.com", 587, "user@example.com", "app-password", "user@example.com", "starttls")


class EmailValidationTests(unittest.TestCase):
    def test_valid(self):
        for e in ("name@mail.kz", "first.last+tag@gmail.com", "a_b@sub.domain.org"):
            self.assertEqual(email_error(e), "", e)

    def test_invalid(self):
        for e in ("", "plain", "a@b", "@mail.kz", "a@@mail.kz", "a..b@mail.kz", "a b@mail.kz", "a@mail.k"):
            self.assertNotEqual(email_error(e), "", e)


class SendTests(unittest.TestCase):
    def setUp(self):
        self.outbox = Path(tempfile.mkdtemp())

    def test_invalid_address_rejected_before_sending(self):
        with self.assertRaises(mailer.MailError):
            mailer.send_email("bad", "s", "b", settings=SETTINGS)

    def test_without_smtp_saves_eml(self):
        empty = mailer.SmtpSettings("", 587, "", "", "", "starttls")
        result = mailer.send_email("to@mail.kz", "Тема", "Текст", settings=empty, outbox=self.outbox)
        self.assertFalse(result.delivered)
        msg = message_from_bytes(result.path.read_bytes(), policy=policy.default)
        self.assertEqual(msg["To"], "to@mail.kz")
        self.assertEqual(msg["Subject"], "Тема")

    @mock.patch("mailer.smtplib.SMTP")
    def test_success_with_attachment(self, smtp_cls):
        server = mock.MagicMock(); server.__enter__.return_value = server
        server.send_message.return_value = {}
        smtp_cls.return_value = server
        attachment = self.outbox / "report.csv"; attachment.write_text("a;b", encoding="utf-8")
        result = mailer.send_email("to@mail.kz", "Отчёт", "Текст", [attachment], settings=SETTINGS)
        self.assertTrue(result.delivered)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("user@example.com", "app-password")
        sent = server.send_message.call_args[0][0]
        self.assertEqual([p.get_filename() for p in sent.iter_attachments()], ["report.csv"])

    @mock.patch("mailer.smtplib.SMTP")
    def test_errors_are_translated(self, smtp_cls):
        server = mock.MagicMock(); server.__enter__.return_value = server
        smtp_cls.return_value = server
        cases = [
            (smtplib.SMTPAuthenticationError(535, b"bad"), "логин или пароль"),
            (smtplib.SMTPRecipientsRefused({"to@mail.kz": (550, b"no")}), "получателя"),
            (smtplib.SMTPServerDisconnected("gone"), "почтового сервера"),
            (TimeoutError(), "не ответил"),
        ]
        for error, text in cases:
            with self.subTest(error=type(error).__name__):
                server.login.side_effect = error
                with self.assertRaisesRegex(mailer.MailError, text):
                    mailer.send_email("to@mail.kz", "s", "b", settings=SETTINGS)

    @mock.patch("mailer.smtplib.SMTP", side_effect=ConnectionRefusedError("refused"))
    def test_connection_refused(self, _):
        with self.assertRaisesRegex(mailer.MailError, "подключиться"):
            mailer.send_email("to@mail.kz", "s", "b", settings=SETTINGS)

    def test_missing_attachment(self):
        with self.assertRaisesRegex(mailer.MailError, "не найден"):
            mailer.send_email("to@mail.kz", "s", "b", [self.outbox / "nope.pdf"], settings=SETTINGS)


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = temp_db()
        cls.data = reports.build_report_data(cls.db, {"username": "tester"})
        cls.dir = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_data_complete(self):
        for key in ("summary", "districts", "ratings", "wsm", "topsis", "forecast", "rows"):
            self.assertIn(key, self.data)
        self.assertEqual(len(self.data["rows"]), 14)

    def test_html_csv_json(self):
        html = reports.save_report(self.data, self.dir / "r.html").read_text(encoding="utf-8")
        self.assertIn("TOPSIS", html); self.assertIn("Демо-данные", html)
        csv_text = reports.save_report(self.data, self.dir / "r.csv").read_text(encoding="utf-8-sig")
        self.assertEqual(len(csv_text.strip().splitlines()), 15)
        self.assertTrue((reports.save_report(self.data, self.dir / "r.json")).stat().st_size > 1000)

    def test_pdf(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        pdf = reports.save_report(self.data, self.dir / "r.pdf")
        self.assertEqual(pdf.read_bytes()[:4], b"%PDF")


if __name__ == "__main__":
    unittest.main()
