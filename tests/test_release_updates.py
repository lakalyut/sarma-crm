import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import CSRF_TOKEN

from app.auth_models import User
from app.models import ReleaseUpdate, UpdateDelivery
from app.services import release_update_service as svc
from app.services import telegram_bot_service as bot
from app.telegram_client import TelegramSendError


@pytest.fixture
def announcement(db_session):
    update = ReleaseUpdate(
        release_key="release-test", title="Исправление", body="Два визита подряд"
    )
    db_session.add(update)
    db_session.commit()
    return update


def add_user(db, telegram_id=5550000001, **kwargs):
    data = dict(
        email=f"{telegram_id}@test.local",
        telegram_id=telegram_id,
        role="ambassador",
        is_active=True,
        first_name="Иван",
        city="Иркутск",
    )
    data.update(kwargs)
    user = User(**data)
    db.add(user)
    db.commit()
    return user


def test_import_is_idempotent_and_keeps_admin_edits(db_session):
    item = {"key": "release", "title": "Заголовок", "body": "Описание"}
    assert svc.import_releases(db_session, [item]) == 1
    update = db_session.query(ReleaseUpdate).one()
    update.body = "Текст администратора"
    db_session.commit()
    assert svc.import_releases(db_session, [item]) == 0
    assert db_session.query(ReleaseUpdate).one().body == "Текст администратора"


def test_import_validates_entire_manifest(db_session):
    with pytest.raises(ValueError):
        svc.import_releases(
            db_session,
            [
                {"key": "ok", "title": "OK", "body": "Text"},
                {"key": "bad", "title": "", "body": "Text"},
            ],
        )
    assert db_session.query(ReleaseUpdate).count() == 0


def test_release_manifest_is_valid(db_session):
    manifest = Path(__file__).resolve().parents[1] / "release_updates.json"
    releases = json.loads(manifest.read_text(encoding="utf-8"))
    assert len({item["key"] for item in releases}) == len(releases)
    assert svc.import_releases(db_session, releases) == len(releases)
    assert db_session.query(UpdateDelivery).count() == 0


def test_queue_all_users_once_and_skip_opt_out(db_session, announcement):
    first = add_user(db_session, telegram_chat_id=7770000001)
    add_user(db_session, 5550000002, role="user")
    add_user(db_session, 5550000003, updates_enabled=False)
    add_user(db_session, 5550000004, is_active=False)
    add_user(db_session, 5550000005, role="admin")
    svc.queue_update(db_session, announcement.id)
    assert svc.delivery_counts(db_session, announcement.id) == {
        "queued": 2,
        "skipped": 1,
    }
    assert (
        db_session.query(UpdateDelivery)
        .filter_by(telegram_id=first.telegram_id)
        .one()
        .chat_id
        == 7770000001
    )
    with pytest.raises(ValueError):
        svc.queue_update(db_session, announcement.id)
    db_session.rollback()
    assert db_session.query(UpdateDelivery).count() == 3


def test_audience_and_zero_recipients(db_session, announcement):
    add_user(db_session, role="user")
    announcement.audience = "ambassador"
    db_session.commit()
    svc.queue_update(db_session, announcement.id)
    db_session.refresh(announcement)
    assert announcement.status == "finished"
    assert db_session.query(UpdateDelivery).count() == 0


def test_success_retry_does_not_repeat_delivered(db_session, announcement, monkeypatch):
    add_user(db_session)
    add_user(db_session, 5550000002, role="user")
    svc.queue_update(db_session, announcement.id)
    sent = []
    monkeypatch.setattr(
        svc, "send_update_message", lambda chat, text: sent.append(chat)
    )
    svc.deliver_next(db_session)

    def blocked(*args):
        raise TelegramSendError(403)

    monkeypatch.setattr(svc, "send_update_message", blocked)
    svc.deliver_next(db_session)
    db_session.refresh(announcement)
    assert announcement.status == "finished"
    svc.retry_failed(db_session, announcement.id)
    monkeypatch.setattr(
        svc, "send_update_message", lambda chat, text: sent.append(chat)
    )
    svc.deliver_next(db_session)
    svc.deliver_next(db_session)
    assert sent == [5550000001, 5550000002]
    assert svc.delivery_counts(db_session, announcement.id) == {"sent": 2}


def test_opt_out_after_queue_prevents_send(db_session, announcement, monkeypatch):
    user = add_user(db_session)
    svc.queue_update(db_session, announcement.id)
    user.updates_enabled = False
    db_session.commit()
    monkeypatch.setattr(
        svc, "send_update_message", lambda *args: pytest.fail("must not send")
    )
    svc.deliver_next(db_session)
    assert svc.delivery_counts(db_session, announcement.id) == {"skipped": 1}


def test_rate_limit_leaves_persistent_queue(db_session, announcement, monkeypatch):
    add_user(db_session)
    svc.queue_update(db_session, announcement.id)

    def limit(*args):
        raise TelegramSendError(429, 30)

    monkeypatch.setattr(svc, "send_update_message", limit)
    assert svc.deliver_next(db_session) == 30
    assert svc.delivery_counts(db_session, announcement.id) == {"queued": 1}
    db_session.refresh(announcement)
    assert announcement.status == "sending"


def test_uncertain_network_delivery_never_retried(
    db_session, announcement, monkeypatch
):
    add_user(db_session)
    svc.queue_update(db_session, announcement.id)

    def timeout(*args):
        raise TimeoutError("secret URL must not leak")

    monkeypatch.setattr(svc, "send_update_message", timeout)
    svc.deliver_next(db_session)
    delivery = db_session.query(UpdateDelivery).one()
    assert delivery.status == "unknown"
    assert "secret" not in delivery.error
    db_session.refresh(announcement)
    with pytest.raises(ValueError):
        svc.retry_failed(db_session, announcement.id)


def test_restart_recovers_only_unsent_queue(db_session, announcement, monkeypatch):
    add_user(db_session)
    add_user(db_session, 5550000002)
    svc.queue_update(db_session, announcement.id)
    delivery = db_session.query(UpdateDelivery).order_by(UpdateDelivery.id).first()
    delivery.status = "sending"
    delivery.attempted_at = datetime.now(UTC)
    db_session.commit()
    svc.recover_interrupted(db_session)
    sent = []
    monkeypatch.setattr(
        svc, "send_update_message", lambda chat, text: sent.append(chat)
    )
    svc.deliver_next(db_session)
    assert sent == [5550000002]
    assert svc.delivery_counts(db_session, announcement.id) == {"sent": 1, "unknown": 1}


def test_admin_preview_edit_send_and_no_edits_after_send(
    admin_client, db_session, announcement, monkeypatch
):
    add_user(db_session)
    page = admin_client.get(f"/admin/updates/{announcement.id}")
    assert page.status_code == 200
    assert "Два визита подряд" in page.text
    response = admin_client.post(
        f"/admin/updates/{announcement.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "title": "Новое",
            "body": "<script>Text</script>",
            "audience": "all",
        },
    )
    assert "&lt;script&gt;" in response.text
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "1")
    admin_client.post(
        f"/admin/updates/{announcement.id}/send", data={"csrf_token": CSRF_TOKEN}
    )
    assert db_session.query(UpdateDelivery).count() == 1
    admin_client.post(
        f"/admin/updates/{announcement.id}/send", data={"csrf_token": CSRF_TOKEN}
    )
    assert db_session.query(UpdateDelivery).count() == 1
    admin_client.post(
        f"/admin/updates/{announcement.id}/edit",
        data={"csrf_token": CSRF_TOKEN, "title": "Changed", "body": "Body"},
    )
    db_session.refresh(announcement)
    assert announcement.title == "Новое"


def test_admin_csrf_and_access(client, admin_client, announcement):
    assert (
        admin_client.post(f"/admin/updates/{announcement.id}/send").status_code == 403
    )
    client.cookies.clear()
    assert client.get("/admin/updates", follow_redirects=False).status_code == 302


def test_regular_user_cannot_access_or_send(
    admin_client, admin_user, db_session, announcement
):
    admin_user.role = "user"
    db_session.commit()
    assert admin_client.get("/admin/updates").status_code == 403
    assert (
        admin_client.post(
            f"/admin/updates/{announcement.id}/send", data={"csrf_token": CSRF_TOKEN}
        ).status_code
        == 403
    )
    assert db_session.query(UpdateDelivery).count() == 0


def test_send_without_running_bot_does_not_queue(
    admin_client, db_session, announcement, monkeypatch
):
    monkeypatch.delenv("TELEGRAM_POLLING_ENABLED", raising=False)
    response = admin_client.post(
        f"/admin/updates/{announcement.id}/send", data={"csrf_token": CSRF_TOKEN}
    )
    assert "Telegram-бот не запущен" in response.text
    assert db_session.query(UpdateDelivery).count() == 0
    db_session.refresh(announcement)
    assert announcement.status == "draft"


def test_bot_settings_work_before_registration_and_city_callback(
    db_session, monkeypatch
):
    user = add_user(db_session, first_name=None, city=None)
    sent = []
    monkeypatch.setattr(
        bot, "send_message", lambda *args, **kwargs: sent.append((args, kwargs))
    )
    monkeypatch.setattr(bot, "answer_callback_query", lambda *args, **kwargs: None)
    bot.handle_update(
        db_session,
        {
            "message": {
                "from": {"id": user.telegram_id},
                "chat": {"id": user.telegram_id, "type": "private"},
                "text": "/updates",
            }
        },
        "https://test",
    )
    assert sent[-1][1]["reply_markup"]["inline_keyboard"]
    assert user.first_name is None
    for value in ("off", "on"):
        bot.handle_update(
            db_session,
            {
                "callback_query": {
                    "id": value,
                    "from": {"id": user.telegram_id},
                    "message": {"chat": {"id": user.telegram_id}},
                    "data": f"updates:{value}",
                }
            },
            "https://test",
        )
        db_session.refresh(user)
        assert user.updates_enabled is (value == "on")


def test_disabled_user_cannot_use_settings(db_session, monkeypatch):
    user = add_user(db_session, is_active=False)
    sent = []
    monkeypatch.setattr(bot, "send_message", lambda *args, **kwargs: sent.append(args))
    bot.handle_update(
        db_session,
        {
            "message": {
                "from": {"id": user.telegram_id},
                "chat": {"id": user.telegram_id},
                "text": "/updates",
            }
        },
        "https://test",
    )
    assert sent == [(user.telegram_id, bot.DENY_TEXT)]
