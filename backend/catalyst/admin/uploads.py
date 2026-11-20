"""The uploads table, and the uploaded files.

Every file that gets as far as a preview gets a row in the uploads table, with
the file kept exactly as it was uploaded (its `file` column), so it's in the
database's backups. (Until 20 November 2026 they were kept in imports/raw/.)
The file is only read when it's needed: the lists here leave it out.

A source file can also be worked out again from an earlier upload's file, with
its formulas as they are now: that's a new upload of the same file, with
`worked_out_again_from` saying which.

An upload is either an Excel file for one table (1 to 1), or a source file,
which can fill several tables. Either way its changes are a Comparison per
table: `comparisons`, by table name.
"""

from __future__ import annotations

import datetime

import sqlalchemy as sa

from catalyst.db import Schema
from catalyst.importers.excel import Comparison

PREVIEW, APPROVED, CANCELLED = "preview", "approved", "cancelled"


def create(
    conn: sa.Connection,
    schema: Schema,
    uploaded_to: str,
    file_name: str,
    data: bytes,
    user: str,
    rows_in_file: int,
    comparisons: dict[str, Comparison],
    source_file: bool = False,
    worked_out_again_from: int | None = None,
) -> int:
    """Record the upload, with its file. Returns the upload's ID.

    `uploaded_to` is the table, or for a source file (`source_file`), its input's name.
    """
    uploads = _table(schema)
    return conn.execute(
        uploads.insert()
        .values(
            uploaded_to=uploaded_to, file_name=file_name, file=data, uploaded_by=user, rows_in_file=rows_in_file,
            worked_out_again_from=worked_out_again_from, **_counts(comparisons, source_file),
        )
        .returning(uploads.c.id)
    ).scalar_one()


def get(conn: sa.Connection, schema: Schema, upload_id: int, *, for_update: bool = False) -> sa.Row | None:
    query = _select(schema).where(_table(schema).c.id == upload_id)
    return conn.execute(query.with_for_update() if for_update else query).one_or_none()


def file(conn: sa.Connection, schema: Schema, upload_id: int) -> bytes:
    """The upload's file, as it was uploaded."""
    uploads = _table(schema)
    return bytes(conn.execute(sa.select(uploads.c.file).where(uploads.c.id == upload_id)).scalar_one())


def recent(conn: sa.Connection, schema: Schema, uploaded_to: str, limit: int = 10) -> list[sa.Row]:
    uploads = _table(schema)
    return conn.execute(
        _select(schema).where(uploads.c.uploaded_to == uploaded_to).order_by(uploads.c.id.desc()).limit(limit)
    ).all()


def last_approved(conn: sa.Connection, schema: Schema) -> dict[str, sa.Row]:
    """The most recent approved upload for each table (or source file)."""
    uploads = _table(schema)
    rows = conn.execute(
        _select(schema).where(uploads.c.status == APPROVED)
        .order_by(uploads.c.uploaded_to, uploads.c.approved_at.desc())
        .distinct(uploads.c.uploaded_to)
    )
    return {row.uploaded_to: row for row in rows}


def approved_since(conn: sa.Connection, schema: Schema, since: datetime.datetime) -> list[sa.Row]:
    """The uploads approved after a time (e.g. the last publish), oldest first."""
    uploads = _table(schema)
    return conn.execute(
        _select(schema).where(uploads.c.status == APPROVED, uploads.c.approved_at > since)
        .order_by(uploads.c.approved_at, uploads.c.id)
    ).all()


def approve(conn: sa.Connection, schema: Schema, upload_id: int, comparisons: dict[str, Comparison], source_file: bool = False) -> None:
    """Record the approval. The caller holds the publish lock (catalyst.publish.run.lock), so the time is now,
    not when the transaction started, and so it's in the right order with the publishes' times."""
    uploads = _table(schema)
    conn.execute(
        uploads.update().where(uploads.c.id == upload_id)
        .values(status=APPROVED, approved_at=sa.func.clock_timestamp(), **_counts(comparisons, source_file))
    )


def cancel(conn: sa.Connection, schema: Schema, upload_id: int) -> None:
    uploads = _table(schema)
    conn.execute(uploads.update().where(uploads.c.id == upload_id).values(status=CANCELLED))


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


def _select(schema: Schema) -> sa.Select:
    """The uploads' rows without their files, which are only read when needed (see `file`)."""
    uploads = _table(schema)
    return sa.select(*(c for c in uploads.columns if c.name != "file"))
