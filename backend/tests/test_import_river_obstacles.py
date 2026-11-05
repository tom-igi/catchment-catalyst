"""The river obstacles importer."""

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, river_obstacles
from catalyst.importers.api.catchments import ImportProblem

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()


def obstacle(globalid, ea_id, lon, lat, obstacle_type="culvert", site_name=" "):
    return {
        "type": "Feature",
        "properties": {"globalid": globalid, "ea_obstructid": ea_id, "site_name": site_name,
                       "obstacle_type": obstacle_type, "origin": "artificial", "status": None},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def page(*features):
    return {"type": "FeatureCollection", "features": list(features)}


class FakeObstacles(FakeEA):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.offsets = []

    def river_obstacles(self, box, offset=0):
        self.offsets.append(offset)
        return self.pages[len(self.offsets) - 1]


@pytest.fixture
def database(engine):
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
    return engine


def test_downloads_page_by_page(monkeypatch):
    monkeypatch.setattr(river_obstacles, "RIVER_OBSTACLES_PAGE", 2)
    client = FakeObstacles([page(obstacle("a", 1, 0, 0), obstacle("b", 2, 0, 0)), page(obstacle("c", 3, 0, 0))])
    pages = river_obstacles.fetch(client, (0, 0, 1, 1))
    assert client.offsets == [0, 2]
    assert [o["id"] for o in river_obstacles.read(pages)] == ["a", "b", "c"]


def test_reads_each_obstacle():
    (row,) = river_obstacles.read([page(obstacle("a", 39245, -3.99751, 50.95765))])
    assert row == {"id": "a", "ea_id": 39245, "site_name": None, "obstacle_type": "culvert", "origin": "artificial",
                   "status": None, "longitude": -3.99751, "latitude": 50.95765}


def test_a_changed_service_is_reported_rather_than_guessed():
    feature = obstacle("a", 1, 0, 0)
    del feature["properties"]["obstacle_type"]
    with pytest.raises(ImportProblem, match="sent no obstacle_type"):
        river_obstacles.read([page(feature)])


def test_keeps_the_obstacles_inside_a_catchment(database):
    with database.connect() as conn:
        west, south, east, north = river_obstacles.box(conn, SCHEMA)
        lon, lat = conn.execute(sa.text(
            "SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_PointOnSurface(boundary) AS p FROM catchments WHERE id = :id) x"
        ), {"id": WEST_OKEMENT}).one()
        rows = river_obstacles.place(conn, SCHEMA, river_obstacles.read([page(
            obstacle("inside", 1, lon, lat),
            obstacle("outside", 2, -2.0, 52.0),
        )]))
    assert west < east and south < north  # British National Grid
    assert [(r["id"], r["catchment_id"]) for r in rows] == [("inside", WEST_OKEMENT)]
    with database.begin() as conn:
        for _ in range(2):  # importing again replaces the rows
            river_obstacles.save(conn, SCHEMA, rows)
        assert conn.scalar(sa.text("SELECT count(*) FROM river_obstacles")) == 1
