"""Тесты авторизации: регистрация, вход, профиль, смена и восстановление пароля."""

import unittest

from database import AuthError
from tests.helpers import temp_db


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.db = temp_db(seed_demo=False)
        self.user = self.db.register_user("Айгерим Серикова", "Aigerim@Mail.kz", "aigerim", "secret123", "secret123")

    def tearDown(self):
        self.db.close()

    def test_register_defaults(self):
        self.assertEqual(self.user["role"], "viewer")
        self.assertEqual(self.user["email"], "aigerim@mail.kz")
        stored = self.db.connection.execute("SELECT password_hash FROM users WHERE id=?", (self.user["id"],)).fetchone()[0]
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn("secret123", stored)

    def test_register_validation(self):
        cases = [
            ("", "a@b.kz", "user1", "secret123", "secret123"),          # пустое имя
            ("Имя Фамилия", "not-an-email", "user1", "secret123", "secret123"),
            ("Имя Фамилия", "a@b.kz", "u", "secret123", "secret123"),    # короткий логин
            ("Имя Фамилия", "a@b.kz", "user1", "short1", "short1"),      # короткий пароль
            ("Имя Фамилия", "a@b.kz", "user1", "onlyletters", "onlyletters"),
            ("Имя Фамилия", "a@b.kz", "user1", "secret123", "secret124"),  # не совпадают
            ("Имя Фамилия", "aigerim@mail.kz", "user2", "secret123", "secret123"),  # почта занята
            ("Имя Фамилия", "new@mail.kz", "aigerim", "secret123", "secret123"),     # логин занят
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(AuthError):
                self.db.register_user(*args)

    def test_login_by_username_or_email(self):
        self.assertEqual(self.db.authenticate("aigerim", "secret123")["id"], self.user["id"])
        self.assertEqual(self.db.authenticate("AIGERIM@mail.kz", "secret123")["id"], self.user["id"])
        self.assertIsNone(self.db.authenticate("aigerim", "wrong-pass1"))
        self.assertIsNone(self.db.authenticate("nobody", "secret123"))
        self.assertTrue(self.db.get_user(self.user["id"])["last_login"])

    def test_super_admin_exists(self):
        self.assertEqual(self.db.authenticate("super_admin", "super_admin")["role"], "super_admin")

    def test_update_profile(self):
        u = self.db.update_profile(self.user["id"], "Айгерим С.", "new@mail.kz", "+7 701 123 45 67", "Ищу 2-комнатную")
        self.assertEqual((u["email"], u["phone"]), ("new@mail.kz", "+7 701 123 45 67"))
        with self.assertRaises(AuthError):
            self.db.update_profile(self.user["id"], "Айгерим", "bad@", "")
        with self.assertRaises(AuthError):
            self.db.update_profile(self.user["id"], "Айгерим", "x@mail.kz", "12")

    def test_change_password(self):
        with self.assertRaises(AuthError):
            self.db.change_password(self.user["id"], "wrong", "newsecret1", "newsecret1")
        with self.assertRaises(AuthError):
            self.db.change_password(self.user["id"], "secret123", "secret123", "secret123")
        self.db.change_password(self.user["id"], "secret123", "newsecret1", "newsecret1")
        self.assertIsNone(self.db.authenticate("aigerim", "secret123"))
        self.assertIsNotNone(self.db.authenticate("aigerim", "newsecret1"))

    def test_reset_code_flow(self):
        with self.assertRaises(AuthError):
            self.db.create_reset_code("unknown@mail.kz")
        user, code = self.db.create_reset_code("aigerim@mail.kz")
        self.assertRegex(code, r"^\d{6}$")
        wrong = "000000" if code != "000000" else "111111"
        with self.assertRaises(AuthError):
            self.db.reset_password_with_code("aigerim@mail.kz", wrong, "fresh1234", "fresh1234")
        self.db.reset_password_with_code("aigerim@mail.kz", code, "fresh1234", "fresh1234")
        self.assertIsNotNone(self.db.authenticate("aigerim", "fresh1234"))
        with self.assertRaises(AuthError):  # код одноразовый
            self.db.reset_password_with_code("aigerim@mail.kz", code, "again1234", "again1234")

    def test_reset_code_expiry_and_attempts(self):
        _, code = self.db.create_reset_code("aigerim@mail.kz")
        self.db.connection.execute("UPDATE reset_codes SET expires_at = datetime('now', '-1 minute')")
        with self.assertRaisesRegex(AuthError, "истёк"):
            self.db.verify_reset_code("aigerim@mail.kz", code)
        _, code = self.db.create_reset_code("aigerim@mail.kz")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.db.verify_reset_code("aigerim@mail.kz", wrong)
        with self.assertRaisesRegex(AuthError, "Слишком много"):
            self.db.verify_reset_code("aigerim@mail.kz", code)

    def test_code_is_not_stored_in_plain_text(self):
        _, code = self.db.create_reset_code("aigerim@mail.kz")
        stored = self.db.connection.execute("SELECT code_hash FROM reset_codes ORDER BY id DESC").fetchone()[0]
        self.assertNotEqual(stored, code)


if __name__ == "__main__":
    unittest.main()
