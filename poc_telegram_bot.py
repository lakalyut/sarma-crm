"""Горизонт 13, Этап 0 — одноразовый скрипт тестового бота для PoC.

НЕ часть приложения (не в app/), не деплоится, не часть прод-инфраструктуры.
Прямые HTTP-вызовы к Telegram Bot API (long polling), без aiogram — тут всего
одна команда, полноценный Dispatcher избыточен (см. ROADMAP.md, горизонт 13,
раздел "Инфраструктура и нагрузка").

Запуск:  venv/bin/python poc_telegram_bot.py <публичный-https-url-до-/poc/telegram>
Например: venv/bin/python poc_telegram_bot.py https://abc123.trycloudflare.com/poc/telegram

Отвечает на /start инлайн-кнопкой с web_app — открывает мини-апп PoC.
Ctrl+C — остановить.
"""

import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"


def main():
    if len(sys.argv) < 2:
        print("Использование: python poc_telegram_bot.py <https-url-до-/poc/telegram>")
        sys.exit(1)

    webapp_url = sys.argv[1]
    print(f"Бот запущен. WebApp URL: {webapp_url}")
    print("Открой бота в Telegram и нажми /start. Ctrl+C — остановить.")

    offset = 0
    with httpx.Client(timeout=35) as client:
        while True:
            try:
                resp = client.get(
                    f"{API}/getUpdates", params={"offset": offset, "timeout": 30}
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])
            except httpx.HTTPError as exc:
                print(f"Ошибка опроса Telegram: {exc}")
                time.sleep(2)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if not message:
                    continue

                text = message.get("text", "")
                chat_id = message["chat"]["id"]
                from_user = message.get("from", {})
                print(
                    f"← /{text} от {from_user.get('first_name')} (id={from_user.get('id')})"
                )

                if text == "/start":
                    client.post(
                        f"{API}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "PoC: нажми кнопку, чтобы открыть мини-апп.",
                            "reply_markup": {
                                "inline_keyboard": [
                                    [
                                        {
                                            "text": "Открыть PoC",
                                            "web_app": {"url": webapp_url},
                                        }
                                    ]
                                ]
                            },
                        },
                    )


if __name__ == "__main__":
    main()
