"""Build the data map page from the master schema file.

The page is plain HTML and CSS with no scripts or outside files, so it can be
opened straight from disk or hosted anywhere as a single file.
"""

from __future__ import annotations

import datetime
import html
from pathlib import Path
from string import Template

import sqlalchemy as sa
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
WORDS = {"id": "ID", "ea": "EA", "url": "URL", "ha": "(ha)", "km": "(km)"}


def build(schema: Schema | None = None, out_dir: Path = SITE_DIR) -> Path:
    """Write the page to out_dir/index.html and return its path."""
    schema = schema or load_schema()
    tables = list(schema.metadata.tables.values())
    core = [t for t in tables if t.name not in schema.data_tables]
    data = [t for t in tables if t.name in schema.data_tables]
    today = datetime.date.today()

    page = Template((HERE / "page.html").read_text(encoding="utf-8")).substitute(
        tiles=_tiles("Core tables", "Catchments, locations and the list of datasets.", core, data_table=False)
        + _tiles("Data tables", "One table per dataset.", data, data_table=True),
        tables="\n".join(_card(t, t.name in schema.data_tables) for t in core + data),
        generated=f"{today.day} {today:%B %Y}",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def _tiles(heading: str, note: str, tables: list[sa.Table], data_table: bool) -> str:
    if not tables:
        return ""
    tiles = "".join(
        f'<a class="tile{" data" if data_table else ""}" href="#{t.name}">'
        f'<span class="tile-title">{_e(_title(t))}</span>'
        f'<span class="tile-desc">{_e(_first_sentence(t.comment))}</span>'
        f'<span class="tile-meta">{len(t.columns)} columns</span></a>'
        for t in tables
    )
    return f'<section class="group"><h2>{heading}</h2><p class="group-note">{note}</p><div class="tiles">{tiles}</div></section>'


def _card(table: sa.Table, data_table: bool) -> str:
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
    <span class="tag{' data' if data_table else ''}">{'Data table' if data_table else 'Core table'}</span>
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
    t = column.type
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
