"""The facts behind the admin page's diagram of every table.

`model` gathers them: every table and column from schema.yaml (each table's
`title`, `description` and `filled_by`, each column's `description` and
`example`), plus the sections, where each downloaded table comes from (with its
web page and command), what's done to its data on the way in (its
transformation), where each data table is shown on the dashboards and the extra
links from diagram.yaml. The admin page adds the row counts and the Excel
uploads, and templates/home.html draws the diagram from them.

It's made each time the page is opened, so it always matches the schema.yaml
the admin page is running. When you add a table filled by an importer, add it
under `filled` in diagram.yaml, or the page can't say where it comes from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
import yaml
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from catalyst.db.schema import CATCHMENT_REFERENCE, Schema, load_schema

DIAGRAM_FILE = Path(__file__).with_name("diagram.yaml")
FILLS = {"api", "excel", "command", "admin"}

MAP_SHAPES = {
    "POINT": "Map point", "MULTIPOINT": "Map points",
    "LINESTRING": "Map line", "MULTILINESTRING": "Map line",
    "POLYGON": "Map area", "MULTIPOLYGON": "Map area",
}
DEFAULTS = {"now()": "the current time", "true": "Yes", "false": "No"}
WORDS = {"id": "ID", "ea": "EA", "url": "URL", "ha": "(ha)", "km": "(km)", "ids": "IDs"}
PLURALS = {"Text": "text", "Whole number": "whole numbers", "Number": "numbers", "Date": "dates",
           "Date and time": "dates and times", "Yes / No": "yes / no values", "ID code": "ID codes"}
SENTENCE_END = re.compile(r"(?<!e\.g)(?<!i\.e)\.\s")  # not the dot in "e.g. " or "i.e. "


@dataclass
class Section:
    title: str
    description: str
    tables: list[sa.Table]
    data: bool = False  # the data tables section


def model(schema: Schema | None = None, counts: dict[str, int] | None = None,
          diagram_file: Path = DIAGRAM_FILE) -> dict:
    """Every table, its columns, how it's filled and what it links to. `counts` is each table's number of rows, if known."""
    schema = schema or load_schema()
    config = yaml.safe_load(Path(diagram_file).read_text(encoding="utf-8"))
    filled = config.get("filled") or {}
    tables = schema.metadata.tables
    unknown = [name for name in filled if name not in tables]
    if unknown:
        raise ValueError(f"The `filled` list in diagram.yaml has {', '.join(unknown)}, which isn't in schema.yaml")

    sections = _sections(schema, config)
    shown = _dashboard(schema, config.get("dashboard") or {})
    return {
        "sections": [
            {"title": s.title, "description": s.description, "data": s.data, "tables": [t.name for t in s.tables]}
            for s in sections
        ],
        "tables": [
            _table(t, schema, s.title, filled.get(t.name) or {}, shown.get(t.name, []), (counts or {}).get(t.name))
            for s in sections for t in s.tables
        ],
        "links": _links(schema, config.get("links") or []),
    }


def _sections(schema: Schema, config: dict) -> list[Section]:
    """The sections from diagram.yaml, with every table in exactly one."""
    tables = schema.metadata.tables
    core = [name for name in tables if name not in schema.data_tables]
    sections, placed = [], set()
    for entry in config["sections"]:
        unknown = [name for name in entry["tables"] if name not in core]
        if unknown:
            raise ValueError(f"catalyst/admin/diagram.yaml lists {', '.join(unknown)}, which isn't a core table in schema.yaml")
        sections.append(Section(entry["title"], entry["description"], [tables[name] for name in entry["tables"]]))
        placed.update(entry["tables"])
    others = [tables[name] for name in core if name not in placed]
    if others:
        sections.append(Section("Other tables", "Core tables not yet given a section in catalyst/admin/diagram.yaml.", others))
    data = config["data_tables"]
    sections.append(Section(data["title"], data["description"], [tables[n] for n in schema.data_tables], data=True))
    return [s for s in sections if s.tables]


def _dashboard(schema: Schema, pages) -> dict[str, list[dict]]:
    """Where each table is shown on the dashboards: table name -> [{page, panels}], in the dashboards' order."""
    if not isinstance(pages, dict) or not all(isinstance(panels, dict) for panels in pages.values()):
        raise ValueError("The `dashboard` list in diagram.yaml should list each page, then each panel on it and its table(s)")
    shown: dict[str, dict[str, list[str]]] = {}  # table name -> page -> its panels
    for page, panels in pages.items():
        for panel, names in panels.items():
            for name in names if isinstance(names, list) else [names]:
                if name not in schema.metadata.tables:
                    raise ValueError(
                        f"The `dashboard` list in diagram.yaml gives {page}'s {panel} panel the table {name}, "
                        "which isn't in schema.yaml"
                    )
                shown.setdefault(name, {}).setdefault(str(page), []).append(str(panel))
    return {name: [{"page": page, "panels": panels} for page, panels in by_page.items()] for name, by_page in shown.items()}


def _table(table: sa.Table, schema: Schema, section: str, filled: dict, dashboard: list[dict], rows: int | None) -> dict:
    fill = table.info.get("filled_by") or filled.get("how") or "command"
    if fill not in FILLS:
        raise ValueError(f"{table.name}: how it's filled must be one of {', '.join(sorted(FILLS))}, not {fill}")
    url = filled.get("url")
    if url is not None and not str(url).startswith("https://"):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} the web page {url}, which should start with https://")
    steps = filled.get("transformation") or []
    if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} a transformation that isn't a list of steps")
    key = list(table.primary_key.columns)
    return {
        "name": table.name,
        "title": _title(table),
        "description": _plain(table.comment),
        "summary": _first_sentence(_plain(table.comment)),
        "kind": "data" if table.name in schema.data_tables else "core",
        "section": section,
        "fill": fill,  # api, excel, command or admin
        "source": filled.get("source"),
        "url": url,  # the source's web page
        "command": f"docker compose run --rm {filled['command']}" if filled.get("command") else None,
        "note": filled.get("note"),
        "transformation": steps,  # what's done to the data on the way in; none means it's copied 1 to 1
        "dashboard": dashboard,  # where it's shown on the dashboards: [{page, panels}]
        "rows": rows,
        "one_row_per": [_label(c) for c in key] if len(key) > 1 else None,
        "columns": [_column(c, len(key)) for c in table.columns],
    }


def _column(column: sa.Column, key_size: int) -> dict:
    links_to = [fk.column.table.name for fk in column.foreign_keys]
    default = None
    if column.server_default is not None and column.identity is None:
        text = getattr(column.server_default.arg, "text", str(column.server_default.arg))
        default = DEFAULTS.get(text, text)
    return {
        "name": column.name,
        "label": _label(column),
        "type": _type_label(column.type),
        "meaning": _plain(column.comment) or ("The catchment this row belongs to" if _is_catchment_id(column) and links_to else ""),
        "example": _example(column.info.get("example")),
        "key": bool(column.primary_key),
        "unique_id": bool(column.primary_key and key_size == 1),
        "required": not column.nullable and column.identity is None,
        "automatic": column.identity is not None,
        "no_duplicates": bool(column.unique),
        "default": default,
        "links_to": links_to[0] if links_to else None,
        "catchment_id": _is_catchment_id(column),
    }


def _links(schema: Schema, extra: list[dict]) -> list[dict]:
    """Every link between tables: `id` (checked by the database), `list` (a list of IDs) or `name` (a table's name)."""
    tables = schema.metadata.tables
    links = [
        {"from": t.name, "column": c.name, "to": fk.column.table.name, "kind": "id", "required": not c.nullable}
        for t in tables.values() for c in t.columns for fk in c.foreign_keys
    ]
    groups = {"data tables": list(schema.data_tables), "excel tables": list(schema.excel_tables)}
    for entry in extra:
        table_name, _, column_name = entry["from"].partition(".")
        if table_name not in tables or column_name not in tables[table_name].columns:
            raise ValueError(f"The `links` list in diagram.yaml has {entry['from']}, which isn't in schema.yaml")
        column = tables[table_name].columns[column_name]
        for target in groups.get(entry["to"], [entry["to"]]):
            if target not in tables:
                raise ValueError(f"The `links` list in diagram.yaml links to {target}, which isn't in schema.yaml")
            kind = "list" if isinstance(column.type, sa.ARRAY) else "name"
            links.append({"from": table_name, "column": column_name, "to": target, "kind": kind, "required": not column.nullable})
    return links


def _is_catchment_id(column: sa.Column) -> bool:
    return f"{column.table.name}.{column.name}" == CATCHMENT_REFERENCE or any(
        fk.target_fullname == CATCHMENT_REFERENCE for fk in column.foreign_keys
    )


def _type_label(t) -> str:
    if isinstance(t, sa.ARRAY):
        item = _type_label(t.item_type)
        return f"List of {PLURALS.get(item, item.lower())}"
    if isinstance(t, Geometry):
        return MAP_SHAPES.get(t.geometry_type.upper(), "Map shape")
    if isinstance(t, sa.Boolean):
        return "Yes / No"
    if isinstance(t, sa.Integer):
        return "Whole number"
    if isinstance(t, sa.Numeric):
        return "Number"
    if isinstance(t, sa.DateTime):
        return "Date and time"
    if isinstance(t, sa.Date):
        return "Date"
    if isinstance(t, postgresql.JSONB):
        return "Settings"
    return "Text"


def _label(column: sa.Column) -> str:
    if _is_catchment_id(column):
        return "Catchment ID"
    words = [WORDS.get(w, w) for w in column.name.split("_")]
    label = " ".join(words)
    return label[0].upper() + label[1:]


def _title(table: sa.Table) -> str:
    return table.info.get("title") or table.name.replace("_", " ").capitalize()


def _example(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _plain(text: str | None) -> str:
    """Text from schema.yaml without its `code` marks, which the page shows as plain text."""
    return (text or "").replace("`", "")


def _first_sentence(text: str) -> str:
    parts = SENTENCE_END.split(text, maxsplit=1)
    return parts[0] + "." if len(parts) > 1 else text
