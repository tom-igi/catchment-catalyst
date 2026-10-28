"""Compare the live database with schema.yaml and bring it up to date.

Alembic's autogenerate engine works out the differences. Its operations are run
directly instead of being written out as migration files, so schema.yaml stays
the only description of the database.

Everything happens inside one transaction (PostgreSQL can roll back structure
changes), so a failed change leaves the database exactly as it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext
from alembic.operations import Operations, ops
from sqlalchemy.dialects import postgresql

from .schema import Schema

# Only tables in this PostgreSQL schema are managed. Anything elsewhere
# (e.g. extensions that keep their own tables) is left alone.
MANAGED_SCHEMA = "public"

# Tables in the managed schema that are not ours to manage.
IGNORED_TABLES = {"spatial_ref_sys"}  # created by PostGIS


class DataLossError(Exception):
    """The plan includes changes that delete data, and they were not allowed."""


class PlanChangedError(Exception):
    """The database changed between showing the plan and applying it."""


@dataclass
class Change:
    kind: str  # "add", "change" or "remove"
    summary: str
    details: list[str] = field(default_factory=list)
    data_loss: str | None = None  # why this change can lose data, if it can
    sql: str | None = None  # run directly (extensions and renames)
    op: ops.MigrateOperation | None = None  # run through Alembic


@dataclass
class Plan:
    changes: list[Change]
    warnings: list[str]

    @property
    def summaries(self) -> list[str]:
        return [c.summary for c in self.changes]

    @property
    def data_loss(self) -> list[Change]:
        return [c for c in self.changes if c.data_loss]


def plan_changes(engine: sa.Engine, schema: Schema) -> Plan:
    """Work out what would change, without changing anything."""
    with engine.connect() as conn:
        try:
            return _prepare(conn, schema)
        finally:
            conn.rollback()


def apply_changes(
    engine: sa.Engine,
    schema: Schema,
    *,
    expected: list[str] | None = None,
    allow_data_loss: bool = False,
) -> Plan:
    """Make the database match the schema, in a single transaction.

    `expected` is the list of change summaries the user agreed to; if the
    database has changed since then, nothing is applied.
    """
    with engine.begin() as conn:
        plan = _prepare(conn, schema)
        if expected is not None and plan.summaries != expected:
            raise PlanChangedError("the database changed since the plan was shown; run it again")
        if plan.data_loss and not allow_data_loss:
            raise DataLossError(f"{len(plan.data_loss)} change(s) would delete data")
        operations = Operations(MigrationContext.configure(conn))
        for change in plan.changes:
            if change.op is not None:
                operations.invoke(change.op)
    return plan


def _prepare(conn: sa.Connection, schema: Schema) -> Plan:
    """Build the plan on an open transaction.

    Extensions and renames are run straight away, because the comparison that
    follows needs to see their result. The caller decides whether to commit.
    """
    changes: list[Change] = []

    installed = set(conn.scalars(sa.text("SELECT extname FROM pg_extension")))
    for ext in schema.extensions:
        if ext not in installed:
            changes.append(_run(conn, "add", f"add extension {ext}", f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))

    existing = _managed_tables(conn)
    for new, old in schema.table_renames.items():
        if old in existing and new not in existing:
            changes.append(_run(conn, "change", f"rename table {old} → {new}", f'ALTER TABLE "{old}" RENAME TO "{new}"'))

    inspector = sa.inspect(conn)
    existing = _managed_tables(conn)
    for (table, new), old in schema.column_renames.items():
        if table in existing:
            columns = {c["name"] for c in inspector.get_columns(table)}
            if old in columns and new not in columns:
                changes.append(_run(
                    conn, "change", f"rename column {table}.{old} → {new}",
                    f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"',
                ))

    changes.extend(_rename_to_convention(conn, schema, existing))

    context = MigrationContext.configure(conn, opts={
        "compare_type": True,
        "compare_server_default": True,
        "include_name": lambda name, type_, parent_names: type_ != "table" or name in existing,
    })
    script = produce_migrations(context, schema.metadata)
    changes.extend(_describe(op) for op in _flatten(script.upgrade_ops))

    return Plan(changes, _primary_key_warnings(conn, schema, existing))


def _rename_to_convention(conn: sa.Connection, schema: Schema, existing: set[str]) -> list[Change]:
    """Give existing indexes and constraints the names schema.yaml expects.

    Renaming a table or column leaves the old name inside the names of its
    indexes and constraints (e.g. pk_waterbodies). Renaming those too keeps the
    database identical to one built fresh from schema.yaml, instead of dropping
    and rebuilding indexes or leaving stale names behind.
    """
    preparer = conn.dialect.identifier_preparer
    inspector = sa.inspect(conn)
    changes = []
    for table in schema.metadata.sorted_tables:
        if table.name not in existing:
            continue

        # What each object is (its "signature"), mapped to the name it should have.
        wanted = {}
        for constraint in table.constraints:
            columns = tuple(constraint.columns.keys())
            if isinstance(constraint, sa.PrimaryKeyConstraint):
                wanted[("pk",)] = constraint
            elif isinstance(constraint, sa.UniqueConstraint):
                wanted[("uq", columns)] = constraint
            elif isinstance(constraint, sa.ForeignKeyConstraint):
                target = (constraint.referred_table.name, tuple(e.column.name for e in constraint.elements))
                wanted[("fk", columns, *target)] = constraint
        for index in table.indexes:
            wanted[("ix", tuple(index.columns.keys()), bool(index.unique))] = index
        wanted = {sig: preparer.format_constraint(obj) for sig, obj in wanted.items()}

        found = []  # (signature, current name, is an index)
        pk = inspector.get_pk_constraint(table.name)
        if pk.get("name"):
            found.append((("pk",), pk["name"], False))
        for uq in inspector.get_unique_constraints(table.name):
            found.append((("uq", tuple(uq["column_names"])), uq["name"], False))
        for fk in inspector.get_foreign_keys(table.name):
            sig = ("fk", tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            found.append((sig, fk["name"], False))
        for ix in inspector.get_indexes(table.name):
            if not ix.get("duplicates_constraint"):  # those are renamed with their constraint
                found.append((("ix", tuple(ix["column_names"]), bool(ix["unique"])), ix["name"], True))

        names_in_use = {name for _, name, _ in found}
        for sig, current, is_index in found:
            new = wanted.get(sig)
            if new is None or new == current or new in names_in_use:
                continue
            if is_index:
                sql = f'ALTER INDEX "{current}" RENAME TO "{new}"'
            else:
                sql = f'ALTER TABLE "{table.name}" RENAME CONSTRAINT "{current}" TO "{new}"'
            changes.append(_run(conn, "change", f"rename {'index' if is_index else 'constraint'} {current} → {new}", sql))
            names_in_use.add(new)
    return changes


def _run(conn: sa.Connection, kind: str, summary: str, sql: str) -> Change:
    conn.execute(sa.text(sql))
    return Change(kind, summary, sql=sql)


def _managed_tables(conn: sa.Connection) -> set[str]:
    names = conn.scalars(
        sa.text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
        {"schema": MANAGED_SCHEMA},
    )
    return set(names) - IGNORED_TABLES


def _flatten(op):
    if isinstance(op, ops.OpContainer):
        for child in op.ops:
            yield from _flatten(child)
    else:
        yield op


def _primary_key_warnings(conn: sa.Connection, schema: Schema, existing: set[str]) -> list[str]:
    """Alembic doesn't detect primary key changes, so at least point them out."""
    inspector = sa.inspect(conn)
    warnings = []
    for table in schema.metadata.sorted_tables:
        if table.name not in existing:
            continue
        in_db = inspector.get_pk_constraint(table.name)["constrained_columns"]
        in_file = [c.name for c in table.primary_key.columns]
        if sorted(in_db) != sorted(in_file):
            warnings.append(
                f"{table.name}: the primary key is ({', '.join(in_db)}) in the database but "
                f"({', '.join(in_file)}) in schema.yaml. This can't be changed automatically."
            )
    return warnings


# --- Describing changes ------------------------------------------------------

def _describe(op) -> Change:
    if isinstance(op, ops.CreateTableOp):
        columns = [c for c in op.columns if isinstance(c, sa.Column)]
        return Change("add", f"create table {op.table_name}", [_column_line(c) for c in columns], op=op)
    if isinstance(op, ops.DropTableOp):
        return Change("remove", f"drop table {op.table_name}", data_loss="deletes the table and all its rows", op=op)
    if isinstance(op, ops.AddColumnOp):
        return Change("add", f"add column {op.table_name}.{op.column.name}", [_column_line(op.column)], op=op)
    if isinstance(op, ops.DropColumnOp):
        return Change("remove", f"drop column {op.table_name}.{op.column_name}",
                      data_loss="deletes every value in the column", op=op)
    if isinstance(op, ops.AlterColumnOp):
        return _describe_alter_column(op)
    if isinstance(op, ops.CreateIndexOp):
        return Change("add", f"add index {op.index_name} on {op.table_name} ({_names(op.columns)})", op=op)
    if isinstance(op, ops.DropIndexOp):
        return Change("remove", f"drop index {op.index_name}", op=op)
    if isinstance(op, ops.CreateForeignKeyOp):
        return Change("add", f"add reference {op.source_table}({_names(op.local_cols)}) → "
                             f"{op.referent_table}({_names(op.remote_cols)})", op=op)
    if isinstance(op, ops.CreateUniqueConstraintOp):
        return Change("add", f"make {op.table_name}({_names(op.columns)}) unique", op=op)
    if isinstance(op, ops.DropConstraintOp):
        kind = {"foreignkey": "reference", "unique": "unique rule", "check": "check rule"}.get(op.constraint_type, "constraint")
        return Change("remove", f"drop {kind} {op.constraint_name} on {op.table_name}", op=op)
    if isinstance(op, ops.CreateTableCommentOp):
        return Change("change", f"update description of table {op.table_name}", op=op)
    if isinstance(op, ops.DropTableCommentOp):
        return Change("change", f"remove description of table {op.table_name}", op=op)
    return Change("change", f"{type(op).__name__} on {getattr(op, 'table_name', '?')}", op=op)


def _describe_alter_column(op: ops.AlterColumnOp) -> Change:
    details = []
    data_loss = None
    if op.modify_type is not None:
        details.append(f"type: {_type(op.existing_type)} → {_type(op.modify_type)}")
        data_loss = "converts existing values to the new type"
        # Lets PostgreSQL convert between types it won't convert on its own (e.g. text → integer).
        op.kw["postgresql_using"] = f'"{op.column_name}"::{_type(op.modify_type)}'
    if op.modify_nullable is not None:
        details.append("now required" if op.modify_nullable is False else "no longer required")
    if op.modify_server_default is not False:
        details.append(f"default: {_default(op.existing_server_default)} → {_default(op.modify_server_default)}")
    if op.modify_comment is not False:
        details.append("description updated")
    return Change("change", f"change column {op.table_name}.{op.column_name}", details, data_loss, op=op)


def _column_line(column: sa.Column) -> str:
    notes = []
    if column.primary_key:
        notes.append("primary key")
    elif not column.nullable:
        notes.append("required")
    if column.unique:
        notes.append("unique")
    if column.identity is not None:
        notes.append("auto-numbered")
    if column.server_default is not None and column.identity is None:
        notes.append(f"default {_default(column.server_default)}")
    for fk in column.foreign_keys:
        notes.append(f"→ {fk.target_fullname}")
    return f"{column.name:<32} {_type(column.type):<28} {', '.join(notes)}".rstrip()


def _type(type_) -> str:
    if type_ is None:
        return "?"
    return type_.compile(dialect=postgresql.dialect()).lower()


def _default(default) -> str:
    if default is None or default is False:
        return "none"
    if isinstance(default, sa.Identity):
        return "auto-numbered"
    if isinstance(default, sa.DefaultClause):
        default = default.arg
    return getattr(default, "text", str(default))


def _names(items) -> str:
    return ", ".join(getattr(i, "name", None) or str(i) for i in items)
