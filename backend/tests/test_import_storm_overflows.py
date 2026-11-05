"""The storm overflows importer.

The EA's real returns are too big to keep here (several MB a year), so these
tests make small ones with the same layout: the 2021 one and the 2024 one,
whose columns differ.
"""

import datetime
import io
import zipfile

import pytest
import sqlalchemy as sa
from openpyxl import Workbook

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, storm_overflows
from catalyst.importers.api.catchments import ImportProblem
from catalyst.importers.api.ea_api import EANotFound

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()
HEADINGS_2021 = [
    "Water Company Name", "Site Name\n(EA Consents Database)", "Site Name\n(WaSC operational)", "EA Permit Reference",
    "WaSC Supplementary Permit Ref.", "Activity Reference on Permit", "Storm Discharge Asset Type",
    "Outlet Discharge NGR", "WFD Waterbody ID (Cycle 2)", "WFD Waterbody Catchment Name (Cycle 2)",
    "Receiving Water / Environment (common name)",
    "Total Duration (hrs) all spills prior to processing through 12-24h count method",
    "Counted spills using 12-24h count method",
]
HEADINGS_2024 = ["Unique ID"] + HEADINGS_2021
HEADINGS_2024[HEADINGS_2024.index("WFD Waterbody ID (Cycle 2)")] = "WFD Waterbody ID (Cycle 3)"
HEADINGS_2024[HEADINGS_2024.index(HEADINGS_2021[11])] = "Total Duration (hh:mm:ss) all spills prior to processing through 12-24h count method"


def overflow(waterbody_id, hours, spills, name="HIGH BICKINGTON STW_SO_HIGH BICKINGTON", unique_id=None):
    row = ["South West Water", "HIGH BICKINGTON STW", name, "202194/CS/01", None, "A2", "Storm tank at WwTW",
           "SS 5916 2017", waterbody_id, "West Okement", "West Okement", hours, spills]
    return ([unique_id] if unique_id else []) + row


def make_return(year, sheets: dict[str, tuple[int, list, list[list]]]) -> storm_overflows.Download:
    """A return for the year: sheet name -> (heading row, headings, rows)."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, (heading_row, headings, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        for _ in range(heading_row - 1):
            sheet.append(["Storm overflow annual return"])
        sheet.append(headings)
        for row in rows:
            sheet.append(row)
    book = io.BytesIO()
    workbook.save(book)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        folder = f"EDM_{year}_Storm_Overflow_Annual_Return"
        z.writestr(f"{folder}/EDM {year} Storm Overflow Annual Return - all water and sewerage companies.xlsx", book.getvalue())
        z.writestr(f"{folder}/README.pdf", b"%PDF")
    return storm_overflows.Download(year, archive.getvalue())


def test_reads_the_2024_layout():
    download = make_return(2024, {
        "South West Water 2024": (2, HEADINGS_2024, [
            overflow(WEST_OKEMENT, datetime.timedelta(hours=2656, minutes=58, seconds=48), 233, unique_id="SBB00568"),
            overflow("GB108050099999", 10.0, 1, unique_id="SBB2"),  # a waterbody that isn't imported
            overflow(73, 5.0, 1, unique_id="SBB3"),  # "Not part of a WFD catchment"
        ]),
    })
    (row,) = storm_overflows.read([download], {WEST_OKEMENT, EAST_OKEMONT})
    assert row == {
        "catchment_id": WEST_OKEMENT, "year": 2024, "company": "South West Water",
        "site_name": "HIGH BICKINGTON STW_SO_HIGH BICKINGTON", "unique_id": "SBB00568",
        "permit_reference": "202194/CS/01", "activity_reference": "A2", "asset_type": "Storm tank at WwTW",
        "receiving_water": "West Okement", "grid_reference": "SS 5916 2017", "easting": 259160, "northing": 120170,
        "spill_hours": pytest.approx(2656.98), "spill_count": 233,
    }


def test_reads_the_2021_layout_and_every_companys_sheet():
    wessex = [h.replace("12-24h count method", "12-24hr counting method") if h.startswith("Counted") else h for h in HEADINGS_2021]
    download = make_return(2021, {
        "South West Water 2021": (2, HEADINGS_2021, [overflow(WEST_OKEMENT, 684.88, 95), overflow(EAST_OKEMONT, "#N/A", None)]),
        "Wessex Water 2021": (2, wessex, [overflow(EAST_OKEMONT, 1.5, 1, name="WESSEX")]),
    })
    rows = storm_overflows.read([download], {WEST_OKEMENT, EAST_OKEMONT})
    assert [(r["catchment_id"], r["site_name"], r["spill_hours"], r["unique_id"]) for r in rows] == [
        (WEST_OKEMENT, "HIGH BICKINGTON STW_SO_HIGH BICKINGTON", 684.88, None),
        (EAST_OKEMONT, "HIGH BICKINGTON STW_SO_HIGH BICKINGTON", None, None),  # #N/A: no figure, not zero
        (EAST_OKEMONT, "WESSEX", 1.5, None),
    ]


def test_the_all_companies_sheet_isnt_read_twice():
    download = make_return(2025, {
        "All WaSC": (7, HEADINGS_2024, [overflow(WEST_OKEMENT, 1.0, 1, unique_id="SBB1")]),
        "South West Water": (6, HEADINGS_2024, [overflow(WEST_OKEMENT, 1.0, 1, unique_id="SBB1")]),
    })
    assert len(storm_overflows.read([download], {WEST_OKEMENT})) == 1


def test_a_changed_return_is_reported_rather_than_guessed():
    headings = [h for h in HEADINGS_2024 if not h.startswith("Total Duration")]
    download = make_return(2026, {"South West Water": (2, headings, [])})
    with pytest.raises(ImportProblem, match="'South West Water' sheet has no column for spill_hours"):
        storm_overflows.read([download], {WEST_OKEMENT})


class FakeReturns(FakeEA):
    def storm_overflows(self, year):
        if year > 2022:
            raise EANotFound("the EA has no such page")
        return make_return(year, {"South West Water": (2, HEADINGS_2024, [])}).data


def test_downloads_every_year_until_one_isnt_published():
    assert [d.year for d in storm_overflows.fetch(FakeReturns())] == [2021, 2022]


@pytest.mark.parametrize("value, expected", [
    (684.88, 684.88),
    (datetime.timedelta(hours=4, minutes=36, seconds=36), 4.61),
    (datetime.datetime(1900, 1, 1, 6, 0), 54.0),  # 2 days and 6 hours after Excel's start date
    (datetime.time(2, 30), 2.5),
    ("#N/A", None),
    (None, None),
])
def test_spill_hours(value, expected):
    assert storm_overflows.hours(value) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("grid_reference, expected", [
    ("SS 5916 2017", (259160, 120170)),
    ("SS5951020280", (259510, 120280)),
    ("SX5751293992", (257512, 93992)),  # West Okement, as the EA gives it in eastings and northings
    ("50/30F", (None, None)),
    ("SS 591 20", (None, None)),
])
def test_grid_references(grid_reference, expected):
    assert storm_overflows.grid_to_numbers(grid_reference) == expected


def test_saving_works_out_latitude_and_longitude(engine):
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT], FakeEA())
    rows = storm_overflows.read([make_return(2024, {"South West Water": (2, HEADINGS_2024, [overflow(WEST_OKEMENT, 1.0, 1, unique_id="SBB1")])})], {WEST_OKEMENT})
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
        for _ in range(2):  # importing again replaces the rows
            storm_overflows.save(conn, SCHEMA, rows)
        saved = conn.execute(sa.text("SELECT latitude, longitude FROM storm_overflows")).all()
    assert [(round(lat, 3), round(lon, 3)) for lat, lon in saved] == [(50.964, -4.007)]  # High Bickington
