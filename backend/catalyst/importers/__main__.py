"""Import data into the database.

    python -m catalyst.importers catchments imports/catchments.json

The database is chosen by the DATABASE_URL environment variable. Everything
downloaded is kept in RAW_FILES_DIR (default: imports/raw).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import sqlalchemy as sa

from catalyst.db import load_schema

from . import catchments
from .catchments import ImportProblem
from .ea_api import EAClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="importer", description="Import data into the database.")
    commands = parser.add_subparsers(dest="command", required=True)
    catchments_parser = commands.add_parser(
        "catchments", help="import catchments from the EA's Catchment Data Explorer"
    )
    catchments_parser.add_argument("file", type=Path, help=f"JSON file listing the catchments, e.g. {catchments.LIST_EXAMPLE}")
    catchments_parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)

    try:
        ids = catchments.read_catchment_list(args.file)
    except ImportProblem as e:
        print(e, file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    engine = sa.create_engine(url, connect_args={"connect_timeout": 10})
    try:
        return _import_catchments(engine, ids, yes=args.yes)
    except sa.exc.OperationalError as e:
        print(f"Could not connect to the database: {e.orig}", file=sys.stderr)
        return 1
    except sa.exc.DBAPIError as e:
        print(f"\nThe database refused the import: {e.orig}", file=sys.stderr)
        print("Nothing has been imported. (If a table is missing, run `schema apply` first.)", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def _import_catchments(engine: sa.Engine, ids: list[str], yes: bool) -> int:
    schema = load_schema()
    with engine.connect() as conn:
        existing = catchments.existing_ids(conn, schema, ids)

    print(f"Downloading {len(ids)} catchment(s) from the EA's Catchment Data Explorer:")
    found, problems = catchments.fetch(ids, EAClient(), progress=lambda c: print(f"  ✓ {c.id}  {c.name}"))
    if problems:
        print("\nNothing has been imported, because of these problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"\n{len(found)} catchment(s) to import:\n")
    for c in found:
        d = c.details
        print(f"  {'~ update' if c.id in existing else '+ add'}  {c.id}  {c.name}")
        print(f"        {d['waterbody_type']} · {d['management_catchment']} › {d['operational_catchment']}"
              f" · river length {c.river_length_km:g} km")
        print(f"        upstream: {_names(c.upstream)} · downstream: {_names(c.downstream)}")

    if not yes and not _confirm(f"\nImport {len(found)} catchment(s)? [y/N] "):
        print("Nothing has been imported.")
        return 1

    raw_dir = catchments.save_raw_files(found, Path(os.environ.get("RAW_FILES_DIR", "imports/raw")))
    with engine.begin() as conn:
        catchments.save(conn, schema, found)
        table = schema.metadata.tables["catchments"]
        rows = conn.execute(
            sa.select(table.c.id, table.c.name, table.c.area_ha, table.c.river_length_km)
            .where(table.c.id.in_(ids)).order_by(table.c.id)
        ).all()

    print(f"\nDone: {len(found)} catchment(s) imported.\n")
    for row in rows:
        print(f"  {row.id}  {row.name:<28} {row.area_ha:>10,.2f} ha  {row.river_length_km:>7g} km")
    print(f"\nThe downloaded files are kept in {raw_dir}")
    return 0


def _names(links: list[tuple[str, str]]) -> str:
    return ", ".join(name for _, name in links) or "none"


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print("\nNo terminal to confirm in: run with --yes to import without asking.", file=sys.stderr)
        return False
    return input(prompt).strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    sys.exit(main())
