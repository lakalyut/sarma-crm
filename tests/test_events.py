from datetime import UTC, datetime

from app.services.event_log_service import count_unread_events, log_import


def seed_event(db_session, admin_user, city="Омск"):
    log_import(
        db_session,
        city=city,
        months=["2026-01-01"],
        rows_imported=10,
        rows_unmatched=0,
        user_id=admin_user.id,
    )


def test_unread_count_only_counts_events_after_last_seen(db_session, admin_user):
    seed_event(db_session, admin_user)
    assert count_unread_events(db_session, admin_user) == 1

    admin_user.events_last_seen_at = datetime.now(UTC)
    db_session.commit()
    assert count_unread_events(db_session, admin_user) == 0

    seed_event(db_session, admin_user, city="Москва")
    assert count_unread_events(db_session, admin_user) == 1


def test_unread_count_is_zero_for_anonymous_user(db_session, admin_user):
    seed_event(db_session, admin_user)
    assert count_unread_events(db_session, None) == 0


def test_visiting_events_page_marks_everything_seen(
    admin_client, db_session, admin_user
):
    seed_event(db_session, admin_user, city="Омск")
    seed_event(db_session, admin_user, city="Москва")

    before = admin_client.get("/admin/unmatched")
    assert 'sidebar-nav-badge">2<' in before.text

    resp = admin_client.get("/events")
    assert resp.status_code == 200

    after = admin_client.get("/admin/unmatched")
    assert "sidebar-nav-badge" not in after.text
