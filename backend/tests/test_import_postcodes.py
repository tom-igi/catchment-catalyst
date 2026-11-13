"""The postcodes importer (Ordnance Survey's Code-Point Open)."""

import io
import zipfile

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, postcodes
from catalyst.importers.api.common import ImportProblem

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()
HEADINGS = (
    "PC,PQ,EA,NO,CY,RH,LH,CC,DC,WC\n"
    "Postcode,Positional_quality_indicator,Eastings,Northings,Country_code,NHS_regional_HA_code,NHS_HA_code,"
    "Admin_county_code,Admin_district_code,Admin_ward_code\n"
)


def line(postcode, easting, northing, quality=10):
    return f'"{postcode}",{quality},{easting},{northing},"E92000001","E19000002","E18000010","E10000008","E07000043","E05012413"\n'


def download(files: dict[str, str], headings: str | None = HEADINGS) -> bytes:
    """A Code-Point Open download, laid out like the real one."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        if headings is not None:
            z.writestr("Doc/Code-Point_Open_Column_Headers.csv", headings)
        z.writestr("Doc/licence.txt", "ORDNANCE SURVEY DATA LICENCE")
        for name, text in files.items():
            z.writestr(f"Data/CSV/{name}", text)
    return buffer.getvalue()


@pytest.fixture
def database(engine):
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
    return engine


def test_reads_the_postcodes_in_the_box():
    rows = postcodes.read(download({
        "ex.csv": line("EX20 1AA", 260000, 90000) + line("EX201AB", 260500, 90500) + line("EX20 1AD", 0, 0, quality=90)
                  + line("EX31 1AB", 254234, 133809),  # outside the box
        "pl.csv": line("PL1 1AA", 259999, 89999),  # just outside the box
    }), (260000, 90000, 261000, 91000))
    assert rows == [
        {"postcode": "EX20 1AA", "easting": 260000.0, "northing": 90000.0},
        {"postcode": "EX20 1AB", "easting": 260500.0, "northing": 90500.0},  # with its space put back
    ]


@pytest.mark.parametrize("text, tidied", [("EX36 3AA", "EX36 3AA"), ("ex363aa", "EX36 3AA"), (" pl1  1aa ", "PL1 1AA"), ("W1A 0AX", "W1A 0AX")])
def test_postcodes_are_tidied(text, tidied):
    assert postcodes.tidy(text) == tidied


@pytest.mark.parametrize("text", ["EX36", "EX36 3A", "36 3AA", "EX36 3AA X"])
def test_a_postcode_must_be_whole(text):
    with pytest.raises(ValueError):
        postcodes.tidy(text)


def test_a_changed_download_is_reported_rather_than_guessed():
    with pytest.raises(ImportProblem, match="has no Doc/Code-Point_Open_Column_Headers.csv"):
        postcodes.read(download({"ex.csv": ""}, headings=None), (0, 0, 1, 1))
    with pytest.raises(ImportProblem, match="doesn't name the columns"):
        postcodes.read(download({"ex.csv": ""}, headings="Postcode,Eastings,Northings\n"), (0, 0, 1, 1))
    with pytest.raises(ImportProblem, match="no postcode files"):
        postcodes.read(download({}), (0, 0, 1, 1))
    with pytest.raises(ImportProblem, match="ex.csv, line 2"):
        postcodes.read(download({"ex.csv": line("EX20 1AA", 5, 5) + line("not one", 5, 5)}), (0, 0, 10, 10))
    with pytest.raises(ImportProblem, match="isn't a readable .zip"):
        postcodes.read(b"<html>Sorry</html>", (0, 0, 1, 1))


def test_keeps_the_postcodes_inside_a_catchment(database):
    with database.connect() as conn:
        easting, northing = conn.execute(sa.text(
            "SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_PointOnSurface(boundary), 27700) AS p FROM catchments WHERE id = :id) x"
        ), {"id": WEST_OKEMENT}).one()
        rows = postcodes.place(conn, SCHEMA, [
            {"postcode": "EX20 1AA", "easting": easting, "northing": northing},
            {"postcode": "EX31 1AB", "easting": 254234, "northing": 133809},  # Barnstaple: in neither
        ])
    (row,) = rows
    assert (row["postcode"], row["catchment_id"]) == ("EX20 1AA", WEST_OKEMENT)
    assert 50 < row["latitude"] < 51 and -4.1 < row["longitude"] < -3.9  # Dartmoor
    with database.begin() as conn:
        for _ in range(2):  # importing again replaces the rows
            postcodes.save(conn, SCHEMA, rows)
        assert conn.scalar(sa.text("SELECT count(*) FROM postcodes")) == 1


def test_keeps_the_download(tmp_path):
    folder = postcodes.save_raw_files(b"PK...", tmp_path)
    assert folder.parent == tmp_path / "postcodes"
    assert (folder / "codepo_gb.zip").read_bytes() == b"PK..."
