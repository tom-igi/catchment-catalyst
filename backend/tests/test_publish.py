"""The publish step: each location's dashboard, as web pages."""

import json

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments
from catalyst.publish import collect, figures, site
from catalyst.publish.__main__ import main
from catalyst.publish.collect import PublishProblem

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()


@pytest.fixture
def database(engine):
    """Both test catchments, in a North Devon location, with EA scores for one of them."""
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
        conn.execute(sa.text("INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', :ids)"),
                     {"ids": [WEST_OKEMENT, EAST_OKEMONT]})
        conn.execute(SCHEMA.metadata.tables["ea_scores"].insert(), [
            {"catchment_id": WEST_OKEMENT, "measure": "Fish", "year": 2025, "status": "Poor", "value": 0.16},
            {"catchment_id": WEST_OKEMENT, "measure": "Fish", "year": 2022, "status": "Good", "value": 0.7},
            {"catchment_id": WEST_OKEMENT, "measure": "Ecological", "year": 2025, "status": "Moderate", "value": None},
            {"catchment_id": WEST_OKEMENT, "measure": "Ecological", "year": 2022, "status": "Good", "value": None},
        ])
    return engine


def gather(engine) -> collect.Location:
    with engine.connect() as conn:
        (row,) = collect.locations(conn, SCHEMA)
        return collect.collect(conn, SCHEMA, row)


def publish(engine, out_dir):
    return site.write_location(gather(engine), out_dir)


def test_a_page_for_each_tab_and_catchment(database, tmp_path):
    folder = publish(database, tmp_path)
    assert folder == tmp_path / "north-devon"

    page = (folder / "index.html").read_text()  # the Overview
    assert "Understanding Water Quality in the North Devon Catchment" in page
    assert '<a href="./" aria-current="page">Overview</a>' in page
    assert '<a href="river-status/">River Status</a>' in page
    assert 'data-geojson="catchments.geojson" data-links="river-status/"' in page

    for tab in ["river-status", "ea-data", "land-use", "sewerage"]:
        page = (folder / tab / "index.html").read_text()  # before a catchment is chosen
        assert "Select a river catchment on the map" in page
        assert f'<a href="../{tab}/" aria-current="page">' in page
        for catchment_id in [WEST_OKEMENT, EAST_OKEMONT]:
            page = (folder / tab / catchment_id / "index.html").read_text()
            assert f'data-links="../../{tab}/" data-selected="{catchment_id}"' in page
            assert f'<a href="../../ea-data/{catchment_id}/">EA Data</a>' in page or tab == "ea-data"
            assert 'src="../../assets/map.js"' in page

    page = (folder / "river-status" / WEST_OKEMENT / "index.html").read_text()
    assert '<h1 class="title-bar">West Okement</h1>' in page
    for asset in ["style.css", "map.js", "sort.js", "leaflet/leaflet.js"]:
        assert (folder / "assets" / asset).is_file()


def test_the_overview_counts_the_ecological_statuses(database, tmp_path):
    page = (publish(database, tmp_path) / "index.html").read_text()
    assert "Ecological status of North Devon Catchment rivers (2025)" in page
    assert "<td>Moderate</td>" in page
    assert '<td class="num">1</td>' in page  # one Moderate, and the total


def test_the_side_shows_the_ecological_classification(database, tmp_path):
    folder = publish(database, tmp_path)
    page = (folder / "sewerage" / WEST_OKEMENT / "index.html").read_text()
    assert '<li class="status-moderate"><span>2025</span><strong>Moderate</strong></li>' in page
    assert '<li class="status-good"><span>2022</span><strong>Good</strong></li>' in page
    page = (folder / "sewerage" / EAST_OKEMONT / "index.html").read_text()  # no scores: shown empty
    assert '<li class="status-none"><span>2025</span><strong></strong></li>' in page


def test_ea_data_shows_each_score_coloured_by_its_status(database, tmp_path):
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert page.index(">Ecological</th>") < page.index(">Fish</th>")  # the EA's order, not alphabetical
    assert '<td class="status-poor" title="Poor">0.16</td>' in page
    assert '<td class="status-good" title="Good">0.7</td>' in page
    assert '<td class="status-moderate">Moderate</td>' in page  # no value, so the status


def test_land_use_shows_the_river_information_and_habitat(database, tmp_path):
    with database.begin() as conn:
        conn.execute(SCHEMA.metadata.tables["habitat_land_use"].insert(),
                     [{"catchment_id": WEST_OKEMENT, "habitat": "Woodland", "area_ha": 500}])
    location = gather(database)
    area = next(c["area_ha"] for c in location.catchments if c["id"] == WEST_OKEMENT)
    page = (publish(database, tmp_path) / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert f"<td>{WEST_OKEMENT}</td>" in page
    assert "<td>Woodland</td>" in page
    assert f"{100 * 500 / area:.1f}%" in page
    page = (publish(database, tmp_path) / "land-use" / EAST_OKEMONT / "index.html").read_text()
    assert "<td>Woodland</td>" not in page


def test_info_buttons_show_the_datasets_table(database, tmp_path):
    with database.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO datasets (table_name, name, source_organisation, source_url, caveats) "
            "VALUES ('ea_scores', 'EA Scores', 'Environment Agency', 'https://example.org/ea', '2025 is provisional')"
        ))
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert 'popovertarget="info-ea_scores"' in page
    assert '<a href="https://example.org/ea">Environment Agency</a>' in page
    assert "2025 is provisional" in page
    page = (publish(database, tmp_path) / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert 'popovertarget="info-habitat_land_use"' not in page  # no datasets row yet: greyed out
    assert '<span class="info" aria-hidden="true">i</span>' in page


def test_figures_cope_with_a_missing_table(database):
    location = gather(database)
    location.datasets = [d for d in location.datasets if d.table not in ("ea_scores", "habitat_land_use")]
    numbers = figures.Figures(location)
    assert numbers.status(WEST_OKEMENT) is None
    assert numbers.status_counts() == []
    assert numbers.classification(WEST_OKEMENT) == []
    assert numbers.scoring(WEST_OKEMENT).rows == []
    assert numbers.habitat(location.catchments[0]) == []


def test_status_counts_are_most_first():
    location = collect.Location("Here", "here", [], {}, [collect.Dataset(
        "ea_scores", "EA Scores", None, [], {
            "A": [{"measure": "Ecological", "year": 2025, "status": "Good", "value": None}],
            "B": [{"measure": "ecological", "year": 2025, "status": "Poor", "value": None}],
            "C": [{"measure": "Ecological", "year": 2025, "status": "Poor", "value": None}],
            "D": [{"measure": "Ecological", "year": 2022, "status": "Bad", "value": None}],  # not this year
        }, None,
    )], {})
    numbers = figures.Figures(location)
    assert numbers.status_counts() == [("Poor", 2), ("Good", 1)]
    assert numbers.statuses() == ["Good", "Poor", "Bad"]
    assert numbers.classification("D") == [(2025, None), (2022, "Bad")]


def test_the_map_has_each_outline_river_and_status(database, tmp_path):
    folder = publish(database, tmp_path)
    features = json.loads((folder / "catchments.geojson").read_text())["features"]
    assert sorted((f["properties"]["id"], f["properties"]["layer"], f["geometry"]["type"], f["properties"]["status"])
                  for f in features) == [
        (WEST_OKEMENT, "catchment", "Polygon", "Moderate"),
        (WEST_OKEMENT, "river", "MultiLineString", "Moderate"),
        (EAST_OKEMONT, "catchment", "Polygon", None),
        (EAST_OKEMONT, "river", "MultiLineString", None),
    ]


def test_publishing_again_replaces_the_old_pages(database, tmp_path):
    publish(database, tmp_path)
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT]})
    folder = publish(database, tmp_path)
    assert (folder / "river-status" / WEST_OKEMENT).is_dir()
    assert not (folder / "river-status" / EAST_OKEMONT).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["north-devon"]  # nothing left over


def test_catchments_that_arent_imported_stop_the_publish(database, tmp_path):
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT, "GB999"]})
    with pytest.raises(PublishProblem, match="North Devon lists catchment IDs that aren't in the catchments table: GB999"):
        publish(database, tmp_path)


def test_the_command_publishes_every_location(database, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", database.url.render_as_string(hide_password=False))
    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    assert main([]) == 0
    assert "North Devon: 2 catchment(s)" in capsys.readouterr().out
    assert '<a href="north-devon/">North Devon</a>' in (tmp_path / "index.html").read_text()


@pytest.mark.parametrize("name, expected", [
    ("North Devon", "north-devon"),
    ("  Exe & Culm (Devon) ", "exe-culm-devon"),
])
def test_web_addresses_come_from_the_name(name, expected):
    assert collect.slug(name) == expected
