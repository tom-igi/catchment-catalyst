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


def test_river_status_shows_the_text_risks_interventions_and_ranking(database, tmp_path):
    insert(database, "river_status_text", [{
        "catchment_id": WEST_OKEMENT, "why_failing": "Fish are poor.\n\nThe reasons:\n- Metals\n- Mining",
        "happening_now": "<b>Surveys</b>", "intervention_hypothesis": "Treat the mine water.", "hypothesis_confidence": "Med-High",
    }])
    insert(database, "risk_levels", [{"catchment_id": WEST_OKEMENT, "untreated_sewage": "Very High", "running_dry": "Low"}])
    insert(database, "catchment_rankings", [{"catchment_id": WEST_OKEMENT, "ranking": 7}])
    insert(database, "interventions", [
        {"catchment_id": WEST_OKEMENT, "number": 2, "priority": "Contingency", "desired_change": "Fish passage", "lead_partner": "WRT"},
        {"catchment_id": WEST_OKEMENT, "number": 3, "priority": "Primary", "desired_change": "Less metal", "lead_partner": "EA"},
    ])
    page = (publish(database, tmp_path) / "river-status" / WEST_OKEMENT / "index.html").read_text()
    assert "<p>Fish are poor.</p>\n<p>The reasons:</p>\n<ul><li>Metals</li><li>Mining</li></ul>" in page
    assert "&lt;b&gt;Surveys&lt;/b&gt;" in page  # text is shown as typed, never as HTML
    assert "Intervention hypothesis (confidence: Med-High)" in page
    assert '<li class="risk-very-high"><span class="risk-name">Untreated Sewage</span><span class="risk-level">Very High</span></li>' in page
    assert '<li class="risk-none"><span class="risk-name">Modification</span><span class="risk-level"></span></li>' in page
    assert "Catchment Ranking: 7/2" in page  # of the location's 2 rivers
    assert page.index("PRIMARY INTERVENTIONS") < page.index("Less metal") < page.index("CONTINGENCY INTERVENTIONS") < page.index("Fish passage")
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
                                        "contact_email": "someone@example.org"}])
    location = gather(database)
    area = next(c["area_ha"] for c in location.catchments if c["id"] == WEST_OKEMENT)
    page = (publish(database, tmp_path) / "sewerage" / WEST_OKEMENT / "index.html").read_text()
    assert "<dt>Properties on Private Sewerage:</dt><dd>467</dd>" in page
    assert f"<dd>{467 / area:.2f}</dd>" in page
    assert "<td>HIGH BICKINGTON STW</td>" in page
    assert "<p>When it rains.</p>" in page
    assert '<a href="mailto:someone@example.org">' in page


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
    assert numbers.failing(ids) == 1
    assert numbers.total("farms", "number_of_farms", ids) == figures.Total(68, 1, 2)
    habitat, covered = numbers.habitat_totals(ids)
    assert habitat[0]["area_ha"] == 600 and covered.known == 2

    folder = publish(database, tmp_path)
    page = (folder / "catchment-dashboard" / "index.html").read_text()
    assert '<a href="../catchment-dashboard/" aria-current="page">North Devon</a>' in page
    assert '<a href="../catchment-dashboard/torridge/">Torridge</a>' in page
    assert "Number of Farms: 68 <small" in page and "(1 of 2 waterbodies)" in page
    assert "<p>Most rivers are failing.</p>" in page
    assert 'data-links="../river-status/"' in page  # clicking a catchment opens it in the Waterbody Dashboard
    page = (folder / "catchment-dashboard" / "torridge" / "index.html").read_text()
    assert '<a href="../../catchment-dashboard/torridge/" aria-current="page">Torridge</a>' in page
    assert f'data-focus="{WEST_OKEMENT},{EAST_OKEMONT}"' in page or f'data-focus="{EAST_OKEMONT},{WEST_OKEMENT}"' in page


def test_the_placeholder_views_show_their_focus_areas(database, tmp_path):
    folder = publish(database, tmp_path)
    page = (folder / "intervention-management" / "index.html").read_text()
    assert page.count('role="tab"') == len(site.INTERVENTION_AREAS)
    assert "Starting Position (2022)" in page and "<li>1 Failing</li>" in page
    page = (folder / "catchment-insights" / "index.html").read_text()
    assert '<section class="focus-panel" role="tabpanel" id="funding-delivery"' in page
    assert (folder / "assets" / "tabs.js").is_file()


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
    ("Two\nlines", "<p>Two<br>lines</p>"),
    ("A\n\nB", "<p>A</p>\n<p>B</p>"),
    ("Groups:\n• One – 27\n- Two\n* Three", "<p>Groups:</p>\n<ul><li>One – 27</li><li>Two</li><li>Three</li></ul>"),
    ("-27 degrees", "<p>-27 degrees</p>"),  # a dash with no space isn't a list
    ("a < b", "<p>a &lt; b</p>"),
    (None, ""),
])
def test_hand_written_text_becomes_paragraphs_and_lists(text, html):
    assert str(site._paragraphs(text)) == html


def test_links_to_the_assets_change_when_the_files_do(database, tmp_path):
    """So browsers don't show an old stylesheet, script or map after a publish."""
    folder = publish(database, tmp_path)
    first = site.version(folder)
    assert f'href="../../assets/style.css?v={first}"' in (folder / "ea-data" / WEST_OKEMENT / "index.html").read_text()
    assert site.version(publish(database, tmp_path)) == first  # nothing changed: browsers can keep their copies
    with database.begin() as conn:
        conn.execute(sa.text("UPDATE locations SET catchment_ids = :ids"), {"ids": [WEST_OKEMENT]})
    assert site.version(publish(database, tmp_path)) != first  # the map changed
