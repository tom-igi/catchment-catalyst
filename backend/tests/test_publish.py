"""The publish step: each location's dashboard, as web pages."""

import json

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, classifications
from catalyst.publish import collect, figures, site
from catalyst.publish.__main__ import main
from catalyst.publish.collect import PublishProblem

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()


@pytest.fixture
def database(engine):
    """Both test catchments, in a North Devon location, with the EA's real
    classifications and RNAGs for West Okement only."""
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
        conn.execute(sa.text("INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', :ids)"),
                     {"ids": [WEST_OKEMENT, EAST_OKEMONT]})
        classifications.save(conn, SCHEMA, classifications.read(classifications.fetch([3062], FakeEA()), {WEST_OKEMENT}))
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

    page = (folder / "index.html").read_text()  # River Status, while the Overview is switched off
    assert ">Overview</a>" not in page
    assert '<a href="river-status/" aria-current="page">River Status</a>' in page
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


def test_the_overview_can_be_switched_back_on(database, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "SHOW_OVERVIEW", True)
    folder = publish(database, tmp_path)
    page = (folder / "index.html").read_text()
    assert '<a href="./" aria-current="page">Overview</a>' in page
    assert "Ecological status of North Devon Catchment rivers (2022)" in page
    assert "<td>Poor</td>" in page
    assert '<a href="./">Overview</a>' in (folder / "river-status" / "index.html").read_text().replace('href="../"', 'href="./"')


def test_the_side_shows_the_classification_failing_elements_and_reasons(database, tmp_path):
    folder = publish(database, tmp_path)
    page = (folder / "sewerage" / WEST_OKEMENT / "index.html").read_text()
    assert '<li class="status-poor"><span>2022</span><strong>Poor</strong></li>' in page
    assert '<li class="status-moderate"><span>2016</span><strong>Moderate</strong></li>' in page
    assert "<li>Fish</li>" in page  # Poor in 2022
    assert "<li>Abandoned mine</li>" in page  # an RNAG
    assert "<li>Not applicable</li>" not in page
    page = (folder / "sewerage" / EAST_OKEMONT / "index.html").read_text()  # no results: shown empty
    assert '<li class="status-none"><span>2022</span><strong></strong></li>' in page
    assert "<li>Fish</li>" not in page


def test_ea_data_shows_each_result_coloured_by_its_status(database, tmp_path):
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert page.index(">Ecological</th>") < page.index(">Fish</th>")  # the EA's order, not alphabetical
    assert '<td class="status-poor">Poor</td>' in page
    assert '<td class="status-not-high">Not High</td>' in page  # Morphology
    assert ">Mercury and Its Compounds</th>" not in page  # single chemicals aren't shown
    assert [f'<th scope="col">{year}</th>' in page for year in (2022, 2019, 2016, 2015, 2014)] == [True] * 4 + [False]


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
            "VALUES ('ea_classifications', 'EA Classifications', 'Environment Agency', 'https://example.org/ea', "
            "'2025 is provisional')"
        ))
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert 'popovertarget="info-ea_classifications"' in page
    assert '<a href="https://example.org/ea">Environment Agency</a>' in page
    assert "2025 is provisional" in page
    page = (publish(database, tmp_path) / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert 'popovertarget="info-habitat_land_use"' not in page  # no datasets row yet: greyed out
    assert '<span class="info" aria-hidden="true">i</span>' in page


def test_figures_cope_with_a_missing_table(database):
    location = gather(database)
    location.datasets = [d for d in location.datasets if d.table not in ("ea_classifications", "ea_rnags", "habitat_land_use")]
    numbers = figures.Figures(location)
    assert numbers.status(WEST_OKEMENT) is None
    assert numbers.status_counts() == []
    assert numbers.classification(WEST_OKEMENT) == []
    assert numbers.scoring(WEST_OKEMENT).rows == []
    assert numbers.failing_elements(WEST_OKEMENT) == []
    assert numbers.reasons(WEST_OKEMENT) == []
    assert numbers.habitat(location.catchments[0]) == []


def result(item, year, status, cycle=3, level="Element"):
    return {"item": item, "year": year, "cycle": cycle, "level": level, "status": status, "certainty": None}


def with_results(results: dict[str, list[dict]]) -> figures.Figures:
    dataset = collect.Dataset("ea_classifications", "EA Classifications", None, [], results, None)
    return figures.Figures(collect.Location("Here", "here", [], {}, [dataset], {}))


def test_status_counts_are_most_first():
    numbers = with_results({
        "A": [result("Ecological", 2022, "Good")],
        "B": [result("Ecological", 2022, "Poor")],
        "C": [result("Ecological", 2022, "Poor")],
        "D": [result("Ecological", 2019, "Bad")],  # not this year
    })
    assert numbers.status_counts() == [("Poor", 2), ("Good", 1)]
    assert numbers.statuses() == ["Good", "Poor", "Bad"]
    assert numbers.classification("D") == [(2022, None), (2019, "Bad")]


def test_a_year_classified_twice_uses_the_later_cycle():
    numbers = with_results({"A": [result("Ecological", 2019, "Good", cycle=2), result("Ecological", 2019, "Poor", cycle=3)]})
    assert numbers.status("A") == "Poor"


def test_failing_elements_are_those_below_good_in_the_latest_year():
    numbers = with_results({"A": [
        result("Ecological", 2022, "Moderate", level="Ecological, chemical or quantitative status"),
        result("Fish", 2022, "Moderate"),
        result("Invertebrates", 2022, "Good"),
        result("Phosphate", 2019, "Poor"),  # an earlier year
        result("Mercury and Its Compounds", 2022, "Fail"),  # a chemical
        result("Macrophytes and Phytobenthos Combined", 2022, "Moderate"),  # left out for its sub element
        result("Phytobenthos Sub Element", 2022, "Moderate", level="Sub Element"),
        result("Biological quality elements", 2022, "Moderate", level="Component"),
    ]})
    assert numbers.failing_elements("A") == ["Fish", "Phytobenthos Sub Element"]


def overflow(year, site, hours, latitude=50.96, longitude=-4.0):
    return {"catchment_id": WEST_OKEMENT, "year": year, "company": "South West Water", "site_name": site,
            "spill_hours": hours, "latitude": latitude, "longitude": longitude}


def test_sewerage_shows_each_overflows_hours_a_year(database, tmp_path):
    with database.begin() as conn:
        conn.execute(SCHEMA.metadata.tables["storm_overflows"].insert(), [
            overflow(2022, "HIGH BICKINGTON", 1563.19),
            overflow(2023, "HIGH BICKINGTON", 2896.43, latitude=50.97),
            overflow(2022, "YARNSCOMBE", 1462.5),
            overflow(2021, "YARNSCOMBE", None),  # no figure that year
            overflow(2021, "NO MONITOR", None),  # no figures at all: left out, as on the original
        ])
    folder = publish(database, tmp_path)
    page = (folder / "sewerage" / WEST_OKEMENT / "index.html").read_text()
    assert "South West Water Intermittent Sewage Discharges (hrs per year)" in page
    assert '<th scope="col" data-type="number" class="num">2021</th>' in page
    assert ">1463</td>" in page  # 1462.5, rounded half up as on the original
    assert ">3026</td>" in page  # 2022's total
    assert ">5922</td>" in page  # everything
    assert "NO MONITOR" not in page
    assert 'data-points=\'[[50.97, -4.0, "HIGH BICKINGTON"], [50.96, -4.0, "YARNSCOMBE"]]\'' in page  # the latest place
    page = (folder / "sewerage" / EAST_OKEMONT / "index.html").read_text()
    assert "HIGH BICKINGTON" not in page


def test_land_use_shows_the_river_obstacles(database, tmp_path):
    with database.begin() as conn:
        conn.execute(SCHEMA.metadata.tables["river_obstacles"].insert(), [
            {"id": "b", "ea_id": 39245, "catchment_id": WEST_OKEMENT, "site_name": None, "obstacle_type": "culvert", "origin": "artificial",
             "latitude": 50.95, "longitude": -4.0},
            {"id": "a", "ea_id": 775, "catchment_id": WEST_OKEMENT, "site_name": "Sticklepath Weir", "obstacle_type": "weir",
             "origin": "artificial", "latitude": 50.96, "longitude": -4.0},
        ])
    page = (publish(database, tmp_path) / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert page.index("<td>775</td>") < page.index("<td>39245</td>")
    assert "<td>Sticklepath Weir</td>" in page
    assert '[50.95, -4.0, "culvert, EA ID 39245"]' in page


def test_the_map_has_each_outline_river_and_status(database, tmp_path):
    folder = publish(database, tmp_path)
    features = json.loads((folder / "catchments.geojson").read_text())["features"]
    assert sorted((f["properties"]["id"], f["properties"]["layer"], f["geometry"]["type"], f["properties"]["status"])
                  for f in features) == [
        (WEST_OKEMENT, "catchment", "Polygon", "Poor"),
        (WEST_OKEMENT, "river", "MultiLineString", "Poor"),
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
