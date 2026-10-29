"""The uploads table, and the uploaded files.

Every file that gets as far as a preview is kept exactly as it was uploaded, in
a folder per table inside the raw files folder (RAW_FILES_DIR, by default
imports/raw), and gets a row in the uploads table.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from catalyst.db import Schema
from catalyst.importers.excel import Comparison

PREVIEW, APPROVED, CANCELLED = "preview", "approved", "cancelled"


def create(
    conn: sa.Connection,
    schema: Schema,
    raw_files_dir: Path,
    table: sa.Table,
    file_name: str,
    data: bytes,
    user: str,
    rows_in_file: int,
    comparison: Comparison,
) -> int:
    """Record the upload and keep the file. Returns the upload's ID."""
    uploads = _table(schema)
    upload_id, uploaded_at = conn.execute(
        uploads.insert()
        .values(
            table_name=table.name, file_name=file_name, stored_as="", uploaded_by=user,
            rows_in_file=rows_in_file, **_counts(comparison),
        )
        .returning(uploads.c.id, uploads.c.uploaded_at)
    ).one()
    stored_as = f"{table.name}/{uploaded_at:%Y-%m-%d_%H%M%S}_{upload_id}.xlsx"
    path = raw_files_dir / stored_as
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    conn.execute(uploads.update().where(uploads.c.id == upload_id).values(stored_as=stored_as))
    return upload_id


def get(conn: sa.Connection, schema: Schema, upload_id: int, *, for_update: bool = False) -> sa.Row | None:
    uploads = _table(schema)
    query = sa.select(uploads).where(uploads.c.id == upload_id)
    return conn.execute(query.with_for_update() if for_update else query).one_or_none()


def recent(conn: sa.Connection, schema: Schema, table_name: str, limit: int = 10) -> list[sa.Row]:
    uploads = _table(schema)
    return conn.execute(
        sa.select(uploads).where(uploads.c.table_name == table_name).order_by(uploads.c.id.desc()).limit(limit)
    ).all()


def last_approved(conn: sa.Connection, schema: Schema) -> dict[str, sa.Row]:
    """The most recent approved upload for each table."""
    uploads = _table(schema)
    rows = conn.execute(
        sa.select(uploads).where(uploads.c.status == APPROVED)
        .order_by(uploads.c.table_name, uploads.c.approved_at.desc())
        .distinct(uploads.c.table_name)
    )
    return {row.table_name: row for row in rows}


def approve(conn: sa.Connection, schema: Schema, upload_id: int, comparison: Comparison) -> None:
    uploads = _table(schema)
    conn.execute(
        uploads.update().where(uploads.c.id == upload_id)
        .values(status=APPROVED, approved_at=sa.func.now(), **_counts(comparison))
    )


def cancel(conn: sa.Connection, schema: Schema, upload_id: int) -> None:
    uploads = _table(schema)
    conn.execute(uploads.update().where(uploads.c.id == upload_id).values(status=CANCELLED))


def file_path(raw_files_dir: Path, upload: sa.Row) -> Path:
    return raw_files_dir / upload.stored_as


def _counts(comparison: Comparison) -> dict[str, int]:
    return {
        "rows_added": len(comparison.added),
        "rows_changed": len(comparison.changed),
        "rows_removed": len(comparison.removed),
    }


def _table(schema: Schema) -> sa.Table:
    return schema.metadata.tables["uploads"]
