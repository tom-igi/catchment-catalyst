"""Build the data map page from the master schema file.

The page is plain HTML and CSS with no scripts or outside files, so it can be
opened straight from disk or hosted anywhere as a single file.
"""

from __future__ import annotations

import datetime
import html
from dataclasses import dataclass
from pathlib import Path
from string import Template

import sqlalchemy as sa
import yaml
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from catalyst.db.schema import CATCHMENT_REFERENCE, Schema, load_schema

HERE = Path(__file__).parent
SITE_DIR = HERE / "site"

MAP_SHAPES = {
    "POINT": "Map point", "MULTIPOINT": "Map points",
    "LINESTRING": "Map line", "MULTILINESTRING": "Map line",
    "POLYGON": "Map area", "MULTIPOLYGON": "Map area",
}
DEFAULTS = {"now()": "Set automatically to the current time", "true": "Default: Yes", "false": "Default: No"}
WORDS = {"id": "ID", "ea": "EA", "url": "URL", "ha": "(ha)", "km": "(km)", "ids": "IDs"}
PLURALS = {"Text": "text", "Whole number": "whole numbers", "Number": "numbers", "Date": "dates",
           "Date and time": "dates and times", "Yes / No": "yes / no values", "ID code": "ID codes"}


@dataclass
class Section:
    title: str
    description: str
    tables: list[sa.Table]
    data: bool = False  # the data tables section


def build(schema: Schema | None = None, out_dir: Path = SITE_DIR, sections_file: Path = HERE / "sections.yaml") -> Path:
    """Write the page to out_dir/index.html and return its path."""
    schema = schema or load_schema()
    sections = _sections(schema, sections_file)
    today = datetime.date.today()

    page = Template((HERE / "page.html").read_text(encoding="utf-8")).substitute(
        sections="\n".join(_section(s) for s in sections),
        tables="\n".join(_card(t, s) for s in sections for t in s.tables),
        generated=f"{today.day} {today:%B %Y}",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def _sections(schema: Schema, sections_file: Path) -> list[Section]:
    """The page's sections, from sections.yaml, with every table in exactly one."""
    config = yaml.safe_load(Path(sections_file).read_text(encoding="utf-8"))
    tables = schema.metadata.tables
    core = [name for name in tables if name not in schema.data_tables]
    sections, placed = [], set()
    for entry in config["sections"]:
        unknown = [name for name in entry["tables"] if name not in core]
        if unknown:
            raise ValueError(f"datamap/sections.yaml lists {', '.join(unknown)}, which isn't a core table in schema.yaml")
        sections.append(Section(entry["title"], entry["description"], [tables[name] for name in entry["tables"]]))
        placed.update(entry["tables"])
    others = [tables[name] for name in core if name not in placed]
    if others:
        sections.append(Section("Other tables", "Core tables not yet given a section in datamap/sections.yaml.", others))
    data = config["data_tables"]
    sections.append(Section(data["title"], data["description"], [tables[n] for n in schema.data_tables], data=True))
    return [s for s in sections if s.tables]


def _section(section: Section) -> str:
    tiles = "".join(
        f'<a class="tile" href="#{t.name}">'
        f'<span class="tile-title">{_e(_title(t))}</span>'
        f'<span class="tile-desc">{_e(_first_sentence(t.comment))}</span>'
        f'<span class="tile-meta">{len(t.columns)} columns</span></a>'
        for t in section.tables
    )
    return (
        f'<section class="group"><h2>{_e(section.title)}</h2>'
        f'<p class="group-note">{_e(section.description)}</p><div class="tiles">{tiles}</div></section>'
    )


def _card(table: sa.Table, section: Section) -> str:
    columns = list(table.columns)
    headings = "".join(f'<th scope="col"{_catchment_class(c)}>{_e(_label(c))}</th>' for c in columns)
    types = "".join(f"<td>{_type(c)}</td>" for c in columns)
    example = "".join(f"<td>{_e(_example(c.info.get('example')))}</td>" for c in columns)

    key = [c for c in table.primary_key.columns]
    one_row_per = ""
    if len(key) > 1:
        one_row_per = f" There is one row for each combination of {_e(_join([_label(c) for c in key]))}."

    rows = "".join(
        f'<tr><th scope="row">{_e(_label(c))}<code>{_e(c.name)}</code></th>'
        f"<td>{_type(c)}{_flags(c, len(key))}</td><td>{_e(_meaning(c))}</td></tr>"
        for c in columns
    )
    return f"""
<section class="card" id="{table.name}">
  <div class="card-head">
    <h3>{_e(_title(table))}</h3>
    <span class="tag{' data' if section.data else ''}">{_e('Data table' if section.data else section.title)}</span>
    <code class="tech">{_e(table.name)}</code>
  </div>
  <p class="card-desc">{_e(table.comment or '')}</p>
  <div class="scroll" role="region" aria-label="{_e(_title(table))}: columns and an example row" tabindex="0">
    <table class="sheet">
      <thead><tr>{headings}</tr><tr class="types">{types}</tr></thead>
      <tbody><tr class="example">{example}</tr></tbody>
    </table>
  </div>
  <p class="note">The shaded row is an example of what each column holds, not real data.{one_row_per}</p>
  <table class="columns">
    <thead><tr><th scope="col">Column</th><th scope="col">Holds</th><th scope="col">What it means</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <a class="top" href="#top">Back to the list of tables</a>
</section>"""


def _flags(column: sa.Column, key_size: int) -> str:
    flags = []
    if column.primary_key and key_size == 1:
        flags.append(("Unique ID", ""))
    elif not column.nullable and column.identity is None:
        flags.append(("Required", ""))
    if column.identity is not None:
        flags.append(("Numbered automatically", ""))
    if column.unique:
        flags.append(("No duplicates", ""))
    if column.server_default is not None and column.identity is None:
        text = getattr(column.server_default.arg, "text", str(column.server_default.arg))
        flags.append((DEFAULTS.get(text, f"Default: {text}"), ""))
    for fk in column.foreign_keys:
        target = fk.column.table
        style = " catchment" if fk.target_fullname == CATCHMENT_REFERENCE else ""
        flags.append((f'Links to <a href="#{target.name}">{_e(_title(target))}</a>', style))
    return "".join(f'<span class="flag{style}">{text}</span>' for text, style in flags)


def _meaning(column: sa.Column) -> str:
    if column.comment:
        return column.comment
    if _is_catchment_id(column) and column.foreign_keys:
        return "The catchment this row belongs to"
    return ""


def _catchment_class(column: sa.Column) -> str:
    return ' class="catchment"' if _is_catchment_id(column) else ""


def _is_catchment_id(column: sa.Column) -> bool:
    return f"{column.table.name}.{column.name}" == CATCHMENT_REFERENCE or any(
        fk.target_fullname == CATCHMENT_REFERENCE for fk in column.foreign_keys
    )


def _type(column: sa.Column) -> str:
    return _type_label(column.type)


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


def _first_sentence(text: str | None) -> str:
    if not text:
        return ""
    first, dot, _ = text.partition(". ")
    return first + "." if dot else text


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _e(text: str) -> str:
    return html.escape(text, quote=True)
