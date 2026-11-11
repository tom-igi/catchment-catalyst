"""Publish every location's dashboard as web pages.

    python -m catalyst.publish

The pages are written to PUBLISHED_DIR (default: published), in a folder per
location. The database is chosen by the DATABASE_URL environment variable.
The admin page's Publish button does the same (see run.py).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import sqlalchemy as sa

from catalyst.db import load_schema

from .collect import PublishProblem
from .run import publish_all


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="publish", description="Publish every location's dashboard as web pages.").parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    out_dir = Path(os.environ.get("PUBLISHED_DIR", "published"))
    engine = sa.create_engine(url, connect_args={"connect_timeout": 10})
    try:
        gathered = publish_all(engine, load_schema(), out_dir)
    except PublishProblem as e:
        print(f"Nothing has been published. {e}", file=sys.stderr)
        return 1
    except sa.exc.OperationalError as e:
        print(f"Could not connect to the database: {e.orig}", file=sys.stderr)
        return 1
    except sa.exc.DBAPIError as e:
        print(f"The database gave an error, so nothing has been published: {e.orig}", file=sys.stderr)
        print("(If a table is missing, run `schema apply` first.)", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    for location in gathered:
        print(f"{location.name}: {len(location.catchments)} catchment(s), published to {out_dir / location.slug}/")
        for dataset in location.datasets:
            count = sum(len(rows) for rows in dataset.rows.values())
            about = "about the location" if dataset.key == "location_id" else f"for {len(dataset.rows)} of the catchments"
            print(f"  {dataset.title}: {count} row(s), {about}")

    current = {l.slug for l in gathered}
    for folder in sorted(out_dir.iterdir()):
        if folder.is_dir() and not folder.name.startswith(".") and folder.name not in current:
            print(f"\nNote: {folder} isn't a current location's folder. Delete it if it's no longer needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
