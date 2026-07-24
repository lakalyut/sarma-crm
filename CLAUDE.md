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
`admin_users`, `admin_abc`, `admin_imports`, `client_analysis`, `misc`), подключается в
[app/main.py](app/main.py). Роуты парсят query/form-параметры, зовут функцию из
`app/services/*_service.py` (SQLAlchemy-запросы и агрегация), рендерят шаблон.
`routes/ambassadors.py` (раздел «Амбассадорские отчёты») удалён — механика (SKU-статусы
по многим клиентам) сейчас частью `client_analysis.py`, см. ниже.

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
собирают `routes/analytics.py` и `services/client_analysis_service.py`/`dashboard_service.py`
по параметрам `city`/`months`/`sale_types`/`client`/`matched`. Есть и списочные варианты
`cities`/`clients` (в дополнение к одиночным `city`/`client`, не вместо) — под дашборд и
«Анализ по клиентам», которые умеют фильтровать сразу по нескольким регионам/клиентам.

**ABC-рейтинг** — не автоматический: категория (A/B/C) проставляется вручную per-товар
per-сегмент через `/admin/abc` в таблицу `product_abc_ratings`; сегменты (`AbcSegment`,
напр. HoReCa/Розница) создаются там же. Автоматический расчёт по правилу 80/15/5 — в
горизонте 3 роадмапа, ещё не сделан.

**Детализация по клиенту** (`/analytics/client`, роут в
[app/routes/analytics.py](app/routes/analytics.py), шаблон
[client_detail.html](app/templates/analytics/client_detail.html)) — вся клиентская
аналитика для одного клиента/города/типа точки в сворачиваемых карточках (`.amb-card`/
`.amb-toggle`, тот же паттерн, что и на «Анализе по клиентам» ниже): динамика по месяцам,
SKU-статусы (New/Lost/Unstable — `build_client_sku_status()` в
[app/services/ambassadors_service.py](app/services/ambassadors_service.py), с фильтром по
`sale_type` страницы и колонкой ABC из `rating_by_product`, сортировка по клику на месяц/
Итого), «Ассортимент по ABC» (гэп-анализ, `abc_service.get_client_abc_overview`), сводные
карточки, график (Chart.js, чекбоксы-метрики Количество/Вес/Уникальные SKU). Настройки
порогов SKU-статусов (`new_client_months`/`lost_months`/`unstable_gap_months`) — через
`get_int_param()` в [app/utils/params.py](app/utils/params.py).

**«Анализ по клиентам»** (`/analytics/client-analysis`,
[app/routes/client_analysis.py](app/routes/client_analysis.py) +
[app/services/client_analysis_service.py](app/services/client_analysis_service.py)) — две
вкладки на одной странице, переключение обычной GET-навигацией (`?tab=summary`/
`?tab=ambassadors`): сервер каждый раз считает и рендерит **только** активную вкладку
(вторая ветка Jinja не выполняется), поэтому одноимённые JS-хелперы вроде `initTagSearch`
в шаблонах вкладок не конфликтуют друг с другом.
- «Свод» — иерархия тип точки → клиент → номенклатура с ленивой подгрузкой
  (`/api/client-analysis/{clients,nomenclature,missing}`), первый тип по весу — развёрнут
  сразу. Метрика переключается вкладкой (Вес/Количество/Уникальных SKU) мгновенно на
  клиенте — каждая lazy-строка везёт сразу все метрики, повторного запроса на клик нет.
  ABC-сегмент — **свой на каждый тип точки** (не общий на всю страницу — наименования
  типов разнятся по регионам), дефолт через `abc_service.guess_default_segment()`, бейджи
  считает `get_abc_badges_for_clients()` (2 запроса на весь список клиентов типа, без
  N+1). «Чего не хватает» — `get_client_abc_overview()` как есть.
- «Амбассадорский отчёт» — SKU-статусы по нескольким клиентам сразу, **без** разбивки по
  типу точки (историческое поведение, восстановлено дословно из git-истории вместе с
  `build_ambassadors_report()`, а не по памяти) — отдельная от «Свода» механика, живёт
  в шаблоне-партиале [_client_analysis_ambassadors.html](app/templates/analytics/_client_analysis_ambassadors.html).

На странице «Клиенты» ([clients_summary.html](app/templates/analytics/clients_summary.html))
чекбоксы в таблице → всплывающая панель «Сформировать свод»/«Амбассадорский отчёт» →
редирект на `/analytics/client-analysis` с готовым списком клиентов (город/период
переносятся тоже). Данные для JS всегда через `data-*`-атрибуты, не сырым `{{ ... |tojson }}`
внутри `<script>` — автоэкранирование Jinja портит кавычки в JSON (`"` → `&#34;`), ловили
живьём на этой самой панели.

**Дашборд** (`/dashboard`, [app/routes/dashboard.py](app/routes/dashboard.py) +
[app/services/dashboard_service.py](app/services/dashboard_service.py)) —
фиксированная страница «Аналитика по регионам», доступна всем ролям
(`require_user`). Пришла на смену кастомному конструктору виджетов (несколько
именованных дашбордов, GridStack, PDF-экспорт через html2canvas/jsPDF — полностью
убраны вместе с моделями `Dashboard`/`DashboardWidget`, миграция `7a1f2c9d5b3e`;
история решений по конструктору — в ROADMAP.md, раздел «Дашборд», помечен как
исторический). Фильтры — регионы (тег-поиск) и период; свод считает одна функция
`get_regions_overview()` — сетка город×месяц по всем 6 метрикам `METRIC_CATALOG`
(Вес/Количество/Клиенты/Всего SKU/Уникальных SKU/SKU на клиента) плюс итоги по
городу (весь период), по месяцу (все выбранные города) и общий итог. Итоги **не**
суммируются из готовой (город, месяц)-сетки — `unique_clients`/`unique_sku`
пересчитываются отдельным запросом на нужной группировке, иначе клиент/SKU,
повторившийся в нескольких месяцах, задвоился бы. Данные на весь период (все
метрики, все города/месяцы) отдаются странице одним GET-запросом и кладутся в
`data-regions` атрибут (`|tojson`, не сырым в `<script>` — см. предупреждение про
Jinja-автоэкранирование выше); переключение вкладки метрики и вида графика
(«Общий график» с городами-линиями / «По регионам отдельно» — мини-графики на
город) дальше работает чисто на клиенте, без повторных походов на сервер — та же
идея, что и в мгновенном переключении метрики на «Анализе по клиентам».

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
