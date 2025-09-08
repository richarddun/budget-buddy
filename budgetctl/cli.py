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

    # ingest ynab
    ynab_parser = ingest_sub.add_parser("ynab", help="Ingest from YNAB")
    ynab_mode = ynab_parser.add_mutually_exclusive_group(required=True)
    ynab_mode.add_argument("--delta", action="store_true", help="Run delta sync")
    ynab_mode.add_argument("--backfill", action="store_true", help="Run backfill")
    ynab_parser.add_argument("--months", type=int, default=1, help="Backfill horizon in months")
    ynab_parser.add_argument("--from-csv", dest="from_csv", type=Path, help="Import from YNAB CSV export")
    ynab_parser.add_argument(
        "--account",
        dest="csv_account",
        type=str,
        default=None,
        help="Override account name for CSV rows",
    )
    _add_common_db_arg(ynab_parser)

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
    reset_mode = reset_parser.add_mutually_exclusive_group()
    reset_mode.add_argument(
        "--delta",
        action="store_true",
        help="After reset, run delta sync (default: backfill)",
    )
    reset_mode.add_argument(
        "--backfill",
        action="store_true",
        help="After reset, run backfill (default)",
    )
    reset_parser.add_argument(
        "--months",
        type=int,
        default=1,
        help="Backfill horizon in months (when using backfill)",
    )
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
    if args.command == "ingest" and args.ingest_command == "ynab":
        # CSV import takes precedence when provided
        if args.from_csv:
            return ingest_handlers.ingest_from_csv(args.db, args.from_csv, account_override=args.csv_account)
        if args.delta:
            return ingest_handlers.delta_sync(args.db)
        if args.backfill:
            return ingest_handlers.backfill(args.db, months=args.months)
        print("No ingest mode chosen. See --help.")
        return 2

    if args.command == "categories" and args.categories_command == "sync-ynab":
        return admin_handlers.sync_categories(args.db)

    if args.command == "reconcile":
        return admin_handlers.reconcile(args.db)

    if args.command == "db" and args.db_command == "migrate":
        return admin_handlers.db_migrate(args.db)

    if args.command == "db" and args.db_command == "reset":
        # Determine populate mode
        populate = not args.no_populate
        use_delta = bool(args.delta)
        # If neither --delta nor --backfill specified, default is backfill
        if args.backfill:
            use_delta = False
        return admin_handlers.db_reset(
            args.db,
            populate=populate,
            delta=use_delta,
            months=args.months,
            force=args.force,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
