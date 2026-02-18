"""One-time migration script to import existing JSON files into Firestore.

Usage:
    uv run python scripts/migrate_to_firestore.py [--server-id SERVER_ID]

This script reads the local JSON state files and writes them to Firestore.
It is idempotent — safe to run multiple times (overwrites Firestore docs).

Requires:
    - google-cloud-firestore
    - Application Default Credentials configured (e.g., running on GCP VM
      or having GOOGLE_APPLICATION_CREDENTIALS set)
"""

import argparse
import asyncio
import json
import logging
import os
import sys

from google.cloud.firestore_v1 import AsyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default paths relative to project root
DATA_DIR = "data"
STATE_FILES = {
    "pending": "pending.json",
    "jobs": "jobs.json",
    "history": "history.json",
    "calendar": "calendar_events.json",
}
VRCHAT_SESSION_FILE = "vrchat_session.json"


def load_json(filepath):
    """Load a JSON file, return None if it doesn't exist."""
    if not os.path.exists(filepath):
        logger.warning(f"File not found, skipping: {filepath}")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


async def migrate(server_id: str):
    db = AsyncClient()

    # Migrate per-server state files
    for key, filename in STATE_FILES.items():
        filepath = os.path.join(DATA_DIR, filename)
        data = load_json(filepath)
        if data is None:
            continue

        doc_ref = (
            db.collection("servers")
            .document(server_id)
            .collection("state")
            .document(key)
        )
        await doc_ref.set({"data": data})
        logger.info(f"Migrated {filepath} -> servers/{server_id}/state/{key}")

    # Migrate VRChat session (shared, not per-server)
    session_data = load_json(VRCHAT_SESSION_FILE)
    if session_data is not None:
        doc_ref = db.collection("shared").document("vrchat_session")
        await doc_ref.set(session_data)
        logger.info(f"Migrated {VRCHAT_SESSION_FILE} -> shared/vrchat_session")

    logger.info("Migration complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate local JSON state files to Firestore"
    )
    parser.add_argument(
        "--server-id",
        default="default",
        help='Server ID in Firestore (default: "default")',
    )
    args = parser.parse_args()

    logger.info(f"Starting migration with server_id={args.server_id}")
    asyncio.run(migrate(args.server_id))


if __name__ == "__main__":
    main()
