/**
 * Релей для Telegram Bot API — обход блокировки исходящего HTTPS к
 * api.telegram.org с прод-VPS (см. CLAUDE.md, раздел Deploy). Пробрасывает
 * запрос как есть на api.telegram.org — у Cloudflare своя сеть, блокировка
 * конкретно этого VPS её не касается.
 *
 * Три независимых бота (sarma-crm, dziro_bot, guide_bot) упираются в одну и
 * ту же сетевую блокировку — один и тот же воркер годится для всех трёх,
 * достаточно у каждого поменять базовый URL Bot API на адрес воркера.
 *
 * ДЕПЛОЙ (дашборд Cloudflare, без wrangler):
 *   1. dash.cloudflare.com -> Workers & Pages -> Create -> Create Worker.
 *   2. Вставить этот файл целиком в редактор, Deploy.
 *   3. Settings -> Variables -> Environment Variables -> добавить
 *      секретную переменную RELAY_SECRET (encrypt) — любая случайная строка,
 *      например `openssl rand -hex 32`.
 *   4. Скопировать адрес воркера (https://<имя>.<аккаунт>.workers.dev).
 *
 * НАСТРОЙКА КАЖДОГО БОТА — прописать на сервере, где бот работает:
 *   TELEGRAM_API_BASE_URL=https://<имя>.<аккаунт>.workers.dev
 *   TELEGRAM_RELAY_SECRET=<та же строка, что RELAY_SECRET в воркере>
 * (в sarma-crm — в .env + переменные окружения сервиса web в
 * docker-compose.yml, см. CLAUDE.md про добавление новой прод-переменной;
 * для dziro_bot/guide_bot — по месту, эти проекты не в этом репозитории).
 *
 * БЕЗ RELAY_SECRET воркер открытым текстом пробрасывает ЛЮБОЙ запрос на
 * Telegram Bot API кому угодно, кто узнает адрес воркера (сам токен бота
 * лежит в пути запроса и никогда не виден воркеру отдельно — но воркер не
 * должен становиться бесплатным анонимным прокси для чужих токенов тоже).
 * Секрет обязателен для боевого использования.
 */

const TELEGRAM_ORIGIN = "https://api.telegram.org";

export default {
  async fetch(request, env) {
    if (env.RELAY_SECRET) {
      const provided = request.headers.get("X-Relay-Secret");
      if (provided !== env.RELAY_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
    }

    const url = new URL(request.url);
    const target = TELEGRAM_ORIGIN + url.pathname + url.search;

    const forwardedHeaders = new Headers(request.headers);
    forwardedHeaders.delete("x-relay-secret");
    forwardedHeaders.delete("host");

    const init = {
      method: request.method,
      headers: forwardedHeaders,
      // Буферизуем целиком, не пробрасываем как ReadableStream — тела тут
      // маленькие (JSON-пейлоады sendMessage и т.п.), а буферизация проще и
      // надёжнее потоковой передачи между разными версиями fetch в Workers.
      body: ["GET", "HEAD"].includes(request.method)
        ? undefined
        : await request.arrayBuffer(),
    };

    return fetch(target, init);
  },
};
