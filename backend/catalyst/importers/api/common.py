"""The few small pieces every API importer uses.

Each source's downloading and reading stays in its own module: they really are
different. Only what's the same for every importer is here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

BATCH = 5000  # rows per insert, so a big import isn't sent as one huge statement


class ImportProblem(Exception):
    """The input, or something downloaded, isn't what the importer expects."""


def replace_rows(conn: sa.Connection, table: sa.Table, rows: list[dict[str, Any]]) -> None:
    """Delete every row in the table, then insert the new ones, a batch at a time."""
    conn.execute(table.delete())
    for start in range(0, len(rows), BATCH):
        conn.execute(table.insert(), rows[start:start + BATCH])


def run_folder(raw_dir: Path, name: str) -> Path:
    """Make the folder for this import run's downloads, raw/<name>/<date and time>/,
    where the name is the importer's table (or its command, for one that fills two)."""
    folder = Path(raw_dir) / name / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    return folder
