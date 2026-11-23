# Соответствие требованиям

| Требование | Где реализовано |
|---|---|
| Дизайн: макет в Figma, главное окно, кнопки, меню, поля ввода | Figma-файл «HouseCheck AI 2.0 — Презентация», кликабельный прототип `prototype/index.html`; `main.py` (`HouseCheckWindow`), `ui_kit.py`, `theme.qss` |
| Регистрация: окно, имя / почта / пароль, повтор пароля | `features.py` → `RegisterDialog`; `database.py` → `register_user`; `validators.py` |
| Вход: окно, кнопка «Войти», сообщение о неверном пароле | `main.py` → `LoginDialog.try_login`; `database.py` → `authenticate` (PBKDF2-SHA256) |
| Личный профиль: данные пользователя, «Изменить профиль» | `features.py` → `build_profile`, `ProfileDialog`; `database.py` → `get_user`, `update_profile` |
| Пароль: смена, «Забыли пароль?», ввод кода подтверждения | `features.py` → `ChangePasswordDialog`, `ForgotPasswordDialog`; `database.py` → `change_password`, `create_reset_code`, `verify_reset_code`, `reset_password_with_code` |
| Главное меню и навигация, открытие и закрытие разделов | `main.py` → `sidebar`, `show_page`, `AnimatedStack`, палитра ⌘K, кнопки «Назад» |
| Работа с данными: формы ввода и редактирования, добавление и удаление, вывод сохранённого | `main.py` → `DevelopmentDialog`, `add/edit/delete_development`, заметки; каталог, карточка ЖК |
| Поиск и фильтры: строка поиска, фильтры, сортировка | Каталог (поиск, район, класс, покупка/аренда, 6 сортировок), отзывы, история, таблица в «Аналитике» |
| Таблицы и графики | `features.py` → `HBarChart`, `ColumnChart`, `ScatterChart`, `make_table` (сортировка по столбцу) |
| Расчёты: математические вычисления, данные для графиков, итоговые показатели | `analytics.py` → `mean`, `median`, `stdev`, `pearson`, `linear_regression`, `summary`, `by_district`, `rating_distribution` |
| Принятие решений: метод, оценка по критериям, лучшее решение | `decision.py` → `weighted_sum` (WSM), `topsis` (TOPSIS), `agreement`, `explain` |
| ИИ: своя функция, анализ и прогноз, рекомендации, объяснение и ограничения | `analyzer.py` (тональность по 5 категориям), `ai_insights.py` (`price_forecast`, `recommend`, `explain_analysis`), `assistant_engine.py` (Доми) |
| Почта: сервис, проверка адреса, отправка отчётов, ошибки отправки | `mailer.py` → `send_email`, `MailError`; `validators.email_error`; `features.py` → `email_report` |
| Проверка данных: ввод, ошибочные значения, ошибки в базе | `validators.py`; `database.py` → `validate_data`, `repair_data`, проверки в `add_development` / `add_review` / `import_file` |
| История: запросы и результаты, чтение из базы, поиск и фильтр | таблица `history`; `database.py` → `log`, `history`, `history_actions`; `features.py` → `build_history` |
| Отчёты: файл, данные для экспорта, сохранение результатов | `reports.py` → `build_report_data`, `render_html`, `save_report` (PDF / HTML / CSV / JSON) |
| Завершение сеанса, закрытие доступа | `features.py` → `logout`, `SessionGuard` (автовыход через 30 минут); `main.py` → `main()` возвращает к окну входа |
| Тестирование | `tests/`: база (`test_database.py`), расчёты (`test_calculations.py`), ИИ на трёх наборах (`test_ai.py`), авторизация (`test_auth.py`), почта и отчёты (`test_mail_reports.py`) |
