"""Read the master schema file (schema.yaml) into SQLAlchemy table definitions.

Other parts of the backend (admin API, importers) should get their tables from
`load_schema().metadata` rather than defining them a second time.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

SCHEMA_FILE = Path(__file__).with_name("schema.yaml")

# Gives every index and constraint a predictable name, so that later changes
# can find them again.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

TOP_LEVEL_OPTIONS = {"extensions", "tables", "data_tables"}
TABLE_OPTIONS = {"title", "description", "filled_by", "columns", "indexes", "renamed_from"}
COLUMN_OPTIONS = {
    "type", "description", "required", "primary_key", "identity", "unique",
    "index", "default", "references", "on_delete", "renamed_from", "example",
}
BOOLEAN_OPTIONS = {"required", "primary_key", "identity", "unique", "index"}
INDEX_OPTIONS = {"columns", "unique", "using"}
ON_DELETE = {"cascade": "CASCADE", "set null": "SET NULL", "restrict": "RESTRICT"}
INDEX_METHODS = {"btree", "gist", "gin"}

# Every data table must link each row to a catchment with this column.
CATCHMENT_COLUMN = "catchment_id"
CATCHMENT_REFERENCE = "catchments.id"

# How a table gets its data (the `filled_by` option).
FILLED_BY = {
    "api": "an importer, from an outside service's API (backend/catalyst/importers/api/)",
    "excel": "uploading an Excel file in the admin page (backend/catalyst/importers/excel/)",
}
# Column types an Excel upload can fill: text, whole numbers, numbers, yes/no
# and dates. (real and numeric aren't included: their values change slightly
# when stored, so every upload would look like it changed them. Use double.)
EXCEL_TYPES = (sa.String, sa.Integer, sa.Double, sa.Boolean, sa.Date)
EXCEL_TYPE_NAMES = "text, varchar(N), integer, bigint, smallint, double, boolean or date"

# Created by PostGIS, so not available as table names.
RESERVED_TABLES = {"spatial_ref_sys"}

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
TYPE_RE = re.compile(r"^(\w+)\s*(?:\((.*)\))?$")

SIMPLE_TYPES = {
    "text": sa.Text,
    "integer": sa.Integer,
    "bigint": sa.BigInteger,
    "smallint": sa.SmallInteger,
    "double": postgresql.DOUBLE_PRECISION,
    "real": sa.REAL,
    "boolean": sa.Boolean,
    "date": sa.Date,
    "timestamptz": lambda: sa.DateTime(timezone=True),
    "jsonb": postgresql.JSONB,
    "uuid": sa.Uuid,
}
GEOMETRY_TYPES = {
    "point", "linestring", "polygon", "multipoint", "multilinestring",
    "multipolygon", "geometry",
}
TYPE_HELP = (
    "use one of: " + ", ".join(SIMPLE_TYPES)
    + ", varchar(N), numeric(P,S), geometry(<shape>, <SRID>), or any of these with [] for a list"
)


class SchemaError(Exception):
    """schema.yaml has one or more mistakes."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class Schema:
    metadata: sa.MetaData
    extensions: list[str] = field(default_factory=list)
    data_tables: list[str] = field(default_factory=list)  # one per dataset
    table_renames: dict[str, str] = field(default_factory=dict)  # new -> old
    column_renames: dict[tuple[str, str], str] = field(default_factory=dict)  # (table, new) -> old

    @property
    def excel_tables(self) -> list[str]:
        """The tables filled by Excel upload, in the order of schema.yaml."""
        return [t.name for t in self.metadata.tables.values() if t.info.get("filled_by") == "excel"]


def load_schema(path: Path | str = SCHEMA_FILE) -> Schema:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as e:
        raise SchemaError([f"{path} is not valid YAML: {e}"]) from e
    return build_schema(data)


def build_schema(data: Any) -> Schema:
    """Turn the parsed contents of schema.yaml into a Schema, or raise SchemaError."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise SchemaError(["the file should have 'extensions' and 'tables' sections"])
    _check_keys(data, TOP_LEVEL_OPTIONS, "top level", problems)

    tables = data.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise SchemaError(problems + ["'tables' must list at least one table"])
    extensions = data.get("extensions") or []
    if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
        problems.append("'extensions' must be a list of names, e.g. [postgis]")
        extensions = []
    data_tables = data.get("data_tables") or {}
    if not isinstance(data_tables, dict):
        problems.append("'data_tables' must list tables, in the same way as 'tables'")
        data_tables = {}
    for name in tables.keys() & data_tables.keys():
        problems.append(f"'{name}' is listed in both 'tables' and 'data_tables'")

    # Every table's column names, so references can be checked before tables exist.
    known_columns = {
        name: set(spec.get("columns") or {}) if isinstance(spec, dict) else set()
        for name, spec in {**tables, **data_tables}.items()
    }
    schema = Schema(sa.MetaData(naming_convention=NAMING_CONVENTION), extensions, list(data_tables))
    for section, specs in (("tables", tables), ("data_tables", data_tables)):
        for name, spec in specs.items():
            _build_table(f"{section}.{name}", name, spec, known_columns, schema, problems)
    for name, spec in data_tables.items():
        _check_data_table(name, spec, problems)

    if problems:
        raise SchemaError(problems)
    return schema


def parse_type(spec: str) -> sa.types.TypeEngine:
    if spec.strip().endswith("[]"):
        item_type = parse_type(spec.strip()[:-2])
        if isinstance(item_type, (Geometry, postgresql.JSONB, postgresql.ARRAY)):
            raise ValueError(f"bad type '{spec}': lists of this type aren't supported")
        return postgresql.ARRAY(item_type)
    match = TYPE_RE.match(spec.strip().lower())
    if not match:
        raise ValueError(f"unknown type '{spec}' ({TYPE_HELP})")
    name, raw_args = match.groups()
    args = [a.strip() for a in raw_args.split(",")] if raw_args else []
    try:
        if name in SIMPLE_TYPES and not args:
            return SIMPLE_TYPES[name]()
        if name == "varchar" and len(args) == 1:
            return sa.String(int(args[0]))
        if name == "numeric" and len(args) <= 2:
            return sa.Numeric(*(int(a) for a in args))
        if name == "geometry" and len(args) == 2:
            if args[0] not in GEOMETRY_TYPES:
                raise ValueError(f"unknown geometry shape '{args[0]}'")
            # The spatial index is added by the `index` option instead, so it is
            # compared and named like any other index.
            return Geometry(geometry_type=args[0].upper(), srid=int(args[1]), spatial_index=False)
    except ValueError as e:
        raise ValueError(f"bad type '{spec}': {e}") from e
    raise ValueError(f"unknown type '{spec}' ({TYPE_HELP})")


def _build_table(where, name, spec, known_columns, schema: Schema, problems: list[str]) -> None:
    if not _check_name(name, where, problems):
        return
    if name in RESERVED_TABLES:
        problems.append(f"{where}: '{name}' is used by PostGIS, choose another name")
        return
    if isinstance(spec, dict):
        _check_keys(spec, TABLE_OPTIONS, where, problems)
    if not isinstance(spec, dict) or not isinstance(spec.get("columns"), dict) or not spec["columns"]:
        problems.append(f"{where}: needs a 'columns' section listing at least one column")
        return

    columns: list[sa.Column] = []
    indexes: list[tuple[list[str], bool, str | None]] = []
    for col_name, col_spec in spec["columns"].items():
        column = _build_column(where, name, col_name, col_spec, known_columns, schema, problems)
        if column is None:
            continue
        columns.append(column)
        if col_spec.get("index"):
            # Map shapes and lists need their own kinds of index.
            using = "gist" if isinstance(column.type, Geometry) else "gin" if isinstance(column.type, postgresql.ARRAY) else None
            indexes.append(([col_name], False, using))

    for i, idx in enumerate(spec.get("indexes") or []):
        parsed = _parse_index(idx, f"{where}.indexes[{i}]", known_columns[name], problems)
        if parsed:
            indexes.append(parsed)

    if not columns:
        return
    if "title" in spec and not isinstance(spec["title"], str):
        problems.append(f"{where}: 'title' must be text, e.g. title: EA Scores")
    filled_by = spec.get("filled_by")
    if filled_by is not None and filled_by not in FILLED_BY:
        problems.append(f"{where}: 'filled_by' must be one of: {', '.join(FILLED_BY)}")
    table = sa.Table(
        name, schema.metadata, *columns,
        comment=spec.get("description"),
        info={"title": spec.get("title"), "filled_by": filled_by},  # not stored in the database
    )
    if filled_by == "excel":
        _check_excel_table(where, table, problems)
    for cols, unique, using in indexes:
        if all(c in table.c for c in cols):
            kwargs = {"postgresql_using": using} if using else {}
            sa.Index(None, *(table.c[c] for c in cols), unique=unique, **kwargs)

    if old := spec.get("renamed_from"):
        if _check_name(old, f"{where}.renamed_from", problems):
            schema.table_renames[name] = old


def _build_column(table_where, table, name, spec, known_columns, schema: Schema, problems) -> sa.Column | None:
    where = f"{table_where}.columns.{name}"
    if not _check_name(name, where, problems):
        return None
    if not isinstance(spec, dict):
        problems.append(f"{where}: expected options such as 'type: text'")
        return None
    _check_keys(spec, COLUMN_OPTIONS, where, problems)
    for option in BOOLEAN_OPTIONS & spec.keys():
        if not isinstance(spec[option], bool):
            problems.append(f"{where}: '{option}' must be true or false")

    if "type" not in spec:
        problems.append(f"{where}: missing 'type'")
        return None
    try:
        col_type = parse_type(str(spec["type"]))
    except ValueError as e:
        problems.append(f"{where}: {e}")
        return None

    primary_key = spec.get("primary_key") is True
    if primary_key and spec.get("required") is False:
        problems.append(f"{where}: primary key columns are always required")

    args: list[Any] = []
    if spec.get("identity") is True:
        if not isinstance(col_type, sa.Integer):
            problems.append(f"{where}: 'identity' only works on integer columns")
        if "default" in spec:
            problems.append(f"{where}: 'identity' and 'default' can't be used together")
        args.append(sa.Identity())

    if "references" in spec:
        ondelete = None
        if "on_delete" in spec:
            ondelete = ON_DELETE.get(str(spec["on_delete"]).lower())
            if ondelete is None:
                problems.append(f"{where}: 'on_delete' must be one of: {', '.join(ON_DELETE)}")
        if _check_reference(spec["references"], where, known_columns, problems):
            args.append(sa.ForeignKey(spec["references"], ondelete=ondelete))
    elif "on_delete" in spec:
        problems.append(f"{where}: 'on_delete' only makes sense with 'references'")

    server_default = None
    if spec.get("default") is not None:
        server_default = _parse_default(spec["default"])

    if old := spec.get("renamed_from"):
        if _check_name(old, f"{where}.renamed_from", problems):
            schema.column_renames[(table, name)] = old

    example = spec.get("example")
    if not isinstance(example, (str, int, float, bool, datetime.date, type(None))):
        problems.append(f"{where}: 'example' must be a single value")

    return sa.Column(
        name,
        col_type,
        *args,
        primary_key=primary_key,
        nullable=not (primary_key or spec.get("required") is True),
        unique=spec.get("unique") is True,
        server_default=server_default,
        comment=spec.get("description"),
        info={"example": example},  # not stored in the database
    )


def _check_data_table(name, spec, problems) -> None:
    columns = spec.get("columns") if isinstance(spec, dict) else None
    column = columns.get(CATCHMENT_COLUMN) if isinstance(columns, dict) else None
    if not (
        isinstance(column, dict)
        and column.get("references") == CATCHMENT_REFERENCE
        and (column.get("required") is True or column.get("primary_key") is True)
    ):
        problems.append(
            f"data_tables.{name}: every data table needs a required '{CATCHMENT_COLUMN}' "
            f"column that references {CATCHMENT_REFERENCE}"
        )


def _check_excel_table(where, table: sa.Table, problems) -> None:
    """An Excel upload must be able to fill every column, and match its rows to the table's."""
    if not table.primary_key.columns:
        problems.append(
            f"{where}: tables filled by Excel need a primary key, so each uploaded row "
            "can be matched with the row already in the table"
        )
    for column in table.columns:
        if column.identity is not None:
            problems.append(
                f"{where}.columns.{column.name}: tables filled by Excel can't have numbered "
                "('identity') columns. Make the primary key from the table's own columns instead, "
                "e.g. catchment_id and year"
            )
        elif not isinstance(column.type, EXCEL_TYPES):
            problems.append(
                f"{where}.columns.{column.name}: Excel uploads can only fill {EXCEL_TYPE_NAMES} columns"
            )


def _parse_default(value: Any) -> sa.TextClause:
    if isinstance(value, bool):
        return sa.text("true" if value else "false")
    return sa.text(str(value))


def _parse_index(idx, where, table_columns, problems) -> tuple[list[str], bool, str | None] | None:
    if not isinstance(idx, dict) or not isinstance(idx.get("columns"), list) or not idx["columns"]:
        problems.append(f"{where}: needs 'columns: [column, ...]'")
        return None
    _check_keys(idx, INDEX_OPTIONS, where, problems)
    missing = [c for c in idx["columns"] if c not in table_columns]
    if missing:
        problems.append(f"{where}: unknown column(s) {', '.join(map(str, missing))}")
        return None
    using = idx.get("using")
    if using is not None and using not in INDEX_METHODS:
        problems.append(f"{where}: 'using' must be one of: {', '.join(sorted(INDEX_METHODS))}")
        return None
    return list(idx["columns"]), idx.get("unique") is True, using


def _check_reference(ref, where, known_columns, problems) -> bool:
    table, _, column = str(ref).partition(".")
    if not column:
        problems.append(f"{where}: 'references' should look like other_table.column")
    elif table not in known_columns:
        problems.append(f"{where}: references unknown table '{table}'")
    elif column not in known_columns[table]:
        problems.append(f"{where}: references unknown column '{ref}'")
    else:
        return True
    return False


def _check_name(name, where, problems) -> bool:
    if isinstance(name, str) and NAME_RE.match(name):
        return True
    problems.append(
        f"{where}: '{name}' is not a valid name "
        "(use lower_case_with_underscores, starting with a letter)"
    )
    return False


def _check_keys(spec: dict, allowed: set[str], where: str, problems: list[str]) -> None:
    for key in spec:
        if key not in allowed:
            problems.append(f"{where}: unknown option '{key}' (allowed: {', '.join(sorted(allowed))})")


class _UniqueKeyLoader(yaml.SafeLoader):
    """A YAML loader that rejects duplicate keys instead of silently keeping the last one."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"'{key}' appears twice", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep)
