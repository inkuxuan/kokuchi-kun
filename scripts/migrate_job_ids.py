"""One-time migration script: update job.id from UUID to message_id in Firestore.

Previously each job had a UUID `id` distinct from the Discord message ID.
The new code uses `message_id` directly as `job_id`.

For each announcement document where `job.id != msg_id` (i.e. the old UUID format),
this script updates `job.id` to `msg_id`.

`channel_id` is a new field absent in old documents; it will load as `None`
automatically — no action needed here.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp.json \
      uv run python scripts/migrate_job_ids.py [--config config.yaml]

Safe to run multiple times — idempotent.
Run BEFORE deploying the new code.
"""

import argparse
import asyncio
import logging
import sys
import yaml

from google.cloud.firestore_v1 import AsyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_guild_configs(config: dict) -> list[dict]:
    """Return list of guild configs with IDs normalized to str."""
    guilds = config.get("discord", {}).get("guilds", [])
    for g in guilds:
        g["guild_id"] = str(g["guild_id"])
        if g.get("firestore_server_id") is not None:
            g["firestore_server_id"] = str(g["firestore_server_id"])
    return guilds


async def migrate_guild(
    db: AsyncClient,
    guild_id: str,
    server_id: str,
    servers_collection: str,
) -> int:
    """Migrate one guild. Returns number of documents updated."""
    announcements_ref = (
        db.collection(servers_collection)
        .document(server_id)
        .collection("announcements")
    )

    docs = announcements_ref.stream()
    updated = 0

    async for doc in docs:
        msg_id = doc.id
        data = doc.to_dict()
        job = data.get("job")

        if job is None:
            continue

        old_job_id = job.get("id")
        if old_job_id is None or old_job_id == msg_id:
            # Already migrated or no id field
            continue

        # Update job.id to msg_id
        job["id"] = msg_id
        await announcements_ref.document(msg_id).update({"job": job})
        logger.info(f"  Guild {guild_id}: updated job.id {old_job_id!r} -> {msg_id!r} for msg {msg_id}")
        updated += 1

    if updated == 0:
        logger.info(f"Guild {guild_id}: nothing to migrate")
    else:
        logger.info(f"Guild {guild_id}: updated {updated} document(s)")

    return updated


async def run(config_path: str):
    config = load_config(config_path)
    guilds = normalize_guild_configs(config)

    if not guilds:
        logger.error("No guilds found in config.yaml")
        sys.exit(1)

    firestore_config = config.get("firestore", {})
    servers_collection = firestore_config.get("servers_collection", "servers")
    database = firestore_config.get("database")

    db = AsyncClient(database=database) if database else AsyncClient()

    total = 0
    for guild_conf in guilds:
        guild_id = guild_conf["guild_id"]
        server_id = guild_conf.get("firestore_server_id", guild_id)
        count = await migrate_guild(
            db=db,
            guild_id=guild_id,
            server_id=server_id,
            servers_collection=servers_collection,
        )
        total += count

    logger.info(f"Migration complete: {total} document(s) updated across {len(guilds)} guild(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Firestore job.id from UUID to message_id"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
