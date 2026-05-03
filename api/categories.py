"""Categories API — CRUD for hierarchical category management.

Endpoints:
  GET    /api/categories         — List all categories (tree or flat), optional filter
  POST   /api/categories         — Create a new category
  PUT    /api/categories/{id}    — Update category name / parent
  DELETE /api/categories/{id}    — Archive a category (soft-delete via is_archived=1)

Design notes:
- Categories are hierarchical (parent_id self-references categories.id).
- Deletes are archival (is_archived=1) to preserve referential integrity.
- The 'Holding' category is system-reserved and always present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "id": int(r["id"]),
        "name": r["name"],
        "parent_id": int(r["parent_id"]) if r["parent_id"] is not None else None,
        "is_archived": bool(r["is_archived"]) if r["is_archived"] else False,
        "source": r["source"],
        "external_id": r["external_id"],
        "parent_name": r.get("parent_name"),
        "children_count": int(r.get("children_count", 0)),
        "transaction_count": int(r.get("transaction_count", 0)),
    }


def _build_tree(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert flat rows into a nested tree structure (does *not* sort)."""
    by_id: dict[int, dict] = {}
    for r in rows:
        d = _row_to_dict(r)
        d["children"] = []
        by_id[d["id"]] = d
    roots: list[dict] = []
    for d in by_id.values():
        pid = d["parent_id"]
        if pid is None or pid not in by_id:
            roots.append(d)
        else:
            parent = by_id[pid]
            parent.setdefault("children", []).append(d)
    return roots


def _ensure_holding_category(conn: sqlite3.Connection) -> int:
    """Idempotent — return existing or create the synthetic Holding category."""
    cur = conn.execute(
        "SELECT id FROM categories WHERE name = ? AND source IS NULL",
        ("Holding",),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO categories (name, parent_id, is_archived, source, external_id) VALUES (?, NULL, 0, NULL, NULL)",
        ("Holding",),
    )
    return int(cur.lastrowid)


def _validate_parent(conn: sqlite3.Connection, parent_id: int | None, self_id: int | None = None) -> None:
    """Ensure parent exists (or is NULL), and does not create a cycle."""
    if parent_id is None:
        return
    # Existence
    cur = conn.execute("SELECT 1 FROM categories WHERE id = ?", (parent_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail=f"Parent category {parent_id} not found")
    # Cycle detection: parent_id must not be a descendant of self_id
    if self_id is not None:
        visited = {parent_id}
        current = parent_id
        while current is not None:
            cur = conn.execute("SELECT parent_id FROM categories WHERE id = ?", (current,))
            row = cur.fetchone()
            if row and row["parent_id"] is not None:
                pid = int(row["parent_id"])
                if pid == self_id:
                    raise HTTPException(status_code=400, detail="Circular parent reference detected")
                if pid in visited:
                    break  # pre-existing cycle elsewhere; fail-safe
                visited.add(pid)
                current = pid
            else:
                break


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────

@router.get("/api/categories")
def list_categories(
    parent_id: Optional[int] = Query(None, description="Filter by parent ID (omit for all)"),
    archived: bool = Query(False, description="Include archived categories"),
    flat: bool = Query(False, description="Return flat list instead of tree"),
):
    """List categories. Default: tree view, no archived. Supports optional parent filter."""
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        if flat:
            # Flat list with parent name and counts
            rows = conn.execute(
                """
                SELECT c.*, p.name AS parent_name,
                    (SELECT COUNT(*) FROM categories child WHERE child.parent_id = c.id AND child.is_archived IN (0, ?)) AS children_count,
                    (SELECT COUNT(*) FROM transactions t WHERE t.category_id = c.id) AS transaction_count
                FROM categories c
                LEFT JOIN categories p ON p.id = c.parent_id
                WHERE (? OR c.is_archived = 0)
                  AND (c.parent_id IS NOT NULL OR c.parent_id IS NULL)
                  AND (? IS NULL OR c.parent_id = ?)
                ORDER BY c.name ASC
                """,
                (1 if archived else 0, archived, parent_id, parent_id),
            ).fetchall()
            items = [_row_to_dict(r) for r in rows]
            return {"count": len(items), "items": items}
        else:
            # Tree
            rows = conn.execute(
                """
                SELECT c.*, p.name AS parent_name,
                    (SELECT COUNT(*) FROM categories child WHERE child.parent_id = c.id AND child.is_archived IN (0, ?)) AS children_count,
                    (SELECT COUNT(*) FROM transactions t WHERE t.category_id = c.id) AS transaction_count
                FROM categories c
                LEFT JOIN categories p ON p.id = c.parent_id
                WHERE (? OR c.is_archived = 0)
                ORDER BY c.name ASC
                """,
                (1 if archived else 0, archived),
            ).fetchall()
            tree = _build_tree(rows)
            return {"count": len(rows), "tree": tree}


@router.get("/api/categories/{category_id}")
def get_category(category_id: int):
    """Get a single category by ID."""
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        row = conn.execute(
            """
            SELECT c.*, p.name AS parent_name
            FROM categories c
            LEFT JOIN categories p ON p.id = c.parent_id
            WHERE c.id = ?
            """,
            (category_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found")
        # Add counts
        children_cnt = conn.execute(
            "SELECT COUNT(*) AS cnt FROM categories WHERE parent_id = ? AND is_archived = 0",
            (category_id,),
        ).fetchone()
        txn_cnt = conn.execute(
            "SELECT COUNT(*) AS cnt FROM transactions WHERE category_id = ?",
            (category_id,),
        ).fetchone()
        d = _row_to_dict(row)
        d["children_count"] = int(children_cnt["cnt"]) if children_cnt else 0
        d["transaction_count"] = int(txn_cnt["cnt"]) if txn_cnt else 0
        return d


@router.post("/api/categories")
async def create_category(request: Request):
    """Create a new category.

    Body:
      name (str, required) — display name
      parent_id (int|null, optional) — parent category ID for hierarchy
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="categories-write")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")

    parent_id = payload.get("parent_id")
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="'parent_id' must be an integer or null")

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        _validate_parent(conn, parent_id)
        cur = conn.execute(
            "INSERT INTO categories (name, parent_id, is_archived, source, external_id) VALUES (?, ?, 0, 'internal', NULL)",
            (name, parent_id),
        )
        new_id = int(cur.lastrowid)

    # Re-fetch
    with _connect(dbp) as conn:
        row = conn.execute(
            "SELECT c.*, p.name AS parent_name FROM categories c LEFT JOIN categories p ON p.id = c.parent_id WHERE c.id = ?",
            (new_id,),
        ).fetchone()
    return {"status": "ok", "category": _row_to_dict(row)}


@router.put("/api/categories/{category_id}")
async def update_category(category_id: int, request: Request):
    """Update a category. Supports partial body — only send fields to change.

    Body (all optional):
      name (str) — new display name
      parent_id (int|null) — new parent (null for root) — set to null explicitly
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="categories-write")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    fields: list[str] = []
    params: list = []

    def set_field(col: str, val):
        fields.append(f"{col} = ?")
        params.append(val)

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="'name' cannot be empty")
        set_field("name", name)

    if "parent_id" in payload:
        pv = payload["parent_id"]
        if pv is not None:
            try:
                pv = int(pv)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="'parent_id' must be an integer or null")
        set_field("parent_id", pv)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Ensure exists
        row = conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found")

        # Validate new parent (including cycle check)
        if "parent_id" in payload:
            new_parent = payload["parent_id"]
            if new_parent is not None:
                new_parent = int(new_parent)
            _validate_parent(conn, new_parent, self_id=category_id)

        params.append(category_id)
        conn.execute(f"UPDATE categories SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()

        row = conn.execute(
            "SELECT c.*, p.name AS parent_name FROM categories c LEFT JOIN categories p ON p.id = c.parent_id WHERE c.id = ?",
            (category_id,),
        ).fetchone()

    return {"status": "ok", "category": _row_to_dict(row)}


@router.delete("/api/categories/{category_id}")
async def archive_category(category_id: int, request: Request):
    """Archive a category (soft-delete via is_archived=1). Not a hard delete."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="categories-write")
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Check exists
        row = conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found")

        # Don't allow archiving the Holding category
        hold_row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND source IS NULL",
            ("Holding",),
        ).fetchone()
        if hold_row and int(hold_row["id"]) == category_id:
            raise HTTPException(status_code=400, detail="Cannot archive the system Holding category")

        # Archive it
        conn.execute("UPDATE categories SET is_archived = 1 WHERE id = ?", (category_id,))
        # Also cascade-archive children
        conn.execute("UPDATE categories SET is_archived = 1 WHERE parent_id = ?", (category_id,))
        conn.commit()

    return {"status": "archived", "id": category_id}
