"""Import postcodes from Ordnance Survey's Code-Point Open: the centre point of
every postcode in Great Britain. Each postcode inside a catchment is kept with
that catchment's ID, for the Waterbody Dashboard's postcode search.

Downloads the whole of Great Britain (one .zip, about 15 MB), keeps the
postcodes in the box around the catchments, then those inside a catchment. A
postcode is placed by its centre, so one that crosses a boundary goes to the
catchment its centre is in. The table is only ever filled from here, so each
import replaces all its rows.

Code-Point Open is free to use under the OS OpenData licence, which asks for a
credit line wherever it's used (the dashboard's footer).
"""

from __future__ import annotations

import csv
import io
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from catalyst.db import Schema

from .common import ImportProblem, replace_rows, run_folder

TABLE = "postcodes"
# The latest Code-Point Open, as CSV files (one per postcode area, e.g. ex.csv):
# https://osdatahub.os.uk/downloads/open/CodePointOpen
DOWNLOAD_URL = "https://api.os.uk/downloads/v1/products/CodePointOpen/downloads?area=GB&format=CSV&redirect"
FILE_NAME = "codepo_gb.zip"
USER_AGENT = "postcode-importer"
# The data files have no headings; this file in the download names their columns.
HEADINGS_FILE = "Doc/Code-Point_Open_Column_Headers.csv"
COLUMNS = {"postcode": "Postcode", "quality": "Positional_quality_indicator", "easting": "Eastings", "northing": "Northings"}
NO_LOCATION = "90"  # the positional quality of a postcode Code-Point Open has no point for


def fetch(retries: int = 3, timeout: float = 300, pause: float = 3.0) -> bytes:
    """The latest Code-Point Open (.zip), as downloaded."""
    problem = ""
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(pause * attempt)
        try:
            request = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as e:
            problem = f"Ordnance Survey returned error {e.code}"
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            problem = f"could not reach Ordnance Survey ({getattr(e, 'reason', e)})"
            continue
        if zipfile.is_zipfile(io.BytesIO(data)):
            return data
        problem = "Ordnance Survey sent something other than a .zip file"
    raise ImportProblem(f"Code-Point Open: {problem}, after {retries} tries ({DOWNLOAD_URL})")


def read(download: bytes, area: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """The postcodes in the box (British National Grid: west, south, east, north), each
    with its centre as an easting and northing."""
    west, south, east, north = area
    try:
        files = zipfile.ZipFile(io.BytesIO(download))
    except zipfile.BadZipFile as e:
        raise ImportProblem(f"Code-Point Open isn't a readable .zip file: {e}") from e
    with files:
        column = _columns(files)
        data = sorted(n for n in files.namelist() if re.fullmatch(r"Data/CSV/[a-z]+\.csv", n, flags=re.IGNORECASE))
        if not data:
            raise ImportProblem("Code-Point Open has no postcode files (Data/CSV/*.csv). The download may have changed.")
        found = []
        for name in data:
            with files.open(name) as raw:
                for number, record in enumerate(csv.reader(io.TextIOWrapper(raw, encoding="utf-8")), start=1):
                    if not record:
                        continue
                    try:
                        if record[column["quality"]].strip() == NO_LOCATION:
                            continue
                        easting, northing = float(record[column["easting"]]), float(record[column["northing"]])
                        if not (west <= easting <= east and south <= northing <= north):
                            continue
                        found.append({"postcode": tidy(record[column["postcode"]]), "easting": easting, "northing": northing})
                    except (IndexError, ValueError):
                        raise ImportProblem(f"Code-Point Open's {name}, line {number}, isn't a postcode and its point: {record}") from None
    return found


def tidy(postcode: str) -> str:
    """A postcode in capitals, with one space before the last three characters (e.g. 'ex363aa' -> 'EX36 3AA')."""
    squashed = re.sub(r"\s+", "", postcode).upper()
    if not re.fullmatch(r"[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}", squashed):
        raise ValueError(f"not a postcode: {postcode!r}")
    return f"{squashed[:-3]} {squashed[-3:]}"


def place(conn: sa.Connection, schema: Schema, postcodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The postcodes whose centre is inside a catchment, each with that catchment's ID and its
    centre as a latitude and longitude. A centre on two outlines that overlap goes to the first
    catchment by ID, so each import gives the same answer."""
    if not postcodes:
        return []
    table = schema.metadata.tables["catchments"]
    points = sa.func.unnest(
        sa.cast([p["postcode"] for p in postcodes], sa.ARRAY(sa.Text)),
        sa.cast([float(p["easting"]) for p in postcodes], sa.ARRAY(sa.Float)),
        sa.cast([float(p["northing"]) for p in postcodes], sa.ARRAY(sa.Float)),
    ).table_valued("postcode", "easting", "northing").render_derived(name="points")
    # Into latitude and longitude, like the outlines, so their spatial index is used.
    centres = sa.select(
        points.c.postcode,
        sa.func.ST_Transform(sa.func.ST_SetSRID(sa.func.ST_MakePoint(points.c.easting, points.c.northing), 27700), 4326).label("centre"),
    ).subquery("centres")
    rows = conn.execute(
        sa.select(centres.c.postcode, table.c.id, sa.func.ST_Y(centres.c.centre), sa.func.ST_X(centres.c.centre))
        .join(table, sa.func.ST_Contains(table.c.boundary, centres.c.centre))
        .order_by(centres.c.postcode, table.c.id)
    )
    placed: dict[str, dict[str, Any]] = {}
    for postcode, catchment_id, latitude, longitude in rows:
        placed.setdefault(postcode, {
            "postcode": postcode, "catchment_id": catchment_id,
            "latitude": round(latitude, 6), "longitude": round(longitude, 6),
        })
    return list(placed.values())


def save(conn: sa.Connection, schema: Schema, rows: list[dict[str, Any]]) -> None:
    """Replace every row with the new ones."""
    replace_rows(conn, schema.metadata.tables[TABLE], rows)


def save_raw_files(download: bytes, raw_dir: Path) -> Path:
    """Keep what was downloaded, in a folder for this import run."""
    run_dir = run_folder(raw_dir, TABLE)
    (run_dir / FILE_NAME).write_bytes(download)
    return run_dir


def _columns(files: zipfile.ZipFile) -> dict[str, int]:
    """Where each column is in the data files, from the headings file."""
    try:
        text = files.read(HEADINGS_FILE).decode("utf-8-sig")
    except KeyError:
        raise ImportProblem(f"Code-Point Open has no {HEADINGS_FILE}. The download may have changed.") from None
    # A row of short names (PC, PQ, ...), then the full ones, which are used here.
    for row in csv.reader(io.StringIO(text)):
        headings = [h.strip() for h in row]
        if all(h in headings for h in COLUMNS.values()):
            return {key: headings.index(heading) for key, heading in COLUMNS.items()}
    raise ImportProblem(
        f"Code-Point Open's {HEADINGS_FILE} doesn't name the columns {', '.join(COLUMNS.values())}. The download may have changed."
    )
