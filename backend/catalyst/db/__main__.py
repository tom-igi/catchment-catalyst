"""Keep the database in line with schema.yaml.

    python -m catalyst.db validate     check schema.yaml for mistakes (no database needed)
    python -m catalyst.db plan         show what would change, without changing anything
    python -m catalyst.db apply        make the changes (asks first)

The database is chosen by the DATABASE_URL environment variable.
"""

from __future__ import annotations

import argparse
import os
import sys

import sqlalchemy as sa

from .schema import SchemaError, load_schema
from .sync import DataLossError, Plan, PlanChangedError, apply_changes, plan_changes

SYMBOLS = {"add": "+", "change": "~", "remove": "-"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schema", description="Keep the database in line with schema.yaml.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check schema.yaml for mistakes (no database needed)")
    commands.add_parser("plan", help="show what would change, without changing anything")
    apply_parser = commands.add_parser("apply", help="make the database match schema.yaml")
    apply_parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    apply_parser.add_argument(
        "--allow-data-loss", action="store_true",
        help="allow changes that delete data (dropping tables or columns, changing types)",
    )
    args = parser.parse_args(argv)

    try:
        schema = load_schema()
    except SchemaError as e:
        print(f"schema.yaml has {len(e.problems)} problem(s):", file=sys.stderr)
        for problem in e.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print(f"schema.yaml is OK: {len(schema.metadata.tables)} tables.")
        return 0

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    engine = sa.create_engine(url, connect_args={"connect_timeout": 10})
    print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")

    try:
        with engine.connect():
            pass
    except sa.exc.OperationalError as e:
        print(f"Could not connect to the database: {e.orig}", file=sys.stderr)
        return 1

    try:
        plan = plan_changes(engine, schema)
        _print_plan(plan)
        if args.command == "plan":
            if plan.changes:
                print("\nNothing has been changed. Run `apply` to make these changes.")
            return 0

        if plan.changes:
            if plan.data_loss and not args.allow_data_loss:
                print(
                    f"\nStopped: {len(plan.data_loss)} change(s) would delete data (marked ⚠).\n"
                    "Check that is intended, then run again with --allow-data-loss.",
                    file=sys.stderr,
                )
                return 1
            if not args.yes and not _confirm(f"\nApply {len(plan.changes)} change(s)? [y/N] "):
                print("Nothing has been changed.")
                return 1

            apply_changes(engine, schema, expected=plan.summaries, allow_data_loss=args.allow_data_loss)
            print(f"Done: {len(plan.changes)} change(s) applied.")
        return 0 if _update_data_map(schema) else 1

    except (DataLossError, PlanChangedError) as e:
        print(f"\nStopped: {e}. Nothing has been changed.", file=sys.stderr)
        return 1
    except sa.exc.DBAPIError as e:
        print(f"\nThe database refused a change: {e.orig}", file=sys.stderr)
        print("Nothing has been changed (everything was rolled back).", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def _update_data_map(schema) -> bool:
    """Rebuild the data map page (the optional datamap/ folder), if it's there."""
    try:
        import datamap
    except ModuleNotFoundError as e:
        if e.name != "datamap":
            raise
        return True
    try:
        path = datamap.build(schema)
    except Exception as e:  # the database is already updated; only the page failed
        print(f"\nThe database is up to date, but the data map couldn't be rebuilt: {e}", file=sys.stderr)
        return False
    print(f"Data map updated: {path.relative_to(os.getcwd())}")
    return True


def _print_plan(plan: Plan) -> None:
    if not plan.changes:
        print("The database already matches schema.yaml.")
    else:
        print(f"{len(plan.changes)} change(s) needed:\n")
        for change in plan.changes:
            warning = f"   ⚠ {change.data_loss}" if change.data_loss else ""
            print(f"  {SYMBOLS[change.kind]} {change.summary}{warning}")
            for line in change.details:
                print(f"        {line}")
    for warning in plan.warnings:
        print(f"\n  ! {warning}")


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print("\nNo terminal to confirm in: run with --yes to apply without asking.", file=sys.stderr)
        return False
    return input(prompt).strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    sys.exit(main())
