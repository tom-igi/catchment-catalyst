"""Import data into the database.

    python -m catalyst.importers catchments imports/catchments.json
    python -m catalyst.importers classifications
    python -m catalyst.importers storm-overflows
    python -m catalyst.importers river-obstacles
    python -m catalyst.importers postcodes

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

from .api import catchments, classifications, postcodes, river_obstacles, storm_overflows
from .api.common import ImportProblem
from .api.ea_api import EAClient, EAError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="importer", description="Import data into the database.")
    commands = parser.add_subparsers(dest="command", required=True)
    catchments_parser = commands.add_parser(
        "catchments", help="import catchments from the EA's Catchment Data Explorer"
    )
    catchments_parser.add_argument("file", type=Path, help=f"JSON file listing the catchments, e.g. {catchments.LIST_EXAMPLE}")
    catchments_parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    classifications_parser = commands.add_parser(
        "classifications",
        help="import the EA's classifications and reasons for not achieving good, for every imported catchment",
    )
    classifications_parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    for name, help in (
        ("storm-overflows", "import storm overflow spills from the EA's annual returns, for every imported catchment"),
        ("river-obstacles", "import weirs, culverts and other river obstacles, for every imported catchment"),
        ("postcodes", "import the postcodes inside every imported catchment, from Ordnance Survey's Code-Point Open"),
    ):
        commands.add_parser(name, help=help).add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)

    if args.command == "catchments":
        try:
            listed = catchments.read_catchment_list(args.file)
        except ImportProblem as e:
            print(e, file=sys.stderr)
            return 2
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    engine = sa.create_engine(url, connect_args={"connect_timeout": 10})
    try:
        if args.command == "catchments":
            return _import_catchments(engine, listed, yes=args.yes)
        return {
            "classifications": _import_classifications,
            "storm-overflows": _import_storm_overflows,
            "river-obstacles": _import_river_obstacles,
            "postcodes": _import_postcodes,
        }[args.command](engine, yes=args.yes)
    except sa.exc.OperationalError as e:
        print(f"Could not connect to the database: {e.orig}", file=sys.stderr)
        return 1
    except sa.exc.DBAPIError as e:
        print(f"\nThe database refused the import: {e.orig}", file=sys.stderr)
        print("Nothing has been imported. (If a table is missing, run `schema apply` first.)", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def _import_catchments(engine: sa.Engine, listed: catchments.CatchmentList, yes: bool) -> int:
    schema = load_schema()
    client = EAClient()
    ids = list(listed.ids)
    for management_id in listed.management_catchments:
        try:
            rivers = catchments.rivers_in(management_id, client)
        except (EAError, ImportProblem) as e:
            print(f"Nothing has been imported. Management catchment {management_id}: {e}", file=sys.stderr)
            return 1
        print(f"Management catchment {management_id}: {len(rivers)} river waterbodies")
        ids += [waterbody_id for waterbody_id, _ in rivers if waterbody_id not in ids]
    with engine.connect() as conn:
        existing = catchments.existing_ids(conn, schema, ids)

    print(f"Downloading {len(ids)} catchment(s) from the EA's Catchment Data Explorer:")
    found, problems = catchments.fetch(ids, client, progress=lambda c: print(f"  ✓ {c.id}  {c.name}"))
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


def _import_classifications(engine: sa.Engine, yes: bool) -> int:
    schema = load_schema()
    with engine.connect() as conn:
        by_management = classifications.management_catchments(conn, schema)
        before = classifications.current_counts(conn, schema)
    if not by_management:
        print("There are no catchments yet: import them first (`importer catchments`).", file=sys.stderr)
        return 1
    catchment_ids = set().union(*by_management.values())

    print(f"Downloading the EA's classifications and RNAGs for {len(by_management)} management catchment(s):")
    try:
        downloads = classifications.fetch(
            sorted(by_management), EAClient(timeout=300),
            progress=lambda m, f: print(f"  ✓ {m}  {f}"),
        )
        rows = classifications.read(downloads, catchment_ids)
    except ImportProblem as e:
        print(f"\nNothing has been imported: {e}", file=sys.stderr)
        return 1

    print(f"\nFor the {len(catchment_ids)} imported catchment(s), this replaces:\n")
    for table, new in rows.items():
        covered = len({row["catchment_id"] for row in new})
        print(f"  {table:<20} {before[table]:>7,} row(s) now  →  {len(new):>7,} row(s), for {covered} catchment(s)")
    missing = sorted(catchment_ids - {row["catchment_id"] for row in rows["ea_classifications"]})
    if missing:
        print(f"\n  The EA has no classifications for: {', '.join(missing)}")

    if not yes and not _confirm("\nReplace them? [y/N] "):
        print("Nothing has been imported.")
        return 1

    raw_dir = classifications.save_raw_files(downloads, Path(os.environ.get("RAW_FILES_DIR", "imports/raw")))
    with engine.begin() as conn:
        classifications.save(conn, schema, rows)
    print(f"\nDone. The downloaded files are kept in {raw_dir}")
    return 0


def _import_storm_overflows(engine: sa.Engine, yes: bool) -> int:
    schema = load_schema()
    table = schema.metadata.tables[storm_overflows.TABLE]
    with engine.connect() as conn:
        catchment_ids = catchments.imported_ids(conn, schema)
        before = conn.scalar(sa.select(sa.func.count()).select_from(table))
    if not catchment_ids:
        print("There are no catchments yet: import them first (`importer catchments`).", file=sys.stderr)
        return 1

    print(f"Downloading the EA's storm overflow annual returns, from {storm_overflows.FIRST_YEAR}:")
    try:
        downloads = storm_overflows.fetch(EAClient(timeout=300), progress=lambda year: print(f"  ✓ {year}"))
        print("Reading them (this takes a minute)...")
        rows = storm_overflows.read(downloads, catchment_ids)
    except ImportProblem as e:
        print(f"\nNothing has been imported: {e}", file=sys.stderr)
        return 1

    print(f"\nFor the {len(catchment_ids)} imported catchment(s), this replaces the {before:,} row(s) with {len(rows):,}:\n")
    for download in downloads:
        found = [r for r in rows if r["year"] == download.year]
        print(f"  {download.year}: {len(found):>4} overflow(s) into {len({r['catchment_id'] for r in found})} catchment(s)")
    if not yes and not _confirm("\nReplace them? [y/N] "):
        print("Nothing has been imported.")
        return 1

    raw_dir = storm_overflows.save_raw_files(downloads, Path(os.environ.get("RAW_FILES_DIR", "imports/raw")))
    with engine.begin() as conn:
        storm_overflows.save(conn, schema, rows)
    print(f"\nDone. The downloaded files are kept in {raw_dir}")
    return 0


def _import_river_obstacles(engine: sa.Engine, yes: bool) -> int:
    schema = load_schema()
    table = schema.metadata.tables[river_obstacles.TABLE]
    with engine.connect() as conn:
        area = river_obstacles.box(conn, schema)
        before = conn.scalar(sa.select(sa.func.count()).select_from(table))
    if area is None:
        print("There are no catchments yet: import them first (`importer catchments`).", file=sys.stderr)
        return 1

    print("Downloading the river obstacles around the imported catchments from River Obstacles:")
    try:
        pages = river_obstacles.fetch(EAClient(), area, progress=lambda n: print(f"  ✓ {n} so far"))
        with engine.connect() as conn:
            rows = river_obstacles.place(conn, schema, river_obstacles.read(pages))
    except ImportProblem as e:
        print(f"\nNothing has been imported: {e}", file=sys.stderr)
        return 1

    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["obstacle_type"] or "(none)"] = kinds.get(row["obstacle_type"] or "(none)", 0) + 1
    print(f"\n{len(rows):,} obstacle(s) are inside {len({r['catchment_id'] for r in rows})} catchment(s), "
          f"replacing the {before:,} row(s) now:")
    print("  " + ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items(), key=lambda k: -k[1])))
    if not yes and not _confirm("\nReplace them? [y/N] "):
        print("Nothing has been imported.")
        return 1

    raw_dir = river_obstacles.save_raw_files(pages, Path(os.environ.get("RAW_FILES_DIR", "imports/raw")))
    with engine.begin() as conn:
        river_obstacles.save(conn, schema, rows)
    print(f"\nDone. The downloaded files are kept in {raw_dir}")
    return 0


def _import_postcodes(engine: sa.Engine, yes: bool) -> int:
    schema = load_schema()
    table = schema.metadata.tables[postcodes.TABLE]
    with engine.connect() as conn:
        area = river_obstacles.box(conn, schema)
        before = conn.scalar(sa.select(sa.func.count()).select_from(table))
    if area is None:
        print("There are no catchments yet: import them first (`importer catchments`).", file=sys.stderr)
        return 1

    print("Downloading Code-Point Open (every postcode in Great Britain) from Ordnance Survey...")
    try:
        download = postcodes.fetch()
        print(f"  ✓ {len(download) / 1_000_000:.1f} MB. Reading it...")
        nearby = postcodes.read(download, area)
        with engine.connect() as conn:
            rows = postcodes.place(conn, schema, nearby)
    except ImportProblem as e:
        print(f"\nNothing has been imported: {e}", file=sys.stderr)
        return 1

    districts: dict[str, int] = {}
    for row in rows:
        district = row["postcode"].split(" ")[0]
        districts[district] = districts.get(district, 0) + 1
    print(f"\nOf the {len(nearby):,} postcodes in the box around the catchments, {len(rows):,} are inside "
          f"{len({r['catchment_id'] for r in rows})} catchment(s), replacing the {before:,} row(s) now. By district:")
    print("  " + ", ".join(f"{district} {count}" for district, count in sorted(districts.items(), key=lambda d: -d[1])))
    if not yes and not _confirm("\nReplace them? [y/N] "):
        print("Nothing has been imported.")
        return 1

    raw_dir = postcodes.save_raw_files(download, Path(os.environ.get("RAW_FILES_DIR", "imports/raw")))
    with engine.begin() as conn:
        postcodes.save(conn, schema, rows)
    print(f"\nDone. The downloaded file is kept in {raw_dir}")
    return 0


def _names(links: list[tuple[str, str]]) -> str:
    return ", ".join(f"{name} ({waterbody_id})" for waterbody_id, name in links) or "none"


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print("\nNo terminal to confirm in: run with --yes to import without asking.", file=sys.stderr)
        return False
    return input(prompt).strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    sys.exit(main())
