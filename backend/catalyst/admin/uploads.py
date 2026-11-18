"""The uploads table, and the uploaded files.

Every file that gets as far as a preview is kept exactly as it was uploaded, in
a folder per table (or per source file) inside the raw files folder
(RAW_FILES_DIR, by default imports/raw), and gets a row in the uploads table.

An upload is either an Excel file for one table (1 to 1), or a source file,
which can fill several tables. Either way its changes are a Comparison per
table: `comparisons`, by table name.
"""

from __future__ import annotations

import datetime
from pathlib import Path, PurePath

import sqlalchemy as sa

from catalyst.db import Schema
from catalyst.importers.excel import Comparison

PREVIEW, APPROVED, CANCELLED = "preview", "approved", "cancelled"
SUFFIXES = {".xlsx", ".xls", ".csv"}  # kept as they came; anything else is kept as .xlsx, as before


def create(
    conn: sa.Connection,
    schema: Schema,
    raw_files_dir: Path,
    uploaded_to: str,
    file_name: str,
    data: bytes,
    user: str,
    rows_in_file: int,
    comparisons: dict[str, Comparison],
    source_file: bool = False,
) -> int:
    """Record the upload and keep the file. Returns the upload's ID.

    `uploaded_to` is the table, or for a source file (`source_file`), its input's name.
    """
    uploads = _table(schema)
    upload_id, uploaded_at = conn.execute(
        uploads.insert()
        .values(
            uploaded_to=uploaded_to, file_name=file_name, stored_as="", uploaded_by=user,
            rows_in_file=rows_in_file, **_counts(comparisons, source_file),
        )
        .returning(uploads.c.id, uploads.c.uploaded_at)
    ).one()
    suffix = PurePath(file_name).suffix.lower()
    stored_as = f"{uploaded_to}/{uploaded_at:%Y-%m-%d_%H%M%S}_{upload_id}{suffix if suffix in SUFFIXES else '.xlsx'}"
    path = raw_files_dir / stored_as
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    conn.execute(uploads.update().where(uploads.c.id == upload_id).values(stored_as=stored_as))
    return upload_id


def get(conn: sa.Connection, schema: Schema, upload_id: int, *, for_update: bool = False) -> sa.Row | None:
    uploads = _table(schema)
    query = sa.select(uploads).where(uploads.c.id == upload_id)
    return conn.execute(query.with_for_update() if for_update else query).one_or_none()


def recent(conn: sa.Connection, schema: Schema, uploaded_to: str, limit: int = 10) -> list[sa.Row]:
    uploads = _table(schema)
    return conn.execute(
        sa.select(uploads).where(uploads.c.uploaded_to == uploaded_to).order_by(uploads.c.id.desc()).limit(limit)
    ).all()


def last_approved(conn: sa.Connection, schema: Schema) -> dict[str, sa.Row]:
    """The most recent approved upload for each table (or source file)."""
    uploads = _table(schema)
    rows = conn.execute(
        sa.select(uploads).where(uploads.c.status == APPROVED)
        .order_by(uploads.c.uploaded_to, uploads.c.approved_at.desc())
        .distinct(uploads.c.uploaded_to)
    )
    return {row.uploaded_to: row for row in rows}


def approved_since(conn: sa.Connection, schema: Schema, since: datetime.datetime) -> list[sa.Row]:
    """The uploads approved after a time (e.g. the last publish), oldest first."""
    uploads = _table(schema)
    return conn.execute(
        sa.select(uploads).where(uploads.c.status == APPROVED, uploads.c.approved_at > since)
        .order_by(uploads.c.approved_at, uploads.c.id)
    ).all()


def approve(conn: sa.Connection, schema: Schema, upload_id: int, comparisons: dict[str, Comparison], source_file: bool = False) -> None:
    uploads = _table(schema)
    conn.execute(
        uploads.update().where(uploads.c.id == upload_id)
        .values(status=APPROVED, approved_at=sa.func.now(), **_counts(comparisons, source_file))
    )


def cancel(conn: sa.Connection, schema: Schema, upload_id: int) -> None:
    uploads = _table(schema)
    conn.execute(uploads.update().where(uploads.c.id == upload_id).values(status=CANCELLED))


def file_path(raw_files_dir: Path, upload: sa.Row) -> Path:
    return raw_files_dir / upload.stored_as


def _counts(comparisons: dict[str, Comparison], source_file: bool) -> dict:
    """The rows added, changed and deleted, in all; and for a source file, in each of its tables."""
    each = {name: [len(c.added), len(c.changed), len(c.removed)] for name, c in comparisons.items()}
    return {
        "rows_added": sum(n[0] for n in each.values()),
        "rows_changed": sum(n[1] for n in each.values()),
        "rows_removed": sum(n[2] for n in each.values()),
        "changes": each if source_file else sa.null(),  # (None would be stored as JSON's null)
    }


def _table(schema: Schema) -> sa.Table:
    return schema.metadata.tables["uploads"]
