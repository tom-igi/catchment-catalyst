"""Compare an upload with the table, then make the table match it.

Rows are matched by the table's primary key (e.g. catchment, measure and year
for EA scores). A row in the file but not the table is added; one in both with
different values is changed; one in the table but not the file is deleted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from .workbook import FileRow, UploadError, show_value

MAX_ROWS_LISTED = 10  # per missing link, in problem messages


@dataclass
class Changed:
    row: FileRow
    old: dict[str, Any]  # the row as it is in the table now
    columns: list[str]  # the columns whose values change


@dataclass
class Comparison:
    added: list[FileRow]
    changed: list[Changed]
    removed: list[dict[str, Any]]
    unchanged: int

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    @property
    def fingerprint(self) -> str:
        """Identifies exactly these changes.

        Shown with the preview and checked again on approval, so the table is
        only changed in the way the person approving saw.
        """
        entries = sorted(
            [json.dumps(["add", r.values], sort_keys=True, default=str) for r in self.added]
            + [json.dumps(["change", c.old, c.row.values], sort_keys=True, default=str) for c in self.changed]
            + [json.dumps(["remove", r], sort_keys=True, default=str) for r in self.removed]
        )
        return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def key_columns(table: sa.Table) -> list[str]:
    return list(table.primary_key.columns.keys())


def lock(conn: sa.Connection, table: sa.Table) -> None:
    """Stop anything else changing the table until this transaction ends (it can still be read)."""
    conn.execute(sa.text(f'LOCK TABLE "{table.name}" IN SHARE ROW EXCLUSIVE MODE'))


def compare(conn: sa.Connection, table: sa.Table, rows: list[FileRow]) -> Comparison:
    """What uploading these rows would change. Raises UploadError for links to rows that don't exist."""
    problems = _missing_links(conn, table, rows)
    if problems:
        raise UploadError(problems)

    key = key_columns(table)
    current = {
        tuple(r[c] for c in key): dict(r)
        for r in conn.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings()
    }
    added, changed, unchanged = [], [], 0
    for row in rows:
        old = current.pop(tuple(row.values[c] for c in key), None)
        if old is None:
            added.append(row)
            continue
        different = [c for c in row.values if row.values[c] != old[c]]
        if different:
            changed.append(Changed(row, old, different))
        else:
            unchanged += 1
    return Comparison(added, changed, list(current.values()), unchanged)


def replace(conn: sa.Connection, table: sa.Table, comparison: Comparison) -> None:
    """Make the changes. Run inside the caller's transaction, so it's all or nothing."""
    key = key_columns(table)
    matches_key = sa.and_(*(table.c[c] == sa.bindparam(f"key_{c}") for c in key))
    if comparison.removed:
        conn.execute(
            table.delete().where(matches_key),
            [{f"key_{c}": r[c] for c in key} for r in comparison.removed],
        )
    others = [c for c in table.columns.keys() if c not in key]
    if comparison.changed and others:
        conn.execute(
            table.update().where(matches_key).values({c: sa.bindparam(f"new_{c}") for c in others}),
            [
                {**{f"key_{c}": ch.row.values[c] for c in key}, **{f"new_{c}": ch.row.values[c] for c in others}}
                for ch in comparison.changed
            ],
        )
    if comparison.added:
        conn.execute(table.insert(), [r.values for r in comparison.added])


def _missing_links(conn: sa.Connection, table: sa.Table, rows: list[FileRow]) -> list[str]:
    """Values that should match a row in another table (e.g. a catchment ID), but don't."""
    problems = []
    for column in table.columns:
        for fk in column.foreign_keys:
            target = fk.column
            lines_by_value: dict[Any, list[int]] = {}
            for row in rows:
                if row.values[column.name] is not None:
                    lines_by_value.setdefault(row.values[column.name], []).append(row.line)
            if not lines_by_value:
                continue
            found = set(conn.scalars(sa.select(target).where(target.in_(list(lines_by_value)))))
            for value, lines in lines_by_value.items():
                if value not in found:
                    listed = ", ".join(map(str, lines[:MAX_ROWS_LISTED])) + (" …" if len(lines) > MAX_ROWS_LISTED else "")
                    problems.append(
                        f"{column.name} {show_value(value)} isn't in the {target.table.name} table "
                        f"(row{'s' if len(lines) > 1 else ''} {listed})."
                    )
    return problems
