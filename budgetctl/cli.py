import argparse
import os
import sys
from pathlib import Path

from .handlers import ingest_handlers, admin_handlers


DEFAULT_DB_PATH = Path("localdb/budget.db")


def _add_common_db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budgetctl", description="Budget Buddy ops CLI")
    subparsers = parser.add_subparsers(dest="command")

    # ingest group
    ingest_parser = subparsers.add_parser("ingest", help="Ingestion tasks")
    ingest_sub = ingest_parser.add_subparsers(dest="ingest_command")

    # ingest csv
    csv_parser = ingest_sub.add_parser("csv", help="Import from CSV")
    csv_parser.add_argument("csv_path", type=Path, help="Path to CSV file")
    csv_parser.add_argument(
        "--account",
        dest="csv_account",
        type=str,
        default=None,
        help="Override account name for CSV rows",
    )
    _add_common_db_arg(csv_parser)

    # categories group
    cat_parser = subparsers.add_parser("categories", help="Category sync and mapping")
    cat_sub = cat_parser.add_subparsers(dest="categories_command")
    cat_sync = cat_sub.add_parser("sync-ynab", help="Snapshot/sync YNAB categories")
    _add_common_db_arg(cat_sync)

    # reconcile
    rec_parser = subparsers.add_parser("reconcile", help="Run reconciliation checks")
    _add_common_db_arg(rec_parser)

    # db migrate (optional)
    db_parser = subparsers.add_parser("db", help="Database utilities")
    db_sub = db_parser.add_subparsers(dest="db_command")
    migrate_parser = db_sub.add_parser("migrate", help="Run DB migrations")
    _add_common_db_arg(migrate_parser)

    # db reset (purge + migrate + optional populate)
    reset_parser = db_sub.add_parser(
        "reset",
        help="Purge the DB file, re-create schema, and optionally repopulate",
    )
    _add_common_db_arg(reset_parser)
    reset_parser.add_argument(
        "--no-populate",
        dest="no_populate",
        action="store_true",
        help="Do not pull data after reset (schema only)",
    )
    reset_parser.add_argument(
        "--force",
        action="store_true",
        help="Do not prompt; proceed with destructive reset",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch
    if args.command == "ingest" and args.ingest_command == "csv":
        return ingest_handlers.ingest_from_csv(args.db, args.csv_path, account_override=args.csv_account)

    if args.command == "categories" and args.categories_command == "sync-ynab":
        return admin_handlers.sync_categories(args.db)

    if args.command == "reconcile":
        return admin_handlers.reconcile(args.db)

    if args.command == "db" and args.db_command == "migrate":
        return admin_handlers.db_migrate(args.db)

    if args.command == "db" and args.db_command == "reset":
        populate = not args.no_populate
        return admin_handlers.db_reset(
            args.db,
            populate=populate,
            force=args.force,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
