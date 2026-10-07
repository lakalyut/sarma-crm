"""Run only after a successful deploy health check; never sends messages."""

import json
from pathlib import Path

from .database import SessionLocal
from .services.release_update_service import import_releases


def main():
    manifest = Path(__file__).resolve().parent.parent / "release_updates.json"
    releases = json.loads(manifest.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        added = import_releases(db, releases)
    print(f"Release drafts created: {added}")


if __name__ == "__main__":
    main()
