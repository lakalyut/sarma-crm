# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

«Пульс» — внутренняя CRM для аналитики продаж (кальянные табаки): импорт продаж из XLSX,
сопоставление сырых номенклатур со справочником товаров, аналитика по клиентам/городам,
ABC-рейтинг ассортимента, амбассадорские отчёты. Русскоязычный интерфейс и код (докстринги,
переменные в шаблонах, коммиты — на русском).

Живой план работ — [ROADMAP.md](ROADMAP.md). **Файл намеренно не в git**
(исключён через `.git/info/exclude` — локальный, невersioned exclude-файл конкретной
рабочей копии, не `.gitignore`). При клонировании репо на другой машине ROADMAP.md
не появится сам — его нужно перенести отдельно (скопировать вручную/через
облако) и на новой машине тоже добавить в `.git/info/exclude`, если он должен
остаться вне истории.

## Commands

Windows/venv (как настроено в этом репозитории — `venv/` в корне):

```powershell
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001   # dev-сервер
venv\Scripts\pytest.exe -q                                              # тесты
venv\Scripts\black.exe .                                                # форматирование
venv\Scripts\ruff.exe check . --fix                                     # линт с автофиксом
venv\Scripts\alembic.exe upgrade head                                   # применить миграции
venv\Scripts\alembic.exe revision --autogenerate -m "описание"          # новая миграция
```

Кроссплатформенные шорткаты — `make fmt` / `make lint` / `make test` (см. [Makefile](Makefile)).

Один тест: `pytest tests/test_smoke.py::test_root_redirect -q`.

`.claude/launch.json` поднимает dev-сервер на порту **8001** (не 8000 — тот занят под
docker-compose/prod-контейнер), через Browser-preview инструмент (`preview_start` с
`name: "sarma-web"`), а не через Bash напрямую.

**`--reload` не всегда подхватывает правки `.py`-файлов в этом окружении** —
поймано многократно: меняешь `app/services/*.py` или `app/routes/*.py`, а
сервер продолжает отвечать по старому коду (в логах ни одного "Reloading").
Шаблоны (`.html`, Jinja auto-reload) и статика (`.css`/`.js`, читаются с диска
на каждый запрос) подхватываются нормально — проблема именно с Python-модулями.
После правки `.py`-файла — `preview_stop` + `preview_start` заново, не
надеяться на `--reload`.

## Local setup

- Реальная БД разработки — SQLite (`main.db` в корне, в `.gitignore`), схема накатывается
  через alembic (`alembic upgrade head`), а не автосозданием. Автосоздание через
  `Base.metadata.create_all()` есть в [app/main.py](app/main.py), но включается только
  флагом `AUTO_CREATE_SCHEMA=1` — по умолчанию выключено, используется только миграция.
- `.env` (в `.gitignore`, шаблон — `.env.example`) содержит `ADMIN_EMAIL`/`ADMIN_PASSWORD` —
  при старте приложения [app/startup.py](app/startup.py) `ensure_admin()` гарантирует, что
  такой admin-пользователь существует и активен (создаёт или чинит роль/пароль/статус).
- Прод — Postgres + Docker Compose (`docker-compose.yml`: db/web/nginx/certbot),
  `docker-compose.dev.yml` — Postgres в докере + приложение с `--reload` на 8000.

## Architecture

**Роуты — тонкие, бизнес-логика — в `app/services/`.** Каждый файл в
[app/routes/](app/routes/) — один `APIRouter` на раздел (`analytics`, `products`, `imports`,
`admin_users`, `admin_abc`, `admin_imports`, `ambassadors`, `misc`), подключается в
[app/main.py](app/main.py). Роуты парсят query/form-параметры, зовут функцию из
`app/services/*_service.py` (SQLAlchemy-запросы и агрегация), рендерят шаблон.

**Рендеринг страниц идёт через [app/render.py](app/render.py)** — хелпер `render(request,
template, ctx)`, который сам достаёт `current_user` по cookie-сессии и кладёт его в контекст
шаблона. Все роуты импортируют именно его (`from ..render import render`). **В
[app/main.py](app/main.py) есть собственная копия функции `render()` — она не используется
нигде** (обработчики ошибок 401/403/404/500 в main.py дергают `templates.TemplateResponse`
напрямую); не путать эти две функции при правке рендеринга.

**Auth — самодельная, без сторонних auth-фреймворков**: `session_id` в httponly-cookie →
строка в таблице `sessions` ([app/auth_models.py](app/auth_models.py)) с TTL 14 дней.
[app/auth_deps.py](app/auth_deps.py) даёт FastAPI-зависимости `get_current_user` /
`require_user` / `require_admin`. Пароли — `passlib[bcrypt]` (roadmap планирует убрать passlib
в пользу прямого bcrypt). Установка пароля новому пользователю — одноразовый токен
(`PasswordToken`, SHA-256 хэш токена в БД), ссылку админ копирует вручную со страницы
пользователей — SMTP-отправки нет.

**Импорт и сопоставление номенклатуры** — сердце домена:
[app/product_parser.py](app/product_parser.py) нормализует строки (нижний регистр, ё→е, чистка
скобок/спецсимволов) и матчит сырое название продажи (`raw_name` из XLSX) на товар из
справочника (`Product`) через `rapidfuzz.fuzz.WRatio` с порогом score **70**. Пайплайн:
[app/routes/imports.py](app/routes/imports.py) `POST /import-xlsx` читает XLSX через pandas,
требует колонки `Месяц/Тип/Клиент/Номенклатура/SKU/Количество/Вес`, для каждой строки зовёт
`match_product_by_flavor()`; при совпадении проставляет `product_id/sku/name/matched=True`,
иначе `matched=False` — такие строки видны на `/admin/unmatched`
([app/routes/analytics.py](app/routes/analytics.py)) и **пока не редактируются на месте**
(это горизонт 1 роадмапа — сейчас read-only список сырых строк).

**Данные продаж — плоская таблица `Sale`** ([app/models.py](app/models.py)): город, месяц
(строка `YYYY-MM-01`, форматируется фильтром Jinja `format_month` в «Март 2026»), тип точки,
клиент, сырые и сопоставленные название/SKU, qty/weight, `matched`. Почти вся аналитика —
это `GROUP BY` по `Sale` с общим набором SQLAlchemy-фильтров из
[app/services/sale_filters.py](app/services/sale_filters.py) (`build_sale_filters`), который
собирают роуты `analytics.py`/`ambassadors.py`/`admin_abc.py` по параметрам `city`/`months`/
`sale_types`/`client`/`matched`. Есть и списочные варианты `cities`/`clients` (в дополнение
к одиночным `city`/`client`, не вместо) — под дашборд, который умеет фильтровать сразу по
нескольким регионам/клиентам.

**ABC-рейтинг** — не автоматический: категория (A/B/C) проставляется вручную per-товар
per-сегмент через `/admin/abc` в таблицу `product_abc_ratings`; сегменты (`AbcSegment`,
напр. HoReCa/Розница) создаются там же. Автоматический расчёт по правилу 80/15/5 — в
горизонте 3 роадмапа, ещё не сделан.

**Дашборд** (`/dashboard`, [app/routes/dashboard.py](app/routes/dashboard.py) +
[app/services/dashboard_service.py](app/services/dashboard_service.py)) — кастомный
конструктор виджетов, доступен всем ролям (`require_user`). Несколько именованных
дашбордов на пользователя (`Dashboard`/`DashboardWidget` в `app/models.py`), каждый —
свой набор регионов/клиентов/периода/режима сравнения (`aggregate` — суммарно,
`split` — по регионам отдельно) и виджетов (`metric_card` / `chart`). `METRIC_CATALOG`
в `dashboard_service.py` — единственное место, где перечислены доступные метрики;
расчёт переиспользует `clients_service`/`charts_service`, новой SQL-агрегации под
дашборд не заводили. Раскладка — GridStack.js (CDN), drag/resize, позиции шлются на
`POST /dashboard/{id}/layout`. Карточки-цифры — тренд-формат (значение + дельты к
прошлому месяцу/среднему/началу периода), переиспользует `.metric-value`/
`.metric-delta-*` из `charts.css` (те же классы, что и карточки на `/analytics/charts`).
Экспорт «Скачать PDF» — **не** `window.print()`: кнопка гоняет DOM-область с
виджетами через `html2canvas` → `jsPDF` (тоже CDN) и режет канвас на срезы по
странице вручную (наивный рецепт «одна картинка на каждую страницу» раздувает файл
кратно числу страниц — проверено на практике, 20+ МБ на 2 страницы). Подробности и
что осознанно не сделано (ABC как тип виджета, per-widget фильтры) — в ROADMAP.md,
раздел «Дашборд».

**Шаблоны и статика без фронтенд-сборки** — чистый Jinja2 + ванильный CSS/JS, никакого
бандлера. [app/templates/_styles.html](app/templates/_styles.html) — единый список
`<link rel=stylesheet>`, порядок подключения в этом файле определяет каскад (важно при
конфликтах специфичности — уже ловили баг, когда `.is-hidden` из `base.css` проигрывал
`.filter-tag` из `filters.css` подключённому позже). Общий JS-паттерн поиска-с-подсказками
(`search-dropdown`) и чекбокс-мультиселекта — переиспользуется по шаблонам через инлайновые
`<script>`-блоки, не вынесен в отдельные переиспользуемые модули (кроме
[checkbox_multiselect.js](app/static/js/checkbox_multiselect.js) для одного конкретного
кейса).

**Дизайн-система**: монохром + индиго-акцент (`--primary: #6d5ef8`), токены в
[app/static/css/base.css](app/static/css/base.css). Файл `DESIGN.md`, на который ссылаются
ROADMAP.md и история коммитов («переход на систему из DESIGN.md»), **в репозитории не
существует** (не заводился и не удалялся — просто не создан) — источник истины по факту
сейчас это `base.css` + коммиты `R: шаг N редизайна` в `git log`. Полный визуальный QA-проход
и полировка (единый вид `<select>`/поиска в строках фильтров, устранение хардкод-hex,
вынос повторяющихся инлайн-стилей в классы) сделаны — см. горизонт 2.5 в ROADMAP.md.

## Deploy

`main` → GitHub Actions CI ([.github/workflows/ci.yml](.github/workflows/ci.yml): ruff + black
--check + pytest на sqlite) → при зелёном CI автоматически триггерится
[deploy.yml](.github/workflows/deploy.yml) по SSH на VPS: git reset --hard на прод-ветку,
бэкап Postgres в `/home/ubuntu/sarma_backups` (хранится 14 дней), `alembic upgrade head` внутри
контейнера, `docker compose up -d --build`. Ручного деплоя нет — пуш в `main` с прошедшим CI
достаточен.

Локальный `main` часто уходит вперёд `origin/main` на несколько коммитов, пока идёт сессия
работы — не забывать `git push`, если требуется деплой или продолжение с другой машины.
