"""Import storm overflow spills from the EA's storm overflow annual returns
(Event Duration Monitoring), for every catchment in the catchments table.

Each year's return is one download covering every water company: a sheet per
company, with a row per storm overflow. Each overflow names the WFD waterbody it
discharges into, which ties it to a catchment. Overflows into waterbodies that
aren't imported, or with no waterbody ID (mostly into estuaries and the sea),
are left out. The table is only ever filled from here, so each import replaces
all its rows.
"""

from __future__ import annotations

import datetime
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
from openpyxl import load_workbook

from catalyst.db import Schema

from .common import ImportProblem, replace_rows, run_folder
from .ea_api import EAClient, EAError, EANotFound

TABLE = "storm_overflows"
FIRST_YEAR = 2021  # the earliest return this has been checked against
WORKBOOK = "all water and sewerage companies.xlsx"  # the end of the main file's name in each .zip
WATERBODY_RE = re.compile(r"^GB\d{12}$")

# The return's columns, by the first line of their heading -> the table's
# columns. The columns move between years, so they're found by their headings.
COLUMNS = {
    "Unique ID": "unique_id",  # from 2023 only
    "Water Company Name": "company",
    "EA Permit Reference": "permit_reference",
    "Activity Reference on Permit": "activity_reference",
    "Storm Discharge Asset Type": "asset_type",
    "Outlet Discharge NGR": "grid_reference",
    "Receiving Water / Environment (common name)": "receiving_water",
}
# Headings that change between years and companies, found by how they start:
# "WFD Waterbody ID (Cycle 2)" or "(Cycle 3)", "Total Duration (hrs) ..." or
# "(hh:mm:ss) ...", and "Counted spills using 12-24h count method" or "12-24hr counting method".
STARTS = {"WFD Waterbody ID": "waterbody_id", "Total Duration": "spill_hours", "Counted spills": "spill_count"}
SITE_NAME = "Site Name"  # appears twice: the EA's name, then the water company's, which is kept
REQUIRED = {"waterbody_id", "site_name", "spill_hours", "spill_count", "grid_reference"}
HEADING_ROWS = 10  # the heading row is within this many rows of the top


@dataclass
class Download:
    year: int
    data: bytes  # the .zip, exactly as downloaded


def fetch(client: EAClient, progress: Callable[[int], None] = lambda year: None) -> list[Download]:
    """Every year's return from FIRST_YEAR, until one isn't published yet."""
    downloads = []
    year = FIRST_YEAR
    while True:
        try:
            downloads.append(Download(year, client.storm_overflows(year)))
        except EANotFound:
            break
        except EAError as e:
            raise ImportProblem(f"the {year} return: {e}") from e
        progress(year)
        year += 1
    if not downloads:
        raise ImportProblem(f"the EA has no storm overflow return for {FIRST_YEAR}")
    return downloads


def read(downloads: list[Download], catchment_ids: set[str]) -> list[dict[str, Any]]:
    """The overflows into the imported catchments, a row per overflow per year."""
    return [row for download in downloads for row in read_return(download, catchment_ids)]


def read_return(download: Download, catchment_ids: set[str]) -> list[dict[str, Any]]:
    archive = zipfile.ZipFile(io.BytesIO(download.data))
    names = [name for name in archive.namelist() if name.endswith(WORKBOOK)]
    if len(names) != 1:
        raise ImportProblem(f"the {download.year} return has no '... {WORKBOOK}' file. The EA may have changed it.")
    workbook = load_workbook(io.BytesIO(archive.read(names[0])), read_only=True, data_only=True)
    rows = []
    for sheet in workbook.worksheets:
        if sheet.title.startswith("All "):
            continue  # every company again, in one sheet (from 2025)
        rows += _read_sheet(sheet, download.year, catchment_ids)
    workbook.close()
    return rows


def _read_sheet(sheet, year: int, catchment_ids: set[str]) -> list[dict[str, Any]]:
    where = f"the {year} return's '{sheet.title}' sheet"
    lines = sheet.iter_rows(values_only=True)
    for number, cells in enumerate(lines, start=1):
        headings = [str(c).split("\n")[0].strip() if c is not None else "" for c in cells]
        if SITE_NAME in headings:
            break
        if number >= HEADING_ROWS:
            raise ImportProblem(f"{where} has no heading row with '{SITE_NAME}'. The EA may have changed it.")
    else:
        return []

    positions: dict[str, int] = {}
    site_names = [i for i, heading in enumerate(headings) if heading == SITE_NAME]
    if len(site_names) == 2:
        positions["site_name"] = site_names[1]
    for i, heading in enumerate(headings):
        column = COLUMNS.get(heading) or next((c for start, c in STARTS.items() if heading.startswith(start)), None)
        if column:
            positions.setdefault(column, i)
    missing = REQUIRED - set(positions)
    if missing:
        raise ImportProblem(f"{where} has no column for {', '.join(sorted(missing))}. The EA may have changed it.")

    rows = []
    for cells in lines:
        def value(column: str) -> Any:
            i = positions.get(column)
            return cells[i] if i is not None and i < len(cells) else None

        waterbody_id = _text(value("waterbody_id"))
        if waterbody_id not in catchment_ids or not WATERBODY_RE.match(waterbody_id):
            continue
        grid_reference = _text(value("grid_reference"))
        easting, northing = grid_to_numbers(grid_reference) if grid_reference else (None, None)
        rows.append({
            "catchment_id": waterbody_id,
            "year": year,
            "company": _text(value("company")),
            "site_name": _text(value("site_name")),
            "unique_id": _text(value("unique_id")),
            "permit_reference": _text(value("permit_reference")),
            "activity_reference": _text(value("activity_reference")),
            "asset_type": _text(value("asset_type")),
            "receiving_water": _text(value("receiving_water")),
            "grid_reference": grid_reference,
            "easting": easting,
            "northing": northing,
            "spill_hours": hours(value("spill_hours")),
            "spill_count": _whole(value("spill_count")),
        })
    return rows


def hours(value: Any) -> float | None:
    """A spill duration in hours: a number of hours (to 2023), or an hh:mm:ss cell (from 2024).
    Blanks and '#N/A' mean there's no figure (e.g. no monitor yet), not zero."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime.timedelta):
        return value.total_seconds() / 3600
    if isinstance(value, datetime.datetime):  # over 24 hours, stored as days since Excel's start date
        return (value - datetime.datetime(1899, 12, 30)).total_seconds() / 3600
    if isinstance(value, datetime.time):
        return value.hour + value.minute / 60 + value.second / 3600
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def grid_to_numbers(grid_reference: str) -> tuple[int, int] | tuple[None, None]:
    """An Ordnance Survey grid reference (e.g. 'SS 5916 2017') as an easting and northing in metres.
    (None, None) if it isn't one."""
    match = re.fullmatch(r"([HJNOST][A-HJ-Z])(\d*)", grid_reference.replace(" ", "").upper())
    if not match or len(match.group(2)) % 2 or not 2 <= len(match.group(2)) <= 10:
        return None, None
    letters, digits = match.groups()
    first, second = (ord(letter) - ord("A") - (letter > "I") for letter in letters)  # there's no I
    east = ((first - 2) % 5) * 5 + second % 5  # 100 km squares
    north = (19 - (first // 5) * 5) - second // 5
    half = len(digits) // 2
    scale = 10 ** (5 - half)
    return east * 100_000 + int(digits[:half]) * scale, north * 100_000 + int(digits[half:]) * scale


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _whole(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def save(conn: sa.Connection, schema: Schema, rows: list[dict[str, Any]]) -> None:
    """Replace every row with the new ones, and work out each outlet's latitude and longitude."""
    table = schema.metadata.tables[TABLE]
    replace_rows(conn, table, rows)
    point = sa.func.ST_Transform(sa.func.ST_SetSRID(sa.func.ST_MakePoint(table.c.easting, table.c.northing), 27700), 4326)
    conn.execute(table.update().where(table.c.easting.is_not(None)).values(
        longitude=sa.func.ST_X(point), latitude=sa.func.ST_Y(point),
    ))


def save_raw_files(downloads: list[Download], raw_dir: Path) -> Path:
    """Keep exactly what was downloaded, in a folder for this import run."""
    run_dir = run_folder(raw_dir, TABLE)
    for download in downloads:
        (run_dir / f"EDM_{download.year}_Storm_Overflow_Annual_Return.zip").write_bytes(download.data)
    return run_dir
