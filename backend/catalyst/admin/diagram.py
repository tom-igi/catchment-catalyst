"""The facts behind the admin page's diagram of every table.

`model` gathers them: every table and column from schema.yaml (each table's
`title`, `description` and `filled_by`, each column's `description` and
`example`), plus the sections, where each downloaded table comes from (with its
web page and command), what's done to its data on the way in (its
transformation, with a downloaded table's example), where each data table is
shown on the dashboards and the extra links from diagram.yaml, each table's
number (as on the numbered screenshots of the dashboards), and each source file
(catalyst.importers.inputs) with the tables it fills and the formulas it uses.
The admin page adds the row counts and the
uploads, and templates/home.html draws the diagram from them. (A source file's
or Excel table's example is made from its last approved file: examples.py.)

The tables in `left_off` (the admin page's own records) aren't on the page.

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
from catalyst.importers import inputs

DIAGRAM_FILE = Path(__file__).with_name("diagram.yaml")
FILLS = {"api", "input", "excel", "command", "admin"}
# What a table holds, shown in its box (where it comes from is in the column on its left). An importer's tables
# are as downloaded, unless their `filled` entry in diagram.yaml says `worked_out: true`; a source file's are
# worked out; an Excel table's are typed in. Tables no data comes into (e.g. Uploads) have none.
HOLDS = {"downloaded": "As downloaded", "worked_out": "Worked out", "typed": "Typed in"}

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
    problems = inputs.check(schema)
    if problems:
        raise ValueError(" ".join(problems))

    left_off = _left_off(schema, config.get("left_off") or [])
    sections = _sections(schema, config, left_off)
    shown = _dashboard(schema, config.get("dashboard") or {})
    numbers = _numbers(schema, config.get("numbers") or {}, shown)
    return {
        "sections": [
            {"title": s.title, "description": s.description, "data": s.data, "tables": [t.name for t in s.tables]}
            for s in sections
        ],
        "tables": [
            {**_table(t, schema, s.title, filled.get(t.name) or {}, shown.get(t.name, []), (counts or {}).get(t.name)),
             "number": numbers.get(t.name), "transform": _transform(t, filled.get(t.name) or {})}
            for s in sections for t in s.tables
        ],
        "links": [l for l in _links(schema, config.get("links") or []) if not {l["from"], l["to"]} & left_off],
        "holds": [{"key": key, "label": label} for key, label in HOLDS.items()],
        "inputs": [_input(source) for source in inputs.INPUTS.values() if source.name in schema.input_tables.values()],
    }


def _input(source: inputs.Input) -> dict:
    """A source file: where it comes from and what's read from it (each table's transformation is on the table)."""
    return {
        "name": source.name,
        "title": source.title,
        "provider": source.provider,
        "url": source.url,
        "file": source.file,
        "sheet": source.sheet,
        "headings": list(source.headings),
        "more_sheets": [{"sheet": name, "headings": list(headings)} for name, headings in source.more_sheets.items()],
        "tables": source.tables,
    }


def _transform(table: sa.Table, filled: dict) -> dict | None:
    """A table's transformation, the diagram's middle column: its inputs, and the steps (the function) that turn
    them into the table's columns, with a downloaded table's example. None for a table no data comes into (e.g.
    Locations)."""
    fill = table.info.get("filled_by")
    columns = [c.name for c in table.columns]
    if fill == "input":
        source = inputs.INPUTS[table.info["input"]]
        read = source.file_columns(table.name)
        steps = [
            {"columns": list(step.columns), "inputs": list(step.inputs), "text": step.text}
            for step in source.table_steps(table.name)
        ]
        return {
            "kind": "input", "name": "Formulas", "sub": _steps(len(steps)),
            "from": source.title, "input": source.name, "file": source.file, "sheet": source.table_sheet(table.name),
            "inputs": read, "steps": steps,
        }
    if fill == "api":
        read = filled.get("inputs") or []
        steps = [
            {"columns": [], "inputs": [], "text": _step_text(step), "example": _step_example(step)}
            for step in filled.get("transformation") or []
        ]
        return {
            "kind": "api", "name": "Reshaped", "sub": _steps(len(steps)) if steps else "By the importer",
            "from": filled.get("source"), "file": filled.get("input"), "sheet": None, "inputs": read, "steps": steps,
            "example": _api_example(table, filled.get("example")),
        }
    if fill == "excel":
        return {
            "kind": "excel", "name": "1 to 1", "sub": "No change", "from": "An Excel file in the table's layout",
            "file": None, "sheet": None, "inputs": columns,
            "steps": [{
                "columns": columns, "inputs": columns,
                "text": "Each column goes in as it is. The upload is only checked for its column names, each value's "
                        "type, and rows that are there twice.",
            }],
        }
    return None


def _steps(steps: int) -> str:
    """e.g. 5 steps."""
    return f"{steps} step{'' if steps == 1 else 's'}"


def _step_text(step) -> str:
    """A downloaded table's step: a sentence, or `step` and its `example`."""
    return step if isinstance(step, str) else step["step"]


def _step_example(step) -> str | None:
    return None if isinstance(step, str) else step.get("example")


def _api_example(table: sa.Table, example) -> dict | None:
    """A downloaded table's example from diagram.yaml: a few rows of the download (`in`), and the same rows in the
    table (`out`), each as {columns, rows}, as a source file's are (examples.py)."""
    if example is None:
        return None
    problem = f"The `filled` list in diagram.yaml gives {table.name} an example"
    if not isinstance(example, dict) or set(example) - {"about", "in", "out"}:
        raise ValueError(f"{problem} that isn't `about`, `in` and `out`")
    shown = {}
    for side in ("in", "out"):
        rows = example.get(side)
        if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"{problem} without `{side}`: a list of rows, each a column's name and its value")
        columns = list(dict.fromkeys(name for row in rows for name in row))
        if side == "out" and (unknown := [name for name in columns if name not in table.columns]):
            raise ValueError(f"{problem} with {', '.join(unknown)}, which isn't one of its columns in schema.yaml")
        shown[side] = {"columns": columns, "rows": [[row.get(name) for name in columns] for row in rows]}
    return {"about": str(example.get("about") or ""), **shown}


def _left_off(schema: Schema, names) -> set[str]:
    """The tables diagram.yaml's `left_off` leaves off the page."""
    if not isinstance(names, list) or (unknown := [name for name in names if name not in schema.metadata.tables]):
        raise ValueError(f"The `left_off` list in diagram.yaml should list tables in schema.yaml, not {names}")
    if data := [name for name in names if name in schema.data_tables]:
        raise ValueError(f"The `left_off` list in diagram.yaml has {', '.join(data)}, a data table, which is always on the page")
    return set(names)


def _sections(schema: Schema, config: dict, left_off: set[str] = frozenset()) -> list[Section]:
    """The sections from diagram.yaml, with every table in exactly one, except those left off."""
    tables = schema.metadata.tables
    core = [name for name in tables if name not in schema.data_tables and name not in left_off]
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


def _numbers(schema: Schema, numbers, shown: dict[str, list[dict]]) -> dict[str, int]:
    """Each table's number from diagram.yaml (as on the numbered screenshots): table name -> number."""
    if not isinstance(numbers, dict):
        raise ValueError("The `numbers` list in diagram.yaml should give each table its number, e.g. catchments: 1")
    seen: dict[int, str] = {}
    for name, number in numbers.items():
        if name not in schema.metadata.tables:
            raise ValueError(f"The `numbers` list in diagram.yaml has {name}, which isn't in schema.yaml")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError(f"The `numbers` list in diagram.yaml gives {name} the number {number}, which isn't a whole number from 1 up")
        if number in seen:
            raise ValueError(f"The `numbers` list in diagram.yaml gives {seen[number]} and {name} the same number, {number}")
        seen[number] = name
    missing = [name for name in shown if name not in numbers]
    if missing:
        raise ValueError(
            f"The `numbers` list in diagram.yaml has no number for {', '.join(missing)}, which is on the dashboards: "
            "give it the next number up"
        )
    return dict(numbers)


def _table(table: sa.Table, schema: Schema, section: str, filled: dict, dashboard: list[dict], rows: int | None) -> dict:
    fill = table.info.get("filled_by") or filled.get("how") or "command"
    if fill not in FILLS:
        raise ValueError(f"{table.name}: how it's filled must be one of {', '.join(sorted(FILLS))}, not {fill}")
    url = filled.get("url")
    if url is not None and not str(url).startswith("https://"):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} the web page {url}, which should start with https://")
    steps = filled.get("transformation") or []
    if not isinstance(steps, list) or not all(
        isinstance(step, str) or (isinstance(step, dict) and isinstance(step.get("step"), str) and set(step) <= {"step", "example"}
                                  and isinstance(step.get("example", ""), str))
        for step in steps
    ):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} a transformation that isn't a list of steps "
                         "(each a sentence, or `step` and its `example`)")
    read = filled.get("inputs") or []
    if not isinstance(read, list) or not all(isinstance(name, str) for name in read):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} inputs that aren't a list of column names")
    worked_out = filled.get("worked_out", False)
    if not isinstance(worked_out, bool) or (worked_out and fill != "api"):
        raise ValueError(f"The `filled` list in diagram.yaml gives {table.name} worked_out: {worked_out}, but it can only be "
                         "true, for a table filled by an importer")
    key = list(table.primary_key.columns)
    return {
        "name": table.name,
        "title": _title(table),
        "description": _plain(table.comment),
        "summary": _first_sentence(_plain(table.comment)),
        "kind": "data" if table.name in schema.data_tables else "core",
        "section": section,
        "fill": fill,  # api, input, excel, command or admin
        "holds": _holds(fill, worked_out),  # a key of HOLDS, or None
        "input": table.info.get("input"),  # for `filled_by: input`, the source file it's worked out from
        "source": filled.get("source"),
        "url": url,  # the source's web page
        "command": f"docker compose run --rm {filled['command']}" if filled.get("command") else None,
        "note": filled.get("note"),
        "transformation": [_step_text(step) for step in steps],  # what's done to the data on the way in; none: 1 to 1
        "dashboard": dashboard,  # where it's shown on the dashboards: [{page, panels}]
        "rows": rows,
        "one_row_per": [_label(c) for c in key] if len(key) > 1 else None,
        "columns": [_column(c, len(key)) for c in table.columns],
    }


def _holds(fill: str, worked_out: bool) -> str | None:
    """What a table holds (see HOLDS)."""
    if fill == "api":
        return "worked_out" if worked_out else "downloaded"
    return {"input": "worked_out", "excel": "typed"}.get(fill)


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
        "examples": [_example(v) for v in _examples(column)],
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
    if isinstance(t, sa.LargeBinary):
        return "File"
    return "Text"


def _label(column: sa.Column) -> str:
    if _is_catchment_id(column):
        return "Catchment ID"
    words = [WORDS.get(w, w) for w in column.name.split("_")]
    label = " ".join(words)
    return label[0].upper() + label[1:]


def _title(table: sa.Table) -> str:
    return table.info.get("title") or table.name.replace("_", " ").capitalize()


def _examples(column: sa.Column) -> list:
    """A column's example values from schema.yaml, one for each example row (a single value is one row)."""
    value = column.info.get("example")
    return value if isinstance(value, list) else [] if value is None else [value]


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
