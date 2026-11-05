"""Import the EA's classification results and reasons for not achieving good
(RNAGs) from the Catchment Data Explorer, for every catchment in the
catchments table.

The EA has one download of each for a whole management catchment, so this
downloads every management catchment the catchments are in, and keeps the rows
for the catchments that have been imported. Both tables are only ever filled
from here, so each import replaces all their rows.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa

from catalyst.db import Schema

from .catchments import ImportProblem
from .ea_api import EAClient, EAError

WATERBODY = "Water Body ID"
INTEGERS = {"id", "year", "cycle"}


@dataclass
class Source:
    """One of the EA's downloads, and the table it fills."""
    file: str  # e.g. classifications.csv
    table: str
    columns: dict[str, str]  # the file's column -> the table's column


SOURCES = [
    Source("classifications.csv", "ea_classifications", {
        WATERBODY: "catchment_id",
        "Classification Item": "item",
        "Year": "year",
        "Cycle": "cycle",
        "Classification Level": "level",
        "Status": "status",
        "Certainty": "certainty",
    }),
    Source("rnags.csv", "ea_rnags", {
        "ID": "id",
        WATERBODY: "catchment_id",
        "Cycle": "cycle",
        "Classification Element": "element",
        "Classification Status": "element_status",
        "Activity": "activity",
        "Activity Certainty": "activity_certainty",
        "Business Sector": "business_sector",
        "Category": "category",
        "Swmi": "source_type",
        "National Swmi Header": "national_issue",
    }),
]


@dataclass
class Download:
    management_catchment_id: int
    files: dict[str, bytes] = field(default_factory=dict)  # exactly as downloaded


def management_catchments(conn: sa.Connection, schema: Schema) -> dict[int, set[str]]:
    """Each management catchment the imported catchments are in, with their IDs."""
    table = schema.metadata.tables["catchments"]
    found: dict[int, set[str]] = {}
    for row in conn.execute(sa.select(table.c.management_catchment_id, table.c.id)):
        found.setdefault(row.management_catchment_id, set()).add(row.id)
    return found


def fetch(
    management_ids: list[int],
    client: EAClient,
    progress: Callable[[int, str], None] = lambda m, f: None,
) -> list[Download]:
    downloads = []
    for management_id in management_ids:
        download = Download(management_id)
        for source in SOURCES:
            try:
                download.files[source.file] = client.management_catchment_file(management_id, source.file)
            except EAError as e:
                raise ImportProblem(f"management catchment {management_id}, {source.file}: {e}") from e
            progress(management_id, source.file)
        downloads.append(download)
    return downloads


def read(downloads: list[Download], catchment_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Each table's new rows: those for the imported catchments."""
    rows: dict[str, list[dict[str, Any]]] = {source.table: [] for source in SOURCES}
    for download in downloads:
        for source in SOURCES:
            rows[source.table] += read_file(download.files[source.file], source, catchment_ids)
    return rows


def read_file(data: bytes, source: Source, catchment_ids: set[str]) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    missing = [c for c in source.columns if c not in (reader.fieldnames or [])]
    if missing:
        raise ImportProblem(
            f"the EA's {source.file} has no {', '.join(missing)} column. "
            "The EA may have changed the file, so the importer needs updating."
        )
    rows = []
    for line, record in enumerate(reader, start=2):
        if record[WATERBODY] not in catchment_ids:
            continue
        row = {}
        for field_name, column in source.columns.items():
            value = (record[field_name] or "").strip() or None
            if value is not None and column in INTEGERS:
                try:
                    value = int(value)
                except ValueError:
                    raise ImportProblem(f"the EA's {source.file}, line {line}: '{value}' in {field_name} isn't a whole number") from None
            row[column] = value
        rows.append(row)
    return rows


def current_counts(conn: sa.Connection, schema: Schema) -> dict[str, int]:
    return {
        source.table: conn.scalar(sa.select(sa.func.count()).select_from(schema.metadata.tables[source.table]))
        for source in SOURCES
    }


def save(conn: sa.Connection, schema: Schema, rows: dict[str, list[dict[str, Any]]]) -> None:
    """Replace every row in the tables with the new ones."""
    for name, new in rows.items():
        table = schema.metadata.tables[name]
        conn.execute(table.delete())
        for start in range(0, len(new), 5000):
            conn.execute(table.insert(), new[start:start + 5000])


def save_raw_files(downloads: list[Download], raw_dir: Path) -> Path:
    """Keep exactly what was downloaded, in a folder for this import run."""
    run_dir = Path(raw_dir) / "classifications" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    for download in downloads:
        folder = run_dir / str(download.management_catchment_id)
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in download.files.items():
            (folder / name).write_bytes(data)
    return run_dir
