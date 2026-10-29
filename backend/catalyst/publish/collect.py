"""Collect everything a location's dashboard shows, from the database.

This half of the publish step knows nothing about web pages: it returns plain
data (a Location), which site.py turns into pages. A different kind of
dashboard could use the same data.

Every data table is collected the same way, so a new table's data is ready
for the pages with no code to write here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from geoalchemy2 import Geometry

from catalyst.db import Schema
from catalyst.db.schema import CATCHMENT_COLUMN

# Outlines are simplified for the web: corners closer than about 10 m are
# dropped, and coordinates are rounded to about 1 m.
SIMPLIFY_DEGREES = 0.0001
COORDINATE_DECIMALS = 5
WORDS = {"id": "ID", "ids": "IDs", "ea": "EA", "ha": "(ha)", "km": "(km)", "url": "URL"}


class PublishProblem(Exception):
    """The data can't be published as it is."""


@dataclass
class Column:
    name: str
    label: str  # e.g. "Area (ha)"
    kind: str  # "number", "date", "yes/no" or "text": used for sorting and lining up


@dataclass
class Dataset:
    table: str
    title: str
    description: str | None
    columns: list[Column]  # every column except catchment_id
    rows: dict[str, list[dict[str, Any]]]  # catchment ID -> its rows
    info: dict[str, Any] | None  # its row in the datasets table (source, caveats), for the "i" buttons

    def rows_for(self, catchment_id: str) -> list[dict[str, Any]]:
        return self.rows.get(catchment_id, [])


@dataclass
class Location:
    name: str
    slug: str  # its folder and web address, e.g. north-devon
    catchments: list[dict[str, Any]]  # its catchments' details (not their shapes), by name
    names: dict[str, str]  # catchment ID -> name, including upstream/downstream ones outside the location
    datasets: list[Dataset]
    map: dict  # GeoJSON: each catchment's outline and river, for the maps

    def catchment_ids(self) -> set[str]:
        return {c["id"] for c in self.catchments}

    def dataset(self, table: str) -> Dataset | None:
        """The data table's dataset, or None if there's no such table (yet)."""
        return next((d for d in self.datasets if d.table == table), None)


def slug(name: str) -> str:
    """A location's name as a web address, e.g. 'North Devon' -> 'north-devon'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def locations(conn: sa.Connection, schema: Schema) -> list[sa.Row]:
    table = schema.metadata.tables["locations"]
    rows = conn.execute(sa.select(table).order_by(table.c.name)).all()
    seen: dict[str, str] = {}
    for row in rows:
        if not slug(row.name):
            raise PublishProblem(f"The location '{row.name}' needs letters or numbers in its name, for its web address.")
        if slug(row.name) in seen:
            raise PublishProblem(f"The locations '{seen[slug(row.name)]}' and '{row.name}' would have the same web address.")
        seen[slug(row.name)] = row.name
    return rows


def collect(conn: sa.Connection, schema: Schema, location: sa.Row) -> Location:
    ids = list(location.catchment_ids)
    catchments = _catchments(conn, schema, ids)
    missing = sorted(set(ids) - {c["id"] for c in catchments})
    if missing:
        raise PublishProblem(
            f"{location.name} lists catchment IDs that aren't in the catchments table: {', '.join(missing)}. "
            "Import them first, or take them off the location."
        )
    linked = {i for c in catchments for i in (c["upstream_ids"] or []) + (c["downstream_ids"] or [])}
    info = _info(conn, schema)
    return Location(
        name=location.name,
        slug=slug(location.name),
        catchments=catchments,
        names=_names(conn, schema, set(ids) | linked),
        datasets=[_dataset(conn, schema.metadata.tables[name], ids, info.get(name)) for name in schema.data_tables],
        map=_map(conn, schema, ids),
    )


def _catchments(conn: sa.Connection, schema: Schema, ids: list[str]) -> list[dict[str, Any]]:
    table = schema.metadata.tables["catchments"]
    details = [c for c in table.columns if not isinstance(c.type, Geometry)]
    rows = conn.execute(sa.select(*details).where(table.c.id.in_(ids)).order_by(table.c.name, table.c.id))
    return [dict(row._mapping) for row in rows]


def _names(conn: sa.Connection, schema: Schema, ids: set[str]) -> dict[str, str]:
    table = schema.metadata.tables["catchments"]
    return dict(conn.execute(sa.select(table.c.id, table.c.name).where(table.c.id.in_(ids))).all())


def _info(conn: sa.Connection, schema: Schema) -> dict[str, dict[str, Any]]:
    """Each data table's row in the datasets table, by table name."""
    table = schema.metadata.tables["datasets"]
    return {row["table_name"]: dict(row) for row in conn.execute(sa.select(table)).mappings()}


def _dataset(conn: sa.Connection, table: sa.Table, ids: list[str], info: dict[str, Any] | None) -> Dataset:
    catchment_id = table.c[CATCHMENT_COLUMN]
    shown = [c for c in table.columns if c.name != CATCHMENT_COLUMN]
    rows: dict[str, list[dict[str, Any]]] = {}
    query = sa.select(table).where(catchment_id.in_(ids)).order_by(*table.primary_key.columns)
    for row in conn.execute(query).mappings():
        rows.setdefault(row[CATCHMENT_COLUMN], []).append({c.name: row[c.name] for c in shown})
    return Dataset(
        table=table.name,
        title=table.info.get("title") or table.name.replace("_", " ").capitalize(),
        description=table.comment,
        columns=[Column(c.name, _label(c.name), _kind(c)) for c in shown],
        rows=rows,
        info=info,
    )


def _map(conn: sa.Connection, schema: Schema, ids: list[str]) -> dict:
    """The catchments' outlines and rivers, as GeoJSON, simplified for the web."""
    table = schema.metadata.tables["catchments"]

    def geojson(column):
        return sa.func.ST_AsGeoJSON(sa.func.ST_SimplifyPreserveTopology(column, SIMPLIFY_DEGREES), COORDINATE_DECIMALS)

    rows = conn.execute(
        sa.select(table.c.id, table.c.name, geojson(table.c.boundary).label("outline"), geojson(table.c.river_line).label("river"))
        .where(table.c.id.in_(ids)).order_by(table.c.id)
    )
    features = []
    for row in rows:
        for layer, shape in (("catchment", row.outline), ("river", row.river)):
            if shape:
                features.append({
                    "type": "Feature",
                    "properties": {"id": row.id, "name": row.name, "layer": layer},
                    "geometry": json.loads(shape),
                })
    return {"type": "FeatureCollection", "features": features}


def _label(name: str) -> str:
    label = " ".join(WORDS.get(word, word) for word in name.split("_"))
    return label[0].upper() + label[1:]


def _kind(column: sa.Column) -> str:
    if isinstance(column.type, sa.Boolean):
        return "yes/no"
    if isinstance(column.type, (sa.Integer, sa.Numeric)):
        return "number"
    if isinstance(column.type, (sa.Date, sa.DateTime)):
        return "date"
    return "text"
