import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

BASE_URL = "https://pulse.test"


def _signed_init_data(telegram_id: int, first_name: str = "Тест") -> str:
    token = os.environ["TELEGRAM_TOKEN"]
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": first_name}, ensure_ascii=False
        ),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


def test_unknown_telegram_id_is_denied(db_session, monkeypatch):
    from app.services import telegram_bot_service as svc

    sent = []
    monkeypatch.setattr(svc, "send_message", lambda *a, **k: sent.append((a, k)))

    svc.handle_update(
        db_session,
        {"message": {"from": {"id": 999}, "chat": {"id": 999}, "text": "/start"}},
        BASE_URL,
    )

    assert len(sent) == 1
    assert sent[0][0][1] == svc.DENY_TEXT


def test_text_message_saves_name_and_asks_region(db_session, monkeypatch):
    from app.auth_models import User
    from app.services import telegram_bot_service as svc

    user = User(
        email="amb@example.com", role="ambassador", is_active=True, telegram_id=12345
    )
    db_session.add(user)
    db_session.commit()

    sent = []
    monkeypatch.setattr(svc, "send_message", lambda *a, **k: sent.append((a, k)))

    svc.handle_update(
        db_session,
        {
            "message": {
                "from": {"id": 12345},
                "chat": {"id": 555},
                "text": "Иван Иванов",
            }
        },
        BASE_URL,
    )

    db_session.refresh(user)
    assert user.first_name == "Иван"
    assert user.last_name == "Иванов"
    assert user.region_id is None
    assert len(sent) == 1
    assert "reply_markup" in sent[0][1]


def test_region_callback_saves_region(db_session, monkeypatch):
    from app.auth_models import User
    from app.models import Region
    from app.services import telegram_bot_service as svc

    region = Region(name="Москва", sort_order=0)
    db_session.add(region)
    user = User(
        email="amb2@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=54321,
        first_name="Пётр",
        last_name="",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(region)

    answered = []
    sent = []
    menu = []
    monkeypatch.setattr(
        svc, "answer_callback_query", lambda *a, **k: answered.append((a, k))
    )
    monkeypatch.setattr(svc, "send_message", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(
        svc, "set_chat_menu_button", lambda *a, **k: menu.append((a, k))
    )

    svc.handle_update(
        db_session,
        {
            "callback_query": {
                "id": "cbq1",
                "from": {"id": 54321},
                "message": {"chat": {"id": 777}},
                "data": f"region:{region.id}",
            }
        },
        BASE_URL,
    )

    db_session.refresh(user)
    assert user.region_id == region.id
    assert len(answered) == 1
    assert len(sent) == 1
    assert len(menu) == 1

    # повторный тап тем же callback — не должен ничего менять
    svc.handle_update(
        db_session,
        {
            "callback_query": {
                "id": "cbq2",
                "from": {"id": 54321},
                "message": {"chat": {"id": 777}},
                "data": f"region:{region.id}",
            }
        },
        BASE_URL,
    )
    db_session.refresh(user)
    assert user.region_id == region.id
    assert len(answered) == 2
    assert len(sent) == 1  # не выросло


def test_webhook_rejects_bad_secret(client):
    resp = client.post("/telegram/webhook", json={})
    assert resp.status_code == 403


def test_webhook_accepts_correct_secret(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    resp = client.post(
        "/telegram/webhook",
        json={"message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "/start"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_ambassador_app_verify_requires_completed_registration(db_session, client):
    from app.auth_models import User

    user = User(
        email="amb3@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=777888,
    )
    db_session.add(user)
    db_session.commit()

    init_data = _signed_init_data(777888)
    resp = client.post(
        "/ambassador/app/verify", headers={"Authorization": f"tma {init_data}"}
    )
    assert resp.status_code == 403


def test_ambassador_app_verify_ok(db_session, client):
    from app.auth_models import User
    from app.models import Region

    region = Region(name="Юг", sort_order=0)
    db_session.add(region)
    db_session.commit()
    db_session.refresh(region)

    user = User(
        email="amb4@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=222333,
        first_name="Анна",
        last_name="Смирнова",
        region_id=region.id,
    )
    db_session.add(user)
    db_session.commit()

    init_data = _signed_init_data(222333)
    resp = client.post(
        "/ambassador/app/verify", headers={"Authorization": f"tma {init_data}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == "Анна"
    assert body["region"] == "Юг"
