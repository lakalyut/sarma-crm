# CRM для аналитики продаж

CRM-система для анализа продаж.

## Возможности

- Авторизация пользователей
- Роли: admin / user
- Управление пользователями
- Справочник продуктов
- Импорт продаж из XLSX
- Аналитика клиентов
- Графики
- Система сопоставления SKU

## Стек

- FastAPI
- SQLAlchemy
- Jinja2
- Pandas
- SQLite (dev) / Postgres (prod)
- Docker

## Запуск локально

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload