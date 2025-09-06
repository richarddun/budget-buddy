import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

from ynab_sdk_client import YNABSdkClient
from localdb import payee_db

logger = logging.getLogger("uvicorn.error")


def _canonicalize_payee(name: str) -> str:
    """Simplify payee text for an icontains rule: strip digits, collapse spaces, trim."""
    import re
    s = name or ""
    s = re.sub(r"\d+", "", s)  # remove numbers
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _category_lookup(client: YNABSdkClient, budget_id: str) -> Dict[str, Tuple[str, str]]:
    """Map category_id -> (group_name, category_name)."""
    groups = client.get_categories(budget_id)
    out: Dict[str, Tuple[str, str]] = {}
    for g in groups:
        gname = g.get("name", "")
        for c in g.get("categories", []) or []:
            cid = c.get("id")
            cname = c.get("name", "")
            if cid:
                out[cid] = (gname, cname)
    return out


def backfill_from_ynab(
    *,
    budget_id: str,
    months: int = 12,
    min_occurrences: int = 2,
    generalize: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Derive local payee rules from historical transactions categorized in YNAB.

    Strategy:
    - Pull transactions since N months ago.
    - Group by payee_name, consider only outflows (amount < 0).
    - For each payee, pick dominant category_id by frequency.
    - Create or update a local rule with match_type=icontains (generalized) or exact.
    """
    client = YNABSdkClient()
    since_date = (datetime.utcnow().date() - timedelta(days=30 * months)).isoformat()
    txns = client.get_transactions(budget_id, since_date)
    cat_lut = _category_lookup(client, budget_id)

    per_payee: Dict[str, Dict[str, int]] = {}
    samples: Dict[str, List[Dict[str, Any]]] = {}

    for t in txns:
        payee = t.get("payee_name") or ""
        if not payee:
            continue
        amt = float(t.get("amount", 0.0) or 0.0)
        if amt >= 0:
            continue  # focus on spending
        cid = t.get("category_id")
        if not cid:
            continue
        per_payee.setdefault(payee, {})
        per_payee[payee][cid] = per_payee[payee].get(cid, 0) + 1
        if payee not in samples:
            samples[payee] = []
        if len(samples[payee]) < 3:
            samples[payee].append({"date": t.get("date"), "amount": amt, "category_id": cid})

    created = 0
    updated = 0
    skipped = 0
    results: List[Dict[str, Any]] = []

    for payee, counts in per_payee.items():
        total = sum(counts.values())
        if total < min_occurrences:
            skipped += 1
            continue
        # pick dominant category
        cid = max(counts.items(), key=lambda kv: kv[1])[0]
        group_name, cat_name = cat_lut.get(cid, (None, None))  # type: ignore
        if not cat_name:
            skipped += 1
            continue

        pattern = _canonicalize_payee(payee) if generalize else payee
        match_type = "icontains" if generalize else "exact"
        confidence = round(counts[cid] / max(1, total), 3)

        if not dry_run:
            rule_id = payee_db.upsert_rule(
                pattern=pattern,
                match_type=match_type,
                suggested_category=group_name,
                suggested_subcategory=cat_name,
                suggested_memo=None,
                confidence=confidence,
            )
            # can't easily tell created vs updated without extra query; best-effort
            created += 1
        else:
            rule_id = -1

        results.append(
            {
                "payee": payee,
                "pattern": pattern,
                "match_type": match_type,
                "suggested_category": group_name,
                "suggested_subcategory": cat_name,
                "confidence": confidence,
                "occurrences": total,
                "top_category_hits": counts[cid],
                "sample": samples.get(payee, [])[:3],
                "rule_id": rule_id,
            }
        )

    logger.info(
        f"Backfill analyzed {len(per_payee)} payees, created/updated ~{created}, skipped {skipped}"
    )
    return {
        "since_date": since_date,
        "payee_count": len(per_payee),
        "rules_written": created if not dry_run else 0,
        "skipped": skipped,
        "dry_run": dry_run,
        "results_preview": results[:25],
    }

