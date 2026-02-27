"""One-time migration script: convert old flat-list Firestore state to per-announcement documents.

Old format (per guild):
  servers/{server_id}/state/pending   -> {data: {msg_id: bot_reply_id, ...}}
  servers/{server_id}/state/history   -> {data: [msg_id, ...]}
  servers/{server_id}/state/calendar  -> {data: {msg_id: calendar_event_id, ...}}
  servers/{server_id}/state/jobs      -> {data: [{id, message_id, ...}, ...]}

New format (per guild):
  servers/{server_id}/announcements/{msg_id}:
    guild_id:          str
    bot_reply_id:      str | null
    calendar_event_id: str | null
    completed:         bool
    job:               dict | null

Usage:
    uv run python scripts/migrate_firestore.py [--config config.yaml]

Safe to run multiple times — overwrites existing announcement documents.
Run this BEFORE deploying the new bot code.
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


def pick_best_job(jobs: list[dict]) -> dict | None:
    """If multiple jobs exist for the same message_id, pick the most relevant one.

    Priority for terminal jobs: success > failed > cancelled > missed.
    Non-terminal (pending) jobs take precedence over any terminal job.
    """
    if not jobs:
        return None
    if len(jobs) == 1:
        return jobs[0]

    priority = {"pending": 0, "missed": 1, "success": 2, "failed": 3, "cancelled": 4}
    return min(jobs, key=lambda j: priority.get(j.get("status", "pending"), 99))


async def migrate_guild(
    db: AsyncClient,
    guild_id: str,
    server_id: str,
    servers_collection: str,
    state_subcollection: str,
) -> int:
    """Migrate one guild. Returns number of announcement documents written."""

    async def load_state_doc(key: str, default):
        doc_ref = (
            db.collection(servers_collection)
            .document(server_id)
            .collection(state_subcollection)
            .document(key)
        )
        doc = await doc_ref.get()
        if doc.exists:
            return doc.to_dict().get("data", default)
        return default

    pending: dict = await load_state_doc("pending", {})
    history: list = await load_state_doc("history", [])
    calendar: dict = await load_state_doc("calendar", {})
    jobs_list: list = await load_state_doc("jobs", [])

    logger.info(
        f"Guild {guild_id} (server_id={server_id}): "
        f"{len(pending)} pending, {len(history)} history, "
        f"{len(calendar)} calendar, {len(jobs_list)} jobs"
    )

    if not pending and not jobs_list:
        logger.info(f"Guild {guild_id}: nothing to migrate, skipping")
        return 0

    # Group jobs by message_id
    jobs_by_msg: dict[str, list[dict]] = {}
    for job in jobs_list:
        msg_id = job.get("message_id")
        if msg_id:
            jobs_by_msg.setdefault(msg_id, []).append(job)

    # Collect all known msg_ids (include history-only entries so they survive migration)
    all_msg_ids = set(pending.keys()) | set(jobs_by_msg.keys()) | set(history)

    history_set = set(history)

    announcements_ref = (
        db.collection(servers_collection)
        .document(server_id)
        .collection("announcements")
    )

    count = 0
    for msg_id in all_msg_ids:
        job = pick_best_job(jobs_by_msg.get(msg_id, []))
        doc = {
            "guild_id": guild_id,
            "bot_reply_id": pending.get(msg_id),
            "calendar_event_id": calendar.get(msg_id),
            "completed": msg_id in history_set or (job is not None and job.get("status") == "success"),
            "job": job,
        }
        await announcements_ref.document(msg_id).set(doc)
        count += 1
        logger.debug(f"  Wrote announcement {msg_id}: completed={doc['completed']}, job_status={job and job.get('status')}")

    logger.info(f"Guild {guild_id}: wrote {count} announcement documents")
    return count


async def run(config_path: str):
    config = load_config(config_path)
    guilds = normalize_guild_configs(config)

    if not guilds:
        logger.error("No guilds found in config.yaml")
        sys.exit(1)

    firestore_config = config.get("firestore", {})
    servers_collection = firestore_config.get("servers_collection", "servers")
    state_subcollection = firestore_config.get("state_subcollection", "state")
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
            state_subcollection=state_subcollection,
        )
        total += count

    logger.info(f"Migration complete: {total} announcement documents written across {len(guilds)} guild(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Firestore state from flat-list to per-announcement documents"
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
