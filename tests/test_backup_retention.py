import gzip
import os
from datetime import UTC, datetime, timedelta

import pytest

from scripts.backup_retention import retain

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def backup(directory, age, *, payload=b"-- SQL dump\n", corrupt=False):
    moment = NOW - age
    path = directory / ("backup_" + moment.strftime("%Y-%m-%d_%H-%M-%S") + ".sql.gz")
    path.write_bytes(b"broken gzip" if corrupt else gzip.compress(payload))
    os.utime(path, (moment.timestamp(), moment.timestamp()))
    return path


def test_recent_daily_and_expired_policy_with_dry_run(tmp_path):
    recent = [backup(tmp_path, timedelta(hours=hours)) for hours in (1, 12, 24, 48)]
    daily = backup(tmp_path, timedelta(days=3))
    duplicate = backup(tmp_path, timedelta(days=3, hours=1))
    boundary = backup(tmp_path, timedelta(days=14))
    expired = backup(tmp_path, timedelta(days=14, seconds=1))
    ignored = tmp_path / "backup_2026-99-99_12-00-00.sql.gz"
    ignored.write_text("unrelated")
    unfinished = tmp_path / "backup_2026-10-09_12-00-00.sql.gz.tmp"
    unfinished.write_text("in progress")
    alias = tmp_path / "backup_2026-10-01_12-00-00.sql.gz"
    alias.symlink_to(expired)
    result = retain(tmp_path, now=NOW)
    assert set(result["keep"]) == {p.name for p in recent + [daily, boundary]}
    assert set(result["delete"]) == {duplicate.name, expired.name}
    assert duplicate.exists() and expired.exists()
    assert result["delete_bytes"] == duplicate.stat().st_size + expired.stat().st_size
    retain(tmp_path, apply=True, now=NOW)
    assert not duplicate.exists() and not expired.exists()
    assert all(
        path.exists() for path in recent + [daily, boundary, ignored, unfinished]
    )
    assert alias.is_symlink()
    assert retain(tmp_path, apply=True, now=NOW)["delete"] == []


def test_newest_backup_survives_even_if_all_are_old(tmp_path):
    newest = backup(tmp_path, timedelta(days=20))
    oldest = backup(tmp_path, timedelta(days=30))
    result = retain(tmp_path, apply=True, now=NOW)
    assert result["keep"] == [newest.name]
    assert newest.exists() and not oldest.exists()


@pytest.mark.parametrize("corrupt, payload", [(True, b"dump"), (False, b"")])
def test_bad_latest_archive_prevents_any_deletion(tmp_path, corrupt, payload):
    latest = backup(tmp_path, timedelta(hours=1), corrupt=corrupt, payload=payload)
    expired = backup(tmp_path, timedelta(days=20))
    with pytest.raises((OSError, ValueError)):
        retain(tmp_path, apply=True, now=NOW)
    assert expired.exists() and latest.exists()


def test_bad_daily_archive_preserves_older_good_copy(tmp_path):
    backup(tmp_path, timedelta(hours=1))
    backup(tmp_path, timedelta(days=4), corrupt=True)
    good_copy = backup(tmp_path, timedelta(days=4, hours=1))
    with pytest.raises(OSError):
        retain(tmp_path, apply=True, now=NOW)
    assert good_copy.exists()


def test_archive_change_during_validation_aborts_cleanup(tmp_path, monkeypatch):
    import scripts.backup_retention as retention

    latest = backup(tmp_path, timedelta(hours=1))
    expired = backup(tmp_path, timedelta(days=20))
    original = retention.validate

    def change(archive):
        original(archive)
        latest.write_bytes(gzip.compress(b"new dump"))

    monkeypatch.setattr(retention, "validate", change)
    with pytest.raises(RuntimeError, match="changed"):
        retain(tmp_path, apply=True, now=NOW)
    assert expired.exists()


def test_empty_directory_is_safe(tmp_path):
    assert retain(tmp_path, apply=True, now=NOW) == {
        "applied": True,
        "keep": [],
        "delete": [],
        "delete_bytes": 0,
    }
