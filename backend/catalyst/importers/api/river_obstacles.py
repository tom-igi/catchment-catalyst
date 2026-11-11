"""Import river obstacles (weirs, culverts, fords, sluices, ...) from River
Obstacles, the national map of them by the EA and The Rivers Trust, for every
catchment in the catchments table.

Downloads every obstacle in the box around the catchments, and keeps those that
are inside one of them. The table is only ever filled from here, so each import
replaces all its rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa

from catalyst.db import Schema

from .common import ImportProblem, replace_rows, run_folder
from .ea_api import RIVER_OBSTACLES_PAGE, EAClient, EAError

TABLE = "river_obstacles"
# The service's field -> the table's column
FIELDS = {
    "globalid": "id",
    "ea_obstructid": "ea_id",
    "site_name": "site_name",
    "obstacle_type": "obstacle_type",
    "origin": "origin",
    "status": "status",
}


def box(conn: sa.Connection, schema: Schema) -> tuple[float, float, float, float] | None:
    """The box around every catchment, in British National Grid: (west, south, east, north)."""
    table = schema.metadata.tables["catchments"]
    extent = sa.func.ST_Extent(sa.func.ST_Transform(table.c.boundary, 27700))
    row = conn.execute(sa.select(
        sa.func.ST_XMin(extent), sa.func.ST_YMin(extent), sa.func.ST_XMax(extent), sa.func.ST_YMax(extent),
    )).one()
    return None if row[0] is None else tuple(row)


def fetch(client: EAClient, area: tuple[float, float, float, float], progress: Callable[[int], None] = lambda n: None) -> list[dict]:
    """Every page of obstacles in the box, as downloaded."""
    pages = []
    while True:
        try:
            page = client.river_obstacles(area, offset=len(pages) * RIVER_OBSTACLES_PAGE)
        except EAError as e:
            raise ImportProblem(f"River Obstacles: {e}") from e
        pages.append(page)
        progress(sum(len(p.get("features", [])) for p in pages))
        if len(page.get("features", [])) < RIVER_OBSTACLES_PAGE and not page.get("properties", {}).get("exceededTransferLimit"):
            return pages


def read(pages: list[dict]) -> list[dict[str, Any]]:
    """The obstacles, each with its latitude and longitude."""
    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        for feature in page.get("features", []):
            properties = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            missing = [f for f in FIELDS if f not in properties]
            if missing:
                raise ImportProblem(f"River Obstacles sent no {', '.join(missing)}. The service may have changed.")
            if geometry.get("type") != "Point" or not properties["globalid"]:
                continue
            row = {column: _clean(properties[field]) for field, column in FIELDS.items()}
            row["longitude"], row["latitude"] = geometry["coordinates"][:2]
            found[row["id"]] = row
    return list(found.values())


def place(conn: sa.Connection, schema: Schema, obstacles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The obstacles inside a catchment, each with that catchment's ID."""
    if not obstacles:
        return []
    table = schema.metadata.tables["catchments"]
    points = sa.func.unnest(
        sa.cast([o["id"] for o in obstacles], sa.ARRAY(sa.Text)),
        sa.cast([o["longitude"] for o in obstacles], sa.ARRAY(sa.Float)),
        sa.cast([o["latitude"] for o in obstacles], sa.ARRAY(sa.Float)),
    ).table_valued("id", "lon", "lat").render_derived(name="points")
    inside = sa.func.ST_Contains(table.c.boundary, sa.func.ST_SetSRID(sa.func.ST_MakePoint(points.c.lon, points.c.lat), 4326))
    catchment_of = dict(conn.execute(sa.select(points.c.id, table.c.id).join(table, inside)).all())
    return [{**o, "catchment_id": catchment_of[o["id"]]} for o in obstacles if o["id"] in catchment_of]


def save(conn: sa.Connection, schema: Schema, rows: list[dict[str, Any]]) -> None:
    """Replace every row with the new ones."""
    replace_rows(conn, schema.metadata.tables[TABLE], rows)


def save_raw_files(pages: list[dict], raw_dir: Path) -> Path:
    """Keep what was downloaded, in a folder for this import run."""
    run_dir = run_folder(raw_dir, TABLE)
    for number, page in enumerate(pages, start=1):
        (run_dir / f"page-{number}.geojson").write_text(json.dumps(page), encoding="utf-8")
    return run_dir


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip() or None
    return value
