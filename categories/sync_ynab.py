from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from db.migrate import run_migrations
from ynab_sdk_client import YNABSdkClient


@dataclass
class SyncResult:
    started_at: str
    finished_at: str
    ynab_groups_seen: int
    ynab_categories_seen: int
    categories_upserted: int
    maps_created: int


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_holding_category(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id FROM categories WHERE source IS NULL OR source = 'internal' AND name = ?",
        ("Holding",),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO categories(name, parent_id, is_archived, source, external_id) VALUES(?, NULL, 0, 'internal', NULL)",
        ("Holding",),
    )
    return int(cur.lastrowid)


def _upsert_category_row(
    conn: sqlite3.Connection,
    *,
    source: str,
    external_id: str,
    name: str,
    parent_id: Optional[int],
    is_archived: int,
) -> int:
    # Lookup by (source, external_id)
    cur = conn.execute(
        "SELECT id FROM categories WHERE source = ? AND external_id = ?",
        (source, external_id),
    )
    row = cur.fetchone()
    if row:
        local_id = int(row[0])
        conn.execute(
            "UPDATE categories SET name = ?, parent_id = ?, is_archived = ? WHERE id = ?",
            (name, parent_id, is_archived, local_id),
        )
        return local_id
    # Insert new row
    cur = conn.execute(
        "INSERT INTO categories(name, parent_id, is_archived, source, external_id) VALUES(?, ?, ?, ?, ?)",
        (name, parent_id, is_archived, source, external_id),
    )
    return int(cur.lastrowid)


def _find_internal_match(conn: sqlite3.Connection, name: str) -> Optional[int]:
    cur = conn.execute(
        "SELECT id FROM categories WHERE (source IS NULL OR source = 'internal') AND name = ?",
        (name,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _ensure_category_map(
    conn: sqlite3.Connection,
    *,
    source: str,
    external_id: str,
    internal_category_id: int,
) -> bool:
    # Returns True if created/updated, False if unchanged
    cur = conn.execute(
        "SELECT internal_category_id FROM category_map WHERE source = ? AND external_id = ?",
        (source, external_id),
    )
    row = cur.fetchone()
    if row:
        # Keep existing mapping stable; only update if different
        existing = int(row[0])
        if existing != internal_category_id:
            conn.execute(
                "UPDATE category_map SET internal_category_id = ? WHERE source = ? AND external_id = ?",
                (internal_category_id, source, external_id),
            )
            return True
        return False
    conn.execute(
        "INSERT INTO category_map(source, external_id, internal_category_id) VALUES(?, ?, ?)",
        (source, external_id, internal_category_id),
    )
    return True


def run_sync(db_path: Path) -> SyncResult:
    """Snapshot YNAB category groups/categories and refresh category_map.

    Behavior:
    - Upserts YNAB category groups and categories into categories(source='ynab').
    - For mapping, prefer existing category_map. Otherwise try name-based match
      against internal categories; if not found, map to the Holding category.
    - Does not mutate internal category ids once assigned.
    """

    ynab_token = os.getenv("YNAB_TOKEN")
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not ynab_token or not budget_id:
        raise RuntimeError("Missing YNAB_TOKEN or YNAB_BUDGET_ID in environment")

    run_migrations(db_path)

    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    groups_seen = 0
    cats_seen = 0
    cat_upserts = 0
    maps_created = 0

    client = YNABSdkClient()
    groups = client.get_categories(budget_id) or []

    with _connect(db_path) as conn:
        holding_id = _ensure_holding_category(conn)

        # Upsert group rows first to get parent IDs
        group_local_ids: Dict[str, int] = {}
        for g in groups:
            gid = str(g.get("id"))
            gname = g.get("name") or f"Group {gid[:8]}"
            is_archived = 1 if (g.get("deleted") or g.get("hidden")) else 0
            local_id = _upsert_category_row(
                conn,
                source="ynab",
                external_id=gid,
                name=gname,
                parent_id=None,
                is_archived=is_archived,
            )
            group_local_ids[gid] = local_id
            groups_seen += 1
            cat_upserts += 1

        # Upsert categories and ensure category_map
        for g in groups:
            gid = str(g.get("id"))
            parent_local_id = group_local_ids.get(gid)
            for c in g.get("categories", []) or []:
                cid = str(c.get("id"))
                cname = c.get("name") or f"Category {cid[:8]}"
                is_archived = 1 if (c.get("deleted") or c.get("hidden")) else 0

                local_id = _upsert_category_row(
                    conn,
                    source="ynab",
                    external_id=cid,
                    name=cname,
                    parent_id=parent_local_id,
                    is_archived=is_archived,
                )
                cats_seen += 1
                cat_upserts += 1

                # Determine target internal category to map
                # Keep existing mapping stable if present
                cur = conn.execute(
                    "SELECT internal_category_id FROM category_map WHERE source = ? AND external_id = ?",
                    ("ynab", cid),
                )
                row = cur.fetchone()
                if row:
                    internal_id = int(row[0])
                else:
                    internal_id = _find_internal_match(conn, cname) or holding_id
                if _ensure_category_map(
                    conn,
                    source="ynab",
                    external_id=cid,
                    internal_category_id=internal_id,
                ):
                    maps_created += 1

    finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return SyncResult(
        started_at=started_at,
        finished_at=finished_at,
        ynab_groups_seen=groups_seen,
        ynab_categories_seen=cats_seen,
        categories_upserted=cat_upserts,
        maps_created=maps_created,
    )

