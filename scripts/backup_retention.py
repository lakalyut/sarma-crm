"""Keep recent deploy backups and one daily copy; dry-run unless --apply."""

import argparse
import gzip
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKUP_NAME = re.compile(r"backup_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.sql\.gz\Z")


@dataclass(frozen=True)
class Backup:
    path: Path
    modified: datetime
    fingerprint: tuple
    size: int


def fingerprint(path):
    stat = path.lstat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode


def plan(directory: Path, now: datetime):
    backups = []
    for path in directory.iterdir():
        match = BACKUP_NAME.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            continue
        try:
            datetime.strptime(match[1], "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            continue
        stat = path.stat()
        backups.append(
            Backup(
                path,
                datetime.fromtimestamp(stat.st_mtime, UTC),
                fingerprint(path),
                stat.st_size,
            )
        )
    backups.sort(key=lambda backup: (backup.modified, backup.path.name), reverse=True)
    keep = set()
    verify = set()
    if backups:
        keep.add(backups[0])
        verify.add(backups[0])
    days = set()
    for backup in backups:
        if backup.modified >= now - timedelta(hours=48):
            keep.add(backup)
        if (
            backup.modified >= now - timedelta(days=14)
            and backup.modified.date() not in days
        ):
            keep.add(backup)
            verify.add(backup)
            days.add(backup.modified.date())
    return backups, keep, verify


def validate(backup):
    with gzip.open(backup.path, "rb") as source:
        if not source.read(1024 * 1024):
            raise ValueError(f"Empty backup: {backup.path.name}")
        while source.read(1024 * 1024):
            pass


def retain(directory: Path, *, apply=False, now=None):
    now = now or datetime.now(UTC)
    backups, keep, verify = plan(directory, now)
    delete = [backup for backup in backups if backup not in keep]
    if apply and delete:
        # Validate the latest and daily restore points before deleting any copy.
        for backup in verify:
            validate(backup)
        for backup in backups:
            if fingerprint(backup.path) != backup.fingerprint:
                raise RuntimeError("Backup directory changed; cleanup aborted")
        for backup in delete:
            if fingerprint(backup.path) != backup.fingerprint:
                raise RuntimeError("Backup changed during cleanup; stopping")
            backup.path.unlink()
    return {
        "applied": apply,
        "keep": [backup.path.name for backup in backups if backup in keep],
        "delete": [backup.path.name for backup in delete],
        "delete_bytes": sum(backup.size for backup in delete),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(retain(args.directory, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
