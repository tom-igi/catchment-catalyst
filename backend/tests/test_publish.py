"""The publish step: each location's dashboard, as web pages."""

import json

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, classifications
from catalyst.publish import collect, figures, last_publish, publish_all, site
from catalyst.publish.__main__ import main
from catalyst.publish.collect import PublishProblem
from catalyst.publish.text import formatted

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
    version = site.version(folder)
    assert f'data-geojson="catchments.geojson?v={version}" data-links="river-status/"' in page

    for tab in ["river-status", "ea-data", "land-use", "sewerage"]:
        page = (folder / tab / "index.html").read_text()  # before a catchment is chosen
        assert "Select a river catchment on the map" in page
        assert f'<a href="../{tab}/" aria-current="page">' in page
        for catchment_id in [WEST_OKEMENT, EAST_OKEMONT]:
            page = (folder / tab / catchment_id / "index.html").read_text()
            assert f'data-links="../../{tab}/" data-selected="{catchment_id}"' in page
            assert f'<a href="../../ea-data/{catchment_id}/">EA Data</a>' in page or tab == "ea-data"
            assert f'src="../../assets/map.js?v={version}"' in page

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
            "INSERT INTO datasets (table_name, info_text) "
            "VALUES ('ea_classifications', 'From the Environment Agency.\n\n2025 is <provisional>.')"
        ))
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert 'popovertarget="info-ea_classifications"' in page
    assert "<h3>EA Classifications</h3>" in page  # the table's title
    assert "<p>From the Environment Agency.</p>\n<p>2025 is &lt;provisional&gt;.</p>" in page  # in paragraphs, as text
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
    assert [p.published_by for p in publishes(database)] == [None]  # recorded, as the command


def publishes(engine) -> list[sa.Row]:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT * FROM publishes ORDER BY id")).all()


def test_each_publish_is_recorded(database, tmp_path):
    with database.connect() as conn:
        assert last_publish(conn, SCHEMA) is None
    (location,) = publish_all(database, SCHEMA, tmp_path / "out", published_by="tom")
    assert location.name == "North Devon"
    assert (tmp_path / "out" / "north-devon" / "index.html").is_file()
    assert (tmp_path / "out" / "index.html").is_file()
    publish_all(database, SCHEMA, tmp_path / "out", published_by="alex")
    first, second = publishes(database)
    assert (first.published_by, second.published_by) == ("tom", "alex")
    assert first.published_at <= second.published_at
    with database.connect() as conn:
        assert last_publish(conn, SCHEMA).id == second.id


def test_a_publish_that_fails_is_not_recorded(database, tmp_path):
    not_a_folder = tmp_path / "a file"
    not_a_folder.write_text("")
    with pytest.raises(OSError):  # the pages can't be written
        publish_all(database, SCHEMA, not_a_folder)
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT, "GB999"]})
    with pytest.raises(PublishProblem, match="GB999"):
        publish_all(database, SCHEMA, tmp_path / "out")
    with database.begin() as conn:
        conn.execute(sa.text("DELETE FROM locations"))
    with pytest.raises(PublishProblem, match="There are no locations to publish yet"):
        publish_all(database, SCHEMA, tmp_path / "out")
    assert publishes(database) == []
    assert not (tmp_path / "out").exists()  # nothing written


@pytest.mark.parametrize("name, expected", [
    ("North Devon", "north-devon"),
    ("  Exe & Culm (Devon) ", "exe-culm-devon"),
])
def test_web_addresses_come_from_the_name(name, expected):
    assert collect.slug(name) == expected


# --- The four views and the new tables ----------------------------------------

def insert(engine, table, rows):
    with engine.begin() as conn:
        conn.execute(SCHEMA.metadata.tables[table].insert(), rows)


def location_id(engine):
    with engine.connect() as conn:
        return conn.scalar(sa.text("SELECT id FROM locations"))


def test_every_page_has_the_four_views(database, tmp_path):
    folder = publish(database, tmp_path)
    pages = {
        "river-status": folder / "river-status" / WEST_OKEMENT / "index.html",
        "catchment-dashboard": folder / "catchment-dashboard" / "index.html",
        "intervention-management": folder / "intervention-management" / "index.html",
        "catchment-insights": folder / "catchment-insights" / "index.html",
    }
    for view, path in pages.items():
        page = path.read_text()
        assert page.count('class="view-card"') == 4
        assert page.count('aria-current="page">\n    <img') == 1  # one card is the current one
        assert f'href="{"../../" if view == "river-status" else "../"}{view}/" aria-current="page"' in page
    assert (folder / "assets" / "cards" / "catchment.jpg").is_file()
    page = (folder / "index.html").read_text()  # the front page is the Waterbody Dashboard
    assert '<a class="view-card" href="river-status/" aria-current="page">' in page


def test_choosing_another_catchment_or_tab_keeps_your_place(database, tmp_path):
    folder = publish(database, tmp_path)
    page = (folder / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert f'<script src="../../assets/keep-scroll.js?v={site.version(folder)}"></script>' in page
    assert '<nav class="tabs" aria-label="Waterbody Dashboard pages" data-keep-scroll>' in page
    assert 'data-keep-scroll role="img"' in page  # the map: another catchment's page is laid out the same
    assert '<th scope="row">Upstream Rivers</th><td data-keep-scroll>' in page
    page = (folder / "catchment-dashboard" / "index.html").read_text()
    assert '<ul class="area-buttons operational" data-keep-scroll>' in page
    assert 'data-keep-scroll role="img"' not in page  # its map's catchments can't be clicked
    assert (folder / "assets" / "keep-scroll.js").is_file()


def test_river_status_shows_the_text_risks_interventions_and_ranking(database, tmp_path):
    insert(database, "river_status_text", [{
        "catchment_id": WEST_OKEMENT, "why_failing": "Fish are poor.\n\nThe reasons:\n- Metals\n- Mining",
        "happening_now": "<b>Surveys</b>", "intervention_hypothesis": "Treat the mine water.", "hypothesis_confidence": "Med-High",
    }])
    insert(database, "risk_levels", [{"catchment_id": WEST_OKEMENT, "untreated_sewage": "Very High", "running_dry": "Low"}])
    insert(database, "catchment_rankings", [{"catchment_id": WEST_OKEMENT, "ranking": 7}])
    here = location_id(database)
    insert(database, "intervention_types", [
        {"location_id": here, "number": 3, "name": "Less metal", "summary_group": "Priority interventions"},
        {"location_id": here, "number": 12, "name": "Fish passage", "summary_group": "Secondary interventions"},
    ])
    insert(database, "intervention_waterbodies", [
        {"catchment_id": WEST_OKEMENT, "intervention": 12, "group_number": 1, "estimated_cost": 500_000, "lead": "WRT"},
        {"catchment_id": WEST_OKEMENT, "intervention": 3, "group_number": 1, "estimated_cost": 250_000, "lead": "EA"},
    ])
    page = (publish(database, tmp_path) / "river-status" / WEST_OKEMENT / "index.html").read_text()
    assert "<p>Fish are poor.</p>\n<p>The reasons:</p>\n<ul>\n<li>Metals</li>\n<li>Mining</li>\n</ul>" in page
    assert "&lt;b&gt;Surveys&lt;/b&gt;" in page  # text is shown as typed, never as HTML
    assert "Intervention hypothesis (confidence: Med-High)" in page
    assert '<li class="risk-very-high"><span class="risk-name">Untreated Sewage</span><span class="risk-level">Very High</span></li>' in page
    assert '<li class="risk-none"><span class="risk-name">Modification</span><span class="risk-level"></span></li>' in page
    assert "Catchment Ranking: 7/2" in page  # of the location's 2 rivers
    assert page.index("PRIORITY INTERVENTIONS") < page.index("Less metal") < page.index("SECONDARY INTERVENTIONS") < page.index("Fish passage")
    assert '<a href="../../intervention-management/#intervention-12">Fish passage</a>' in page  # its page on Intervention Management
    assert '<td class="num">£500,000</td>' in page
    page = (tmp_path / "north-devon" / "river-status" / EAST_OKEMONT / "index.html").read_text()
    assert "Fish are poor" not in page and "Catchment Ranking:</h2>" in page


def test_ea_data_shows_the_values_and_thresholds(database, tmp_path):
    insert(database, "ea_scores", [
        {"catchment_id": WEST_OKEMENT, "measure": "Fish (EQR)", "year": 2022, "value": 0.36, "status": "Good"},
        {"catchment_id": WEST_OKEMENT, "measure": "Inverts NTAXA (EQR)", "year": 2022, "value": 0.97, "status": "High"},
        {"catchment_id": WEST_OKEMENT, "measure": "Phosphate (mg/l)", "year": 2022, "value": 0.057, "status": None},
        {"catchment_id": WEST_OKEMENT, "measure": "Something else", "year": 2022, "value": 1.5, "status": None},
    ])
    insert(database, "ea_thresholds", [
        {"catchment_id": WEST_OKEMENT, "measure": "Fish (EQR)", "poor": 0.03, "moderate": 0.2, "good": 0.4, "high": 0.7},
    ])
    scoring = figures.Figures(gather(database)).scoring(WEST_OKEMENT)
    rows = {row.item: row for row in scoring.rows}
    # One measure: shown in the item's row, coloured by the EA's status (Fish was Poor in 2022), as on the original.
    assert "Fish" not in rows
    assert rows["Fish (EQR)"].by_year[2022] == figures.Cell("0.36", "Poor")
    assert rows["Fish (EQR)"].by_year[2019] == figures.Cell("Poor", "Poor")  # no value that year: the EA's status
    assert rows["Fish (EQR)"].thresholds["good"] == 0.4
    # Several measures: the item's row of statuses, then a row for each, coloured by its own status.
    items = [row.item for row in scoring.rows]
    assert items.index("Invertebrates") + 1 == items.index("Inverts NTAXA (EQR)")
    assert rows["Inverts NTAXA (EQR)"].by_year[2022] == figures.Cell("0.97", "High")
    assert rows["Phosphate (mg/l)"].latest.text == "0.057"
    assert items[-1] == "Something else"  # not on the original: at the bottom
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert '<td class="status-poor">0.36</td>' in page
    assert '<td class="status-good">0.40</td>' in page  # a threshold


@pytest.mark.parametrize("value, shown", [(0.36, "0.36"), (0.2, "0.20"), (100, "100.00"), (0.057, "0.057"), (89.69, "89.69")])
def test_measured_values_have_at_least_two_decimal_places(value, shown):
    assert figures.measured(value) == shown


def test_land_use_shows_farms_livestock_and_phosphate(database, tmp_path):
    insert(database, "farms", [{"catchment_id": WEST_OKEMENT, "number_of_farms": 68}])
    insert(database, "livestock", [{"catchment_id": WEST_OKEMENT, "livestock": "Sheep", "number": 5558, "density_rating": "Medium"}])
    insert(database, "habitat_land_use", [{"catchment_id": WEST_OKEMENT, "habitat": "Woodland", "area_ha": 500, "relative_coverage": "High"}])
    insert(database, "phosphate_sources", [
        {"catchment_id": WEST_OKEMENT, "source": source, "year": year, "percent": percent, "discharge": discharge}
        for year in (2025, 2030)
        for source, percent, discharge in [("STW (SWW)", 60.9, "Continuous"), ("Livestock", 29.1, "Diffuse"), ("Arable", 10.0, "diffuse")]
    ])
    location = gather(database)
    area = next(c["area_ha"] for c in location.catchments if c["id"] == WEST_OKEMENT)
    page = (publish(database, tmp_path) / "land-use" / WEST_OKEMENT / "index.html").read_text()
    assert "Number of Farms: 68" in page
    assert f">{5558 / (area / 100):,.1f}</td>" in page  # sheep per km²
    assert "<td>High</td>" in page  # relative coverage
    assert '<th scope="col" data-type="number" class="num">2030 (%)</th>' in page
    years, groups = figures.Figures(location).phosphate_discharges(WEST_OKEMENT)
    assert years == [2025, 2030]
    assert groups == [("Continuous", {2025: 60.9, 2030: 60.9}), ("Diffuse", {2025: 39.1, 2030: 39.1})]


def test_sewerage_shows_the_properties_plans_and_location_text(database, tmp_path):
    insert(database, "sewerage_properties", [{"catchment_id": WEST_OKEMENT, "public_sewerage_properties": 310, "private_sewerage_properties": 467}])
    insert(database, "sewerage_improvements", [{"catchment_id": WEST_OKEMENT, "site_name": "HIGH BICKINGTON STW", "completion_year": 2035}])
    insert(database, "location_text", [{"location_id": location_id(database), "intermittent_discharges": "When it rains.",
                                        "about_waterbody_dashboard": "Email someone@example.org"}])
    location = gather(database)
    area = next(c["area_ha"] for c in location.catchments if c["id"] == WEST_OKEMENT)
    page = (publish(database, tmp_path) / "sewerage" / WEST_OKEMENT / "index.html").read_text()
    assert "<dt>Properties on Private Sewerage:</dt><dd>467</dd>" in page
    assert f"<dd>{467 / area:.2f}</dd>" in page
    assert "<td>HIGH BICKINGTON STW</td>" in page
    assert "<p>When it rains.</p>" in page
    assert 'Email <a href="mailto:someone@example.org">someone@example.org</a>' in page  # the text under the dashboard


def test_the_catchment_dashboard_adds_up_the_location(database, tmp_path):
    insert(database, "farms", [{"catchment_id": WEST_OKEMENT, "number_of_farms": 68}])
    insert(database, "habitat_land_use", [
        {"catchment_id": WEST_OKEMENT, "habitat": "Woodland", "area_ha": 500},
        {"catchment_id": EAST_OKEMONT, "habitat": "Woodland", "area_ha": 100},
    ])
    insert(database, "location_text", [{"location_id": location_id(database), "why_failing": "Most rivers are failing."}])
    numbers = figures.Figures(gather(database))
    areas = numbers.areas()
    assert [(a.kind, a.slug) for a in areas] == [("management", ""), ("operational", "torridge")]  # North Devon is the whole location
    ids = [WEST_OKEMENT, EAST_OKEMONT]
    assert numbers.class_counts(ids) == [("High", None), ("Good", None), ("Moderate", None), ("Poor", 1), ("Bad", None)]
    assert numbers.total("farms", "number_of_farms", ids) == figures.Total(68, 1, 2)
    habitat, covered = numbers.habitat_totals(ids)
    assert habitat[0]["area_ha"] == 600 and covered.known == 2

    folder = publish(database, tmp_path)
    page = (folder / "catchment-dashboard" / "index.html").read_text()
    assert '<a href="../catchment-dashboard/" aria-current="page">North Devon</a>' in page
    assert '<a href="../catchment-dashboard/torridge/">Torridge</a>' in page
    assert "Number of Farms: 68 <small" in page and "(1 of 2 waterbodies)" in page
    assert "<p>Most rivers are failing.</p>" in page
    assert 'data-geojson="../catchments.geojson?v=' in page and "data-links" not in page  # its catchments can't be clicked
    page = (folder / "catchment-dashboard" / "torridge" / "index.html").read_text()
    assert '<a href="../../catchment-dashboard/torridge/" aria-current="page">Torridge</a>' in page
    assert f'data-focus="{WEST_OKEMENT},{EAST_OKEMONT}"' in page or f'data-focus="{EAST_OKEMONT},{WEST_OKEMENT}"' in page


def test_catchment_insights_shows_each_focus_areas_questions(database, tmp_path):
    folder = publish(database, tmp_path)  # North Devon's questions are in content/north-devon/
    page = (folder / "catchment-insights" / "index.html").read_text()
    assert page.count('role="tab"') == len(site.INSIGHT_AREAS)
    assert '<section class="focus-panel" role="tabpanel" id="funding-delivery"' in page
    assert "<h2>State of the catchment</h2>" in page and "<h3>Overall condition</h3>" in page
    assert "<summary>How many river water bodies are achieving Good Ecological Status?</summary>" in page
    assert "under development and is not fully populated" in page  # the note at the top, as on their pages
    assert "This section is under development." not in page  # every focus area has its questions
    assert (folder / "assets" / "tabs.js").is_file()


def test_catchment_insights_come_from_the_locations_file(database, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "CONTENT", tmp_path / "content")
    page = (publish(database, tmp_path / "out") / "catchment-insights" / "index.html").read_text()
    assert page.count("This section is under development.") == len(site.INSIGHT_AREAS)  # no file for it

    (tmp_path / "content" / "north-devon").mkdir(parents=True)
    path = tmp_path / "content" / "north-devon" / "catchment-insights.yaml"
    path.write_text('Fish:\n  title: Fish\n  groups:\n    - heading: Barriers\n      questions:\n'
                    '        - question: "How many?"\n          answer: "**About 400**"\n        - question: "Where?"\n')
    page = (publish(database, tmp_path / "out") / "catchment-insights" / "index.html").read_text()
    assert '<summary>How many?</summary>\n      <div class="answer"><p><strong>About 400</strong></p></div>' in page
    assert '<summary>Where?</summary>\n      <div class="answer"></div>' in page  # no answer yet
    assert page.count("This section is under development.") == len(site.INSIGHT_AREAS) - 1

    path.write_text("Fishes:\n  title: Fish\n")  # not a focus area's name
    with pytest.raises(PublishProblem, match="focus areas that aren't on Catchment Insights: Fishes"):
        publish(database, tmp_path / "out")
    path.write_text("Fish:\n  groups:\n    - questions:\n        - answer: No question\n")
    with pytest.raises(PublishProblem, match="every question in Fish needs a 'question:' line"):
        publish(database, tmp_path / "out")


def test_intervention_management_shows_each_focus_area(database, tmp_path):
    here = location_id(database)
    insert(database, "location_text", [{
        "location_id": here, "critical_path": "**Starting Position (2025)**\n---\n**Step 1: Deliver**",
        "intervention_summary": "**What the analysis tells us**", "unit_costs_purpose": "**Purpose**",
        "community_action": "Walk your local river.",
    }])
    insert(database, "intervention_types", [
        {"location_id": here, "number": 1, "name": "Investment in STWs (phosphate reduction)", "button": "Sewage treatment works investment",
         "summary_group": "Priority interventions (not in order of priority)", "summary_rwbs": 2, "summary_cost": 6_000_000,
         "percent_available": 100, "percent_delivered": 0, "summary_lead": "SWW", "description": "Reduce phosphorus.",
         "lead_organisation": "South West Water", "progress": "- AMP8 is being delivered", "groups": "Highest Priority\nSecondary Priority"},
    ])
    insert(database, "intervention_types", [  # a separate insert, as it leaves columns out
        {"location_id": here, "number": 2, "name": "Fish data", "summary_group": "Secondary interventions",
         "summary_rwbs": 1, "summary_cost": 54_000, "percent_available": 0, "percent_delivered": None},
    ])
    insert(database, "intervention_waterbodies", [
        {"catchment_id": WEST_OKEMENT, "intervention": 1, "group_number": 2, "size": "AMP9", "estimated_cost": 3_000_000,
         "funding_available": 3_000_000, "finished_delivery": "2030-2035", "lead": "SWW"},
    ])
    insert(database, "intervention_waterbodies", [{"catchment_id": EAST_OKEMONT, "intervention": 1, "group_number": 1, "estimated_cost": 3_000_000, "lead": "SWW"}])
    insert(database, "intervention_waterbodies", [
        {"catchment_id": WEST_OKEMENT, "intervention": 2, "group_number": 1, "note": "abandoned mine", "estimated_cost": 6_000,
         "funding_available": 0, "lead": "WRT"},
    ])
    insert(database, "intervention_unit_costs", [
        {"location_id": here, "number": 1, "title": "Investment in Sewage Treatment Works", "delivery_lead": "South West Water",
         "typical_cost": "- Small works: £1m\n- Medium works: £3m"},
    ])
    numbers = figures.Figures(gather(database))
    priority, secondary = numbers.intervention_summary()
    assert (priority.name, priority.cost, priority.available, priority.to_find) == ("Priority interventions (not in order of priority)", 6_000_000, 6_000_000, 0)
    assert numbers.intervention_total().cost == 6_054_000 and numbers.intervention_total().to_find == 54_000
    assert [(heading, [row["catchment_id"] for row in rows]) for heading, rows in numbers.intervention_waterbodies(1)] == [
        ("Highest Priority", [EAST_OKEMONT]), ("Secondary Priority", [WEST_OKEMENT]),
    ]

    folder = publish(database, tmp_path)
    page = (folder / "intervention-management" / "index.html").read_text()
    assert "under development" not in page
    assert '<div class="focus-body"><p><strong>Starting Position (2025)</strong></p></div>' in page  # --- starts a new box
    assert '<div class="focus-body"><p><strong>Step 1: Deliver</strong></p></div>' in page
    assert "<h3>1. Investment in Sewage Treatment Works</h3>" in page and "<li>Medium works: £3m</li>" in page
    assert '<tr class="part"><th scope="colgroup" colspan="6">Secondary interventions</th></tr>' in page
    assert "<td class=\"c\">£6m</td>" in page and "<td class=\"c\">£54,000</td>" in page
    assert "<td class=\"c\">Data to follow</td>" in page  # no % delivered yet
    assert "Total: c.£6.0m, of which c.£6.0m available, and c.£0.0m to be found" in page
    assert "Overall total: c.£6.1m, of which c.£6.0m available, and c.£0.1m to be found" in page
    assert '<button type="button" role="tab" id="tab-intervention-1" aria-controls="intervention-1">1. Sewage treatment works investment</button>' in page
    assert '<button type="button" role="tab" id="tab-intervention-2" aria-controls="intervention-2">2. Fish data</button>' in page  # no button text: its name
    assert '<h4 class="group">Highest Priority</h4>' in page
    assert f'<a href="../river-status/{WEST_OKEMENT}/">West Okement</a> – abandoned mine' in page
    assert "<p>Walk your local river.</p>" in page


def test_tables_about_a_whole_location_only_have_its_own_row(database):
    with database.begin() as conn:
        other = conn.scalar(sa.text("INSERT INTO locations (name, catchment_ids) VALUES ('Elsewhere', :ids) RETURNING id"),
                            {"ids": [EAST_OKEMONT]})
    insert(database, "location_text", [
        {"location_id": location_id_of(database, "North Devon"), "why_failing": "North Devon's text"},
        {"location_id": other, "why_failing": "Elsewhere's text"},
    ])
    with database.connect() as conn:
        found = {row.name: collect.collect(conn, SCHEMA, row) for row in collect.locations(conn, SCHEMA)}
    assert figures.Figures(found["North Devon"]).location_text()["why_failing"] == "North Devon's text"
    assert figures.Figures(found["Elsewhere"]).location_text()["why_failing"] == "Elsewhere's text"


def location_id_of(engine, name):
    with engine.connect() as conn:
        return conn.scalar(sa.text("SELECT id FROM locations WHERE name = :name"), {"name": name})


@pytest.mark.parametrize("text, html", [
    ("One line", "<p>One line</p>"),
    ("Two\nlines", "<p>Two<br>\nlines</p>"),
    ("A\n\nB", "<p>A</p>\n<p>B</p>"),
    ("Groups:\n• One – 27\n- Two\n* Three", "<p>Groups:</p>\n<ul>\n<li>One – 27</li>\n<li>Two</li>\n<li>Three</li>\n</ul>"),
    ("-27 degrees", "<p>-27 degrees</p>"),  # a dash with no space isn't a list
    ("- A\n  - inside A\n  - > 0.03 = High", "<ul>\n<li>A\n<ul>\n<li>inside A</li>\n<li>&gt; 0.03 = High</li>\n</ul>\n</li>\n</ul>"),
    ("**Bold** and [a link](https://example.org)", '<p><strong>Bold</strong> and <a href="https://example.org">a link</a></p>'),
    ("Email a@example.org or see https://example.org",
     '<p>Email <a href="mailto:a@example.org">a@example.org</a> or see <a href="https://example.org">https://example.org</a></p>'),
    ("> In a grey box", "<blockquote>\n<p>In a grey box</p>\n</blockquote>"),
    ("a < b <b>c</b>", "<p>a &lt; b &lt;b&gt;c&lt;/b&gt;</p>"),  # typed HTML is shown as typed
    ("[x](javascript:alert(1))", "<p>[x](javascript:alert(1))</p>"),  # a link that would run a script isn't made
    ("C:\\Data\\File_Name_2025.xlsx\n    indented\n---", "<p>C:\\Data\\File_Name_2025.xlsx<br>\nindented<br>\n---</p>"),  # no other Markdown
    (None, ""),
])
def test_hand_written_text_becomes_paragraphs_and_lists(text, html):
    assert str(formatted(text)) == html


def test_hand_written_text_can_have_headings_and_sections_that_open_and_close():
    html = str(formatted("Intro\n\n## Understanding\n\nWhy\n\n### Left-hand panel\n\nOne\n\n#### Risk Levels\n\n"
                         "Two\n\n### River Status\n\n### EA Data\n\nThree\n\n## After\n\nEnd"))
    assert html == (
        "<p>Intro</p>\n<h2>Understanding</h2>\n<p>Why</p>\n"
        '<details class="section" open>\n<summary>Left-hand panel</summary>\n<div class="section-body">\n'
        "<p>One</p>\n<h4>Risk Levels</h4>\n<p>Two</p>\n</div>\n</details>\n"  # only the first section starts open
        '<details class="section">\n<summary>River Status</summary>\n<div class="section-body">\n</div>\n</details>\n'
        '<details class="section">\n<summary>EA Data</summary>\n<div class="section-body">\n<p>Three</p>\n</div>\n</details>\n'
        "<h2>After</h2>\n<p>End</p>"  # a ## heading ends the section before it
    )


def test_links_to_the_assets_change_when_the_files_do(database, tmp_path):
    """So browsers don't show an old stylesheet, script or map after a publish."""
    folder = publish(database, tmp_path)
    first = site.version(folder)
    assert f'href="../../assets/style.css?v={first}"' in (folder / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert site.version(publish(database, tmp_path)) == first  # nothing changed: browsers can keep their copies
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT]})
    assert site.version(publish(database, tmp_path)) != first  # the map changed


# --- The postcode search ------------------------------------------------------

def test_the_postcode_search_finds_the_catchment_each_postcode_is_in(database, tmp_path):
    folder = publish(database, tmp_path)  # no postcodes imported: no search
    page = (folder / "river-status" / WEST_OKEMENT / "index.html").read_text()
    assert "<h2>Click the map to select a river catchment</h2>" in page
    assert '<form class="postcode"' not in page and "Royal Mail" not in page
    assert not (folder / "postcodes").exists()

    insert(database, "postcodes", [
        {"postcode": "EX20 1AA", "catchment_id": WEST_OKEMENT, "latitude": 50.7, "longitude": -4.0},
        {"postcode": "EX20 1AB", "catchment_id": EAST_OKEMONT, "latitude": 50.7, "longitude": -3.9},
        {"postcode": "EX21 5AA", "catchment_id": WEST_OKEMENT, "latitude": 50.8, "longitude": -4.1},
    ])
    folder = publish(database, tmp_path)
    assert sorted(p.name for p in (folder / "postcodes").iterdir()) == ["EX20.json", "EX21.json"]  # a file per district
    assert json.loads((folder / "postcodes" / "EX20.json").read_text()) == {"1AA": WEST_OKEMENT, "1AB": EAST_OKEMONT}
    version = site.version(folder)
    for tab in site.TABS:
        page = (folder / tab / WEST_OKEMENT / "index.html").read_text()
        assert "<h2>Click the map to select a river catchment, or enter a postcode</h2>" in page
        assert f'data-postcodes="../../postcodes/" data-version="{version}" data-links="../../{tab}/"' in page  # stays on the tab
        assert f'data-selected="{WEST_OKEMENT}" data-selected-name="West Okement" data-location="North Devon"' in page
    page = (folder / "land-use" / "index.html").read_text()  # before a catchment is chosen
    assert 'data-postcodes="../postcodes/"' in page and 'data-selected="" data-selected-name=""' in page
    assert f'<script src="../assets/postcode.js?v={version}"></script>' in page
    assert "contains Royal Mail data © Royal Mail" in page  # the credit line Code-Point Open's licence asks for
    assert (folder / "assets" / "postcode.js").is_file()

    with database.begin() as conn:
        conn.execute(sa.text("UPDATE postcodes SET catchment_id = :id WHERE postcode = 'EX21 5AA'"), {"id": EAST_OKEMONT})
    assert site.version(publish(database, tmp_path)) != version  # browsers fetch the changed file again

    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT]})
    folder = publish(database, tmp_path)
    assert sorted(p.name for p in (folder / "postcodes").iterdir()) == ["EX20.json"]  # only the location's own catchments
    assert json.loads((folder / "postcodes" / "EX20.json").read_text()) == {"1AA": WEST_OKEMENT}


def test_the_catchments_can_be_chosen_by_name(database, tmp_path):
    folder = publish(database, tmp_path)
    page = (folder / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert '<div class="catchment-list" data-links="../../ea-data/">' in page  # stays on the tab, as the map does
    assert page.index(f'<option value="{EAST_OKEMONT}" data-group="Torridge">East Okemont River</option>') < page.index(
        f'<option value="{WEST_OKEMENT}" data-group="Torridge" selected>West Okement</option>')  # A to Z, with this one chosen
    assert '<option value="" disabled>Or choose from the list</option>' in page
    assert 'class="list-order"' not in page  # all in one operational catchment: nothing to group by
    assert f'<script src="../../assets/catchment-list.js?v={site.version(folder)}"></script>' in page
    page = (folder / "river-status" / "index.html").read_text()  # before a catchment is chosen
    assert '<option value="" disabled selected>Or choose from the list</option>' in page

    with database.begin() as conn:
        conn.execute(sa.text("UPDATE catchments SET operational_catchment = 'Taw' WHERE id = :id"), {"id": EAST_OKEMONT})
    page = (publish(database, tmp_path) / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert f'<option value="{EAST_OKEMONT}" data-group="Taw">' in page
    assert '<label><input type="radio" name="list-order" value="name" autocomplete="off" checked> A to Z</label>' in page
    assert '<label><input type="radio" name="list-order" value="area" autocomplete="off"> By area</label>' in page
