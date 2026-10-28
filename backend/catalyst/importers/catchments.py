"""Import catchments from the EA's Catchment Data Explorer.

Everything in the catchments and catchment_connections tables comes from here,
so they never mix EA data with anything entered by hand:

- the waterbody's shapefile (API): its details, catchment boundary and river line;
- the waterbody's web page: its river length and upstream/downstream waterbodies,
  which the API doesn't provide;
- the area, calculated from the boundary (it matches the EA's own figure).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

import shapefile
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from catalyst.db import Schema

from .ea_api import EAClient, EAError

BNG = 27700  # British National Grid, used by the EA's shapefiles
WGS84 = 4326  # latitude/longitude, used by web maps
ID_RE = re.compile(r"^GB[0-9A-Z]{6,20}$")
LIST_EXAMPLE = '{"catchments": ["GB108050008080", "GB108050008100"]}'

# Shapefile field -> catchments column
DETAIL_FIELDS = {
    "WB_NAME": "name",
    "WB_CAT": "waterbody_type",
    "RBD_ID": "river_basin_district_id",
    "RBD_NAME": "river_basin_district",
    "MANCAT_ID": "management_catchment_id",
    "MNCAT_NAME": "management_catchment",
    "OPCAT_ID": "operational_catchment_id",
    "OPCAT_NAME": "operational_catchment",
    "hydromorph": "hydromorphological_designation",
}
ID_COLUMNS = {"river_basin_district_id", "management_catchment_id", "operational_catchment_id"}


class ImportProblem(Exception):
    """The input, or something downloaded, isn't what the importer expects."""


@dataclass
class Catchment:
    id: str
    details: dict  # catchments column -> value, from the shapefile
    river_length_km: float
    boundary: dict  # GeoJSON geometry, in British National Grid
    river_line: dict  # GeoJSON geometry, in British National Grid
    upstream: list[tuple[str, str]]  # (waterbody ID, name)
    downstream: list[tuple[str, str]]
    raw_files: dict[str, bytes]  # exactly as downloaded, kept for the record

    @property
    def name(self) -> str:
        return self.details["name"]


def read_catchment_list(path: Path) -> list[str]:
    """Read the JSON file listing which catchments to import."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ImportProblem(f"{path} doesn't exist") from None
    except json.JSONDecodeError as e:
        raise ImportProblem(f"{path} is not valid JSON: {e}") from None
    if (
        not isinstance(data, dict)
        or not set(data) <= {"description", "catchments"}
        or not isinstance(data.get("catchments"), list)
        or not data["catchments"]
    ):
        raise ImportProblem(f"{path} should look like {LIST_EXAMPLE}")
    ids = data["catchments"]
    bad = [str(i) for i in ids if not isinstance(i, str) or not ID_RE.match(i)]
    if bad:
        raise ImportProblem(f"{path}: these aren't catchment IDs: {', '.join(bad)}")
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise ImportProblem(f"{path}: listed more than once: {', '.join(repeated)}")
    return ids


def fetch(
    ids: list[str],
    client: EAClient,
    progress: Callable[[Catchment], None] = lambda c: None,
) -> tuple[list[Catchment], list[str]]:
    """Download and check every catchment. Returns (catchments, problems)."""
    found, problems = [], []
    for waterbody_id in ids:
        try:
            catchment = fetch_one(waterbody_id, client)
        except (EAError, ImportProblem) as e:
            problems.append(f"{waterbody_id}: {e}")
            continue
        found.append(catchment)
        progress(catchment)
    return found, problems


def fetch_one(waterbody_id: str, client: EAClient) -> Catchment:
    shapefile_zip = client.waterbody_shapefile(waterbody_id)
    page = client.waterbody_page(waterbody_id)
    details, boundary, river_line = read_shapefile(waterbody_id, shapefile_zip)
    length_km, upstream, downstream = read_page(waterbody_id, page)
    return Catchment(
        id=waterbody_id,
        details=details,
        river_length_km=length_km,
        boundary=boundary,
        river_line=river_line,
        upstream=upstream,
        downstream=downstream,
        raw_files={"shapefile.zip": shapefile_zip, "page.html": page.encode("utf-8")},
    )


# --- The shapefile ---------------------------------------------------------

def read_shapefile(waterbody_id: str, data: bytes) -> tuple[dict, dict, dict]:
    """Return (details, boundary, river line) from the EA's shapefile .zip."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    layers = [_read_layer(archive, name[:-4], waterbody_id) for name in archive.namelist() if name.endswith(".shp")]
    polygons = [layer for layer in layers if layer["type"] == shapefile.POLYGON]
    lines = [layer for layer in layers if layer["type"] == shapefile.POLYLINE]
    if len(polygons) != 1 or len(lines) != 1:
        raise ImportProblem(
            "the EA's shapefile doesn't have exactly one catchment boundary and one river line. "
            "Only river waterbodies can be imported for now."
        )
    record = polygons[0]["record"]
    missing = [f for f in DETAIL_FIELDS if record.get(f) in (None, "")]
    if missing:
        raise ImportProblem(f"the EA's shapefile is missing {', '.join(missing)}")
    details = {
        column: int(record[field]) if column in ID_COLUMNS else str(record[field]).strip()
        for field, column in DETAIL_FIELDS.items()
    }
    return details, polygons[0]["geometry"], lines[0]["geometry"]


def _read_layer(archive: zipfile.ZipFile, base: str, waterbody_id: str) -> dict:
    files = set(archive.namelist())
    prj = archive.read(f"{base}.prj").decode("latin-1") if f"{base}.prj" in files else ""
    if "British_National_Grid" not in prj and "British National Grid" not in prj:
        raise ImportProblem(f"the EA's shapefile {base} isn't in British National Grid")
    # The .cst file says how the text is encoded.
    encoding = archive.read(f"{base}.cst").decode("ascii").strip() if f"{base}.cst" in files else "latin-1"
    reader = shapefile.Reader(
        shp=io.BytesIO(archive.read(f"{base}.shp")),
        shx=io.BytesIO(archive.read(f"{base}.shx")),
        dbf=io.BytesIO(archive.read(f"{base}.dbf")),
        encoding=encoding,
    )
    rows = reader.shapeRecords()
    if len(rows) != 1:
        raise ImportProblem(f"the EA's shapefile {base} has {len(rows)} rows, expected 1")
    record = rows[0].record.as_dict()
    if record.get("WB_ID") != waterbody_id:
        raise ImportProblem(f"the EA's shapefile is for {record.get('WB_ID')}, not {waterbody_id}")
    return {"type": reader.shapeType, "record": record, "geometry": rows[0].shape.__geo_interface__}


# --- The web page ----------------------------------------------------------

def read_page(waterbody_id: str, html: str) -> tuple[float, list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (river length in km, upstream, downstream) from the waterbody's web page."""
    reader = _PageReader()
    reader.feed(html)
    changed = "The EA may have changed the page, so the importer needs updating."
    if reader.attributes.get("Water Body ID") != [waterbody_id]:
        raise ImportProblem(f"the EA's waterbody page doesn't show the ID {waterbody_id}. {changed}")
    lengths = reader.attributes.get("Length")
    if not lengths:
        raise ImportProblem(f"the EA's waterbody page has no 'Length'. {changed}")
    match = re.fullmatch(r"([\d.,]+)\s*(km|m)", lengths[0])
    if not match:
        raise ImportProblem(f"the EA's waterbody page has a length of '{lengths[0]}', which isn't in km or m")
    length = float(match.group(1).replace(",", ""))
    if match.group(2) == "m":
        length /= 1000
    if reader.sections != {"upstream", "downstream"}:
        raise ImportProblem(f"the EA's waterbody page has no upstream/downstream lists. {changed}")
    return length, _unique(reader.links["upstream"]), _unique(reader.links["downstream"])


class _PageReader(HTMLParser):
    """Picks out the Attributes list and the upstream/downstream links."""

    SECTIONS = {"upstream-water-bodies": "upstream", "downstream-water-bodies": "downstream"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes: dict[str, list[str]] = {}  # label -> values (a label can appear twice)
        self.links: dict[str, list[tuple[str, str]]] = {"upstream": [], "downstream": []}
        self.sections: set[str] = set()
        self._in_attributes = False
        self._span = None  # "label" or "value" while inside an attribute span
        self._label = None
        self._section = None  # "upstream" or "downstream" while inside that list
        self._link_id = None
        self._text = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "ul" and "attribute-grid" in classes:
            self._in_attributes = True
        elif tag == "span" and self._in_attributes:
            self._span = "label" if "font-weight-bold" in classes else "value" if "text-monospace" in classes else None
            self._text = ""
        elif tag == "h2":
            self._section = self.SECTIONS.get(attrs.get("id"))
            if self._section:
                self.sections.add(self._section)
        elif tag == "footer":
            self._section = None
        elif tag == "a" and self._section:
            match = re.search(r"/WaterBody/(GB\w+)$", attrs.get("href") or "")
            self._link_id = match.group(1) if match else None
            self._text = ""

    def handle_endtag(self, tag):
        if tag == "ul":
            self._in_attributes = False
        elif tag == "span" and self._span:
            text = " ".join(self._text.split())
            if self._span == "label":
                self._label = text
            elif self._label:
                self.attributes.setdefault(self._label, []).append(text)
                self._label = None
            self._span = None
        elif tag == "a" and self._link_id:
            self.links[self._section].append((self._link_id, " ".join(self._text.split())))
            self._link_id = None

    def handle_data(self, data):
        if self._span or self._link_id:
            self._text += data


def _unique(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return list(dict.fromkeys(links))


# --- Saving ----------------------------------------------------------------

def existing_ids(conn: sa.Connection, schema: Schema, ids: list[str]) -> set[str]:
    table = schema.metadata.tables["catchments"]
    return set(conn.scalars(sa.select(table.c.id).where(table.c.id.in_(ids))))


def save(conn: sa.Connection, schema: Schema, catchments: list[Catchment]) -> None:
    """Add or update the catchments, and replace their upstream/downstream links."""
    table = schema.metadata.tables["catchments"]
    connections = schema.metadata.tables["catchment_connections"]
    for c in catchments:
        boundary = sa.func.ST_SetSRID(sa.func.ST_GeomFromGeoJSON(json.dumps(c.boundary)), BNG)
        river_line = sa.func.ST_SetSRID(sa.func.ST_GeomFromGeoJSON(json.dumps(c.river_line)), BNG)
        values = {
            "id": c.id,
            **c.details,
            "river_length_km": c.river_length_km,
            "area_ha": sa.func.ST_Area(boundary) / 10_000,  # square metres in British National Grid
            "boundary": sa.func.ST_Multi(sa.func.ST_Transform(boundary, WGS84)),
            "river_line": sa.func.ST_Multi(sa.func.ST_Transform(river_line, WGS84)),
            "imported_at": sa.func.now(),
        }
        statement = insert(table).values(values)
        conn.execute(statement.on_conflict_do_update(
            index_elements=[table.c.id],
            set_={column: statement.excluded[column] for column in values if column != "id"},
        ))

    conn.execute(sa.delete(connections).where(connections.c.catchment_id.in_([c.id for c in catchments])))
    rows = [
        {"catchment_id": c.id, "direction": direction, "connected_id": other_id, "connected_name": other_name}
        for c in catchments
        for direction, links in (("upstream", c.upstream), ("downstream", c.downstream))
        for other_id, other_name in links
    ]
    if rows:
        conn.execute(sa.insert(connections), rows)


def save_raw_files(catchments: list[Catchment], raw_dir: Path) -> Path:
    """Keep exactly what was downloaded, in a folder for this import run."""
    run_dir = Path(raw_dir) / "catchments" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    for c in catchments:
        folder = run_dir / c.id
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in c.raw_files.items():
            (folder / name).write_bytes(data)
    return run_dir
