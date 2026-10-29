"""The publish step: each location's dashboard, as web pages."""

import json

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments
from catalyst.publish import collect, site
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
        ])
    return engine


def publish(engine, out_dir):
    with engine.connect() as conn:
        (row,) = collect.locations(conn, SCHEMA)
        location = collect.collect(conn, SCHEMA, row)
    return site.write_location(location, out_dir)


def test_a_page_for_the_location_and_each_catchment(database, tmp_path):
    folder = publish(database, tmp_path)
    assert folder == tmp_path / "north-devon"

    page = (folder / "index.html").read_text()
    assert f'<a href="{WEST_OKEMENT}/">West Okement</a>' in page
    assert f'<a href="{EAST_OKEMONT}/">East Okemont River</a>' in page
    assert 'data-geojson="catchments.geojson"' in page

    page = (folder / WEST_OKEMENT / "index.html").read_text()
    assert "<h1>West Okement</h1>" in page
    assert '<th scope="col" data-type="number" class="num">Value</th>' in page
    assert '<td data-sort="0.16" class="num">0.16</td>' in page
    assert "No data for this catchment yet." in page  # no habitat rows
    assert 'src="../assets/sort.js"' in page

    assert "No data for this catchment yet." in (folder / EAST_OKEMONT / "index.html").read_text()
    for asset in ["style.css", "map.js", "sort.js", "leaflet/leaflet.js"]:
        assert (folder / "assets" / asset).is_file()


def test_the_map_has_each_outline_and_river(database, tmp_path):
    folder = publish(database, tmp_path)
    features = json.loads((folder / "catchments.geojson").read_text())["features"]
    assert sorted((f["properties"]["id"], f["properties"]["layer"], f["geometry"]["type"]) for f in features) == [
        (WEST_OKEMENT, "catchment", "Polygon"),
        (WEST_OKEMENT, "river", "MultiLineString"),
        (EAST_OKEMONT, "catchment", "Polygon"),
        (EAST_OKEMONT, "river", "MultiLineString"),
    ]


def test_publishing_again_replaces_the_old_pages(database, tmp_path):
    publish(database, tmp_path)
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT]})
    folder = publish(database, tmp_path)
    assert (folder / WEST_OKEMENT).is_dir()
    assert not (folder / EAST_OKEMONT).exists()
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
