# «Пульс» — CRM для аналитики продаж

Внутренняя CRM для аналитики продаж кальянных табаков: импорт продаж из XLSX,
сопоставление сырых номенклатур со справочником товаров, аналитика по клиентам/городам,
ABC-рейтинг ассортимента, амбассадорские отчёты.

Подробности архитектуры и решений — [CLAUDE.md](CLAUDE.md).

## Возможности

- Авторизация пользователей (роли admin / user), самодельный auth без сторонних фреймворков
- Импорт продаж из XLSX с нечётким сопоставлением номенклатуры (rapidfuzz)
- Аналитика по клиентам, городам, регионам — таблицы, графики, гэп-анализ ABC
- ABC-рейтинг ассортимента (ручная простановка категорий)
- Амбассадорские отчёты — SKU-статусы (New/Lost/Unstable) по клиентам
- Лента событий импортов, справочник регионов (город → макро-регион)

## Стек

- FastAPI, SQLAlchemy, Alembic
- Jinja2 + ванильный CSS/JS, без фронтенд-сборки
- Pandas + rapidfuzz (импорт и сопоставление номенклатуры)
- SQLite (dev) / Postgres (prod)
- Docker Compose (prod: db/web/nginx/certbot)

## Запуск локально (Windows/venv)

```powershell
python -m venv venv
venv\Scripts\pip.exe install -r requirements.txt

copy .env.example .env
# отредактировать .env — задать ADMIN_EMAIL/ADMIN_PASSWORD

venv\Scripts\alembic.exe upgrade head
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

Приложение поднимется на `http://localhost:8001`. Логин — email/пароль из `.env`
(`ensure_admin()` при старте создаёт или чинит этого пользователя автоматически).

Тесты, форматирование, линт — см. раздел Commands в [CLAUDE.md](CLAUDE.md).

## Прод

Postgres + Docker Compose (`docker-compose.yml`). Деплой — push в `main` с зелёным CI
(GitHub Actions) автоматически триггерит выкладку на VPS по SSH. Подробности — раздел
Deploy в [CLAUDE.md](CLAUDE.md).
