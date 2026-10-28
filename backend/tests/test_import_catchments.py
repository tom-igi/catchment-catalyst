"""The catchments importer.

Uses real EA downloads saved in tests/fixtures/ea (EA data, Open Government
Licence), so the tests don't depend on the EA's servers being up.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers import catchments
from catalyst.importers.catchments import ImportProblem
from catalyst.importers.ea_api import EAError

FIXTURES = Path(__file__).parent / "fixtures" / "ea"
WEST_OKEMENT, EAST_OKEMONT = "GB108050008080", "GB108050008100"


class FakeEA:
    """Stands in for the EA, answering from the saved downloads.

    `answer_with` makes it answer for one catchment with another's files.
    """

    def __init__(self, answer_with: dict[str, str] | None = None):
        self.answer_with = answer_with or {}

    def waterbody_shapefile(self, waterbody_id):
        path = FIXTURES / f"{self.answer_with.get(waterbody_id, waterbody_id)}.zip"
        if not path.exists():
            raise EAError("the EA returned error 500, after 3 tries")
        return path.read_bytes()

    def waterbody_page(self, waterbody_id):
        return (FIXTURES / f"{self.answer_with.get(waterbody_id, waterbody_id)}.html").read_text()


def test_reads_details_and_shapes_from_the_shapefile():
    details, boundary, river_line = catchments.read_shapefile(
        WEST_OKEMENT, (FIXTURES / f"{WEST_OKEMENT}.zip").read_bytes()
    )
    assert details == {
        "name": "West Okement",
        "waterbody_type": "River",
        "river_basin_district_id": 8,
        "river_basin_district": "South West",
        "management_catchment_id": 3062,
        "management_catchment": "North Devon",
        "operational_catchment_id": 3468,
        "operational_catchment": "Torridge",
        "hydromorphological_designation": "not designated artificial or heavily modified",
    }
    assert boundary["type"] == "Polygon"
    assert river_line["type"] == "MultiLineString"


def test_reads_length_and_connections_from_the_web_page():
    length, upstream, downstream = catchments.read_page(
        WEST_OKEMENT, (FIXTURES / f"{WEST_OKEMENT}.html").read_text()
    )
    assert length == 21.13
    assert upstream == []
    assert downstream == [("GB108050008110", "Middle River Okement")]


def test_a_changed_web_page_is_reported_rather_than_guessed():
    page = (FIXTURES / f"{WEST_OKEMENT}.html").read_text()
    with pytest.raises(ImportProblem, match="no 'Length'"):
        catchments.read_page(WEST_OKEMENT, page.replace(">Length<", ">River length<"))
    with pytest.raises(ImportProblem, match="no upstream/downstream"):
        catchments.read_page(WEST_OKEMENT, page.replace('id="upstream-water-bodies"', 'id="upstream"'))


def test_downloads_for_the_wrong_catchment_are_rejected():
    found, problems = catchments.fetch([EAST_OKEMONT], FakeEA(answer_with={EAST_OKEMONT: WEST_OKEMENT}))
    assert found == []
    assert "is for GB108050008080, not GB108050008100" in problems[0]


def test_every_problem_is_reported_together():
    found, problems = catchments.fetch([WEST_OKEMENT, "GB999999999999", EAST_OKEMONT], FakeEA())
    assert [c.id for c in found] == [WEST_OKEMENT, EAST_OKEMONT]
    assert problems == ["GB999999999999: the EA returned error 500, after 3 tries"]


@pytest.mark.parametrize("content, message", [
    ('{"catchments": ["GB108050008080"]}', None),
    ('{"description": "Test", "catchments": ["GB108050008080"]}', None),
    ('{"catchment": ["GB108050008080"]}', "should look like"),
    ('{"catchments": []}', "should look like"),
    ('{"catchments": ["West Okement"]}', "aren't catchment IDs: West Okement"),
    ('{"catchments": ["GB108050008080", "GB108050008080"]}', "more than once: GB108050008080"),
    ('{"catchments": ["GB108050008080",]}', "not valid JSON"),
])
def test_the_catchment_list_is_checked(tmp_path, content, message):
    path = tmp_path / "catchments.json"
    path.write_text(content)
    if message is None:
        assert catchments.read_catchment_list(path) == ["GB108050008080"]
    else:
        with pytest.raises(ImportProblem, match=message):
            catchments.read_catchment_list(path)


def test_import_fills_the_tables_and_can_be_repeated(engine):
    schema = load_schema()
    apply_changes(engine, schema)
    found, problems = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    assert problems == []

    for _ in range(2):  # importing again updates rather than duplicating
        with engine.begin() as conn:
            catchments.save(conn, schema, found)

    with engine.connect() as conn:
        rows = conn.execute(sa.text("""
            SELECT id, name, round(area_ha::numeric, 2)::float AS area_ha, river_length_km,
                   ST_SRID(boundary) AS srid, GeometryType(boundary) AS shape, ST_IsValid(boundary) AS valid
            FROM catchments ORDER BY id
        """)).all()
        links = conn.execute(sa.text(
            "SELECT catchment_id, direction, connected_id, connected_name FROM catchment_connections ORDER BY 1"
        )).all()
    assert [tuple(r) for r in rows] == [
        (WEST_OKEMENT, "West Okement", 3174.75, 21.13, 4326, "MULTIPOLYGON", True),
        (EAST_OKEMONT, "East Okemont River", 2061.61, 10.232, 4326, "MULTIPOLYGON", True),
    ]
    assert [tuple(r) for r in links] == [
        (WEST_OKEMENT, "downstream", "GB108050008110", "Middle River Okement"),
        (EAST_OKEMONT, "downstream", "GB108050008110", "Middle River Okement"),
    ]


def test_downloads_are_kept_as_they_were(tmp_path):
    found, _ = catchments.fetch([WEST_OKEMENT], FakeEA())
    run_dir = catchments.save_raw_files(found, tmp_path)
    kept = run_dir / WEST_OKEMENT / "shapefile.zip"
    assert kept.read_bytes() == (FIXTURES / f"{WEST_OKEMENT}.zip").read_bytes()
