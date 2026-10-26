"""Import and queue the recovery announcement exactly once after healthy deployment."""

import json
from pathlib import Path

from .database import SessionLocal
from .models import ReleaseUpdate
from .services.release_update_service import import_releases, queue_update

KEY = "pulse-restored-2026-10-26"


def main() -> None:
    manifest = Path(__file__).resolve().parent.parent / "release_updates.json"
    releases = json.loads(manifest.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        import_releases(db, releases)
        update = db.query(ReleaseUpdate).filter_by(release_key=KEY).one()
        if update.status == "draft":
            queue_update(db, update.id)
            print(f"Pulse recovery announcement queued: id={update.id}")
        else:
            print(
                f"Pulse recovery announcement already {update.status}: id={update.id}"
            )


if __name__ == "__main__":
    main()
