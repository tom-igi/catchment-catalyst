"""The admin page's diagram of every table, made from the master schema file."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catalyst.admin import diagram
from catalyst.admin.app import _templates
from catalyst.db import load_schema
from catalyst.db.schema import build_schema

from .test_admin import app, client, page_model  # noqa: F401  (the logged-in admin page)

SCREENSHOTS_DIR = Path(diagram.__file__).with_name("screenshots")

ONLY_DATA_TABLES_SECTION = """
sections: []
data_tables: {title: Data tables, description: One per dataset.}
"""


def render(model: dict, **context) -> str:
    """The admin page for a model, without the database."""
    publishing = {"last": None, "waiting": 0, "tables": []}  # the Publish box, before any publish
    return _templates().env.get_template("home.html").render(
        {"model": model, "user": "tom", "message": None, "publishing": publishing, **context}
    )


def test_the_model_has_every_table_and_column():
    schema = load_schema()
    tables = {t["name"]: t for t in diagram.model(schema)["tables"]}
    assert set(tables) == set(schema.metadata.tables)
    for table in schema.metadata.tables.values():
        assert tables[table.name]["title"] == table.info["title"]
        assert [c["name"] for c in tables[table.name]["columns"]] == [c.name for c in table.columns]


def test_sections_come_in_the_order_of_diagram_yaml():
    sections = [s["title"] for s in diagram.model(load_schema())["sections"]]
    assert sections == ["Locations", "Catchments", "Datasets", "Uploads", "Publishes", "Data tables"]  # every core table has a section


def test_the_model_says_how_each_table_is_filled():
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    assert tables["catchments"]["fill"] == "api"
    assert tables["catchments"]["source"] == "EA Catchment Data Explorer"
    assert tables["catchments"]["url"] == "https://environment.data.gov.uk/catchment-planning/"
    assert all(t["url"].startswith("https://") for t in tables.values() if t["fill"] == "api")  # each has a web page
    # Tables downloaded by the same command share one box on the page.
    assert tables["ea_classifications"]["command"] == tables["ea_rnags"]["command"] != tables["catchments"]["command"]
    assert tables["catchments"]["command"] == "docker compose run --rm importer catchments imports/catchments.json"
    assert tables["ea_scores"]["fill"] == "input" and tables["location_text"]["fill"] == "excel"
    assert (tables["uploads"]["fill"], tables["publishes"]["fill"], tables["locations"]["fill"]) == ("admin", "admin", "command")
    assert all(t["fill"] in {"api", "input", "excel"} for t in tables.values() if t["kind"] == "data")
    # Tables worked out from the same source file share one box on the page, too.
    assert tables["livestock"]["fill"] == tables["livestock_pressure"]["fill"] == "input"
    assert tables["livestock"]["input"] == tables["livestock_pressure"]["input"] == "apha_livestock"
    assert tables["locations"]["summary"].startswith("One row per dashboard location (e.g. North Devon): ")
    assert tables["ea_scores"]["one_row_per"] == ["Catchment ID", "Measure", "Year"]


def test_the_model_says_what_each_table_holds():
    model = diagram.model(load_schema())
    tables = {t["name"]: t for t in model["tables"]}
    # As downloaded (an importer's), worked out (a source file's, or an importer's that adds them up) or typed in (Excel).
    assert (tables["ea_classifications"]["holds"], tables["catchments"]["holds"]) == ("downloaded", "downloaded")
    assert tables["sewage_overflow_pressure"]["holds"] == "worked_out"  # added up from the storm overflow returns
    assert (tables["waterbody_figures"]["holds"], tables["river_status_text"]["holds"]) == ("worked_out", "worked_out")
    assert (tables["location_text"]["holds"], tables["datasets"]["holds"]) == ("typed", "typed")
    assert (tables["uploads"]["holds"], tables["locations"]["holds"]) == (None, None)  # no data comes into them
    assert [h["label"] for h in model["holds"]] == ["As downloaded", "Worked out", "Typed in"]
    assert all(t["holds"] for t in tables.values() if t["kind"] == "data")


def test_the_model_says_what_happens_to_the_data_on_the_way_in():
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    # Each importer says what it does to its downloads, in a few steps...
    for t in tables.values():
        if t["fill"] == "api":
            assert t["transformation"] and all(isinstance(step, str) and step.endswith(".") for step in t["transformation"]), t["name"]
    assert "#N/A" in " ".join(tables["storm_overflows"]["transformation"])  # not cut off as a YAML comment
    # ...Excel uploads are copied 1 to 1...
    assert all(t["transformation"] == [] for t in tables.values() if t["fill"] == "excel")
    # ...and a source file's tables are worked out with the original Power BI dashboard's formulas.
    sources = {i["name"]: i for i in diagram.model(load_schema())["inputs"]}
    assert sources["waterbody_lookup"]["tables"] == ["waterbody_figures"]
    assert sources["apha_livestock"]["headings"][0] == "Catchment Name" and sources["apha_livestock"]["sheet"] == "Appendix 1 EIR2026_00630"


def test_each_table_has_its_own_transformation():
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    # A source file's: its inputs (the file's columns it reads), and a step for each of its columns, as the Power BI did.
    pressure = tables["livestock_pressure"]["transform"]
    assert (pressure["kind"], pressure["name"], pressure["sub"]) == ("input", "Power BI's formulas", "6 columns in, 5 steps")
    assert (pressure["file"], pressure["sheet"]) == ("APHA Livestock Data Feb 2026.xlsx", "Appendix 1 EIR2026_00630")
    assert pressure["inputs"][0] == "Catchment Name" and "Pig Density Per SqKm" in pressure["inputs"]
    assert [step["columns"] for step in pressure["steps"]] == [
        ["catchment_id"], ["nitrogen_load"], ["phosphate_load"], ["nitrogen_and_phosphate_load"], ["pressure"],
    ]
    assert pressure["steps"][3]["inputs"] == ["nitrogen_load", "phosphate_load"]  # columns worked out before
    assert "Very High above 40,000" in pressure["steps"][-1]["text"] and pressure["steps"][-1]["power_bi"]
    assert tables["phosphate_point_diffuse"]["transform"]["sheet"] == "Phosphate Point vs Diffuse"  # its own sheet
    # An importer's: what it downloads, and its steps.
    rnags = tables["ea_rnags"]["transform"]
    assert (rnags["kind"], rnags["name"], rnags["file"]) == ("api", "Reshaped", "The EA's rnags.csv for each management catchment")
    assert "Swmi" in rnags["inputs"] and rnags["steps"][0]["text"].startswith("Downloads")
    # An Excel table's: 1 to 1. Housekeeping: none.
    assert tables["location_text"]["transform"]["name"] == "1 to 1"
    assert tables["uploads"]["transform"] is None
    for t in tables.values():  # every table data comes into has one
        assert (t["transform"] is not None) == (t["fill"] in {"api", "input", "excel"}), t["name"]


def test_the_model_says_where_each_data_table_is_on_the_dashboards():
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    for t in tables.values():
        if t["kind"] == "data":  # every one is somewhere, so a new table needs adding to diagram.yaml
            assert t["dashboard"] and all(place["panels"] for place in t["dashboard"]), t["name"]
    assert tables["datasets"]["dashboard"] == [{"page": "Every dashboard page", "panels": ['"i" info buttons']}]
    assert tables["catchments"]["dashboard"] == []
    # A panel's name can be on more than one page, from different tables: the page tells them apart.
    assert {"page": "River Status", "panels": ["Why is the river failing?", "What is happening now?", "Intervention hypothesis"]} \
        in tables["river_status_text"]["dashboard"]
    assert "Intervention hypothesis" in {panel for place in tables["location_text"]["dashboard"] if place["page"] == "Catchment Dashboard"
                                         for panel in place["panels"]}
    # A panel with data from several tables is listed for each, in the dashboards' order.
    for name in ["ea_classifications", "ea_scores", "ea_thresholds"]:
        assert {"page": "EA Data", "panels": ["Environment Agency Scoring"]} in tables[name]["dashboard"]
    # The Risk Levels tiles: each table that has some of them, on the pages it's on.
    assert [place["page"] for place in tables["sewage_overflow_pressure"]["dashboard"]] == ["River Status", "Sewerage Data"]
    assert "risk_levels" not in tables  # its tiles are all in the tables they're worked out in
    assert [place["page"] for place in tables["esme_risk_levels"]["dashboard"]] == ["River Status", "Land Use Data"]


def test_each_table_on_the_dashboards_has_a_number():
    """As on the numbered screenshots of the dashboards, so a number seen there can be found on the diagram."""
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    for t in tables.values():
        if t["dashboard"]:  # a new table on the dashboards needs one in diagram.yaml
            assert isinstance(t["number"], int), t["name"]
    numbers = [t["number"] for t in tables.values() if t["number"] is not None]
    assert len(numbers) == len(set(numbers))
    assert (tables["catchments"]["number"], tables["locations"]["number"]) == (1, 24)  # the waterbodies, and which are shown
    assert tables["uploads"]["number"] is None  # not on the dashboards


def test_the_model_has_every_link():
    model = diagram.model(load_schema())
    links = {(l["from"], l["column"], l["to"], l["kind"]) for l in model["links"]}
    data_tables = [t["name"] for t in model["tables"] if t["kind"] == "data"]
    by_catchment = [t["name"] for t in model["tables"] if t["kind"] == "data" and any(c["name"] == "catchment_id" for c in t["columns"])]
    by_location = {"location_text", "intervention_types", "intervention_unit_costs"}  # about a whole location
    assert set(data_tables) - set(by_catchment) == by_location
    assert {(name, "catchment_id", "catchments", "id") for name in by_catchment} <= links
    assert {(name, "location_id", "locations", "id") for name in by_location} <= links
    assert ("locations", "catchment_ids", "catchments", "list") in links
    assert {("datasets", "table_name", name, "name") for name in data_tables} <= links
    assert ("uploads", "uploaded_to", "location_text", "name") in links


def test_a_mistake_in_diagram_yaml_is_reported(tmp_path):
    settings = tmp_path / "diagram.yaml"
    settings.write_text(ONLY_DATA_TABLES_SECTION.replace("sections: []", "sections: [{title: X, description: Y, tables: [nope]}]"))
    with pytest.raises(ValueError, match="lists nope, which isn't a core table"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {nope: {how: admin}}\n")
    with pytest.raises(ValueError, match="has nope, which isn't in schema.yaml"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {catchments: {source: EA, url: 'javascript:alert(1)'}}\n")
    with pytest.raises(ValueError, match="should start with https://"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {catchments: {transformation: {Downloads: it}}}\n")
    with pytest.raises(ValueError, match="a transformation that isn't a list of steps"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {uploads: {how: admin, worked_out: true}}\n")
    with pytest.raises(ValueError, match="gives uploads worked_out: True, but it can only be true, for a table filled by an importer"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {catchments: {inputs: WB_NAME}}\n")
    with pytest.raises(ValueError, match="inputs that aren't a list of column names"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "dashboard: {River Status: {Risk Levels: [esme_risk_levels, nope]}}\n")
    with pytest.raises(ValueError, match="gives River Status's Risk Levels panel the table nope, which isn't in schema.yaml"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "dashboard: {River Status: [Risk Levels]}\n")
    with pytest.raises(ValueError, match="should list each page, then each panel on it"):
        diagram.model(load_schema(), diagram_file=settings)
    for numbers, problem in [
        ("{nope: 1}", "has nope, which isn't in schema.yaml"),
        ("{catchments: 1, locations: 1}", "gives catchments and locations the same number, 1"),
        ("{catchments: one}", "gives catchments the number one, which isn't a whole number from 1 up"),
        ("{catchments: 0}", "gives catchments the number 0, which isn't a whole number from 1 up"),
        ("[catchments]", "should give each table its number"),
    ]:
        settings.write_text(ONLY_DATA_TABLES_SECTION + f"numbers: {numbers}\n")
        with pytest.raises(ValueError, match=problem):
            diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "dashboard: {River Status: {Risk Levels: esme_risk_levels}}\nnumbers: {livestock: 1}\n")
    with pytest.raises(ValueError, match="has no number for esme_risk_levels, which is on the dashboards"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "links: [{from: locations.nope, to: catchments}]\n")
    with pytest.raises(ValueError, match="has locations.nope, which isn't in schema.yaml"):
        diagram.model(load_schema(), diagram_file=settings)


def test_text_from_the_schema_cant_break_the_page(tmp_path):
    sections = tmp_path / "diagram.yaml"
    sections.write_text(ONLY_DATA_TABLES_SECTION)
    title = "Fish & </script><b>chips</b>"
    schema = build_schema({"tables": {"things": {
        "title": title,
        "columns": {"id": {"type": "integer", "primary_key": True, "example": "<b>1</b>"}},
    }}})
    page = render(diagram.model(schema, diagram_file=sections), message="<i>Done</i>")
    assert "</script><b>" not in page and "<i>Done</i>" not in page
    model = page_model(page)
    assert model["tables"][0]["title"] == title  # the page shows it as text
    assert model["sections"][0]["title"] == "Other tables"  # a table without a section still appears


# --- In the admin page -----------------------------------------------------------

def test_the_admin_page_is_the_diagram(app, client):
    response = TestClient(app).get("/admin", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/admin/login")

    page = client.get("/admin")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert '<meta name="robots" content="noindex, nofollow">' in page.text
    assert "<h1>Your data</h1>" in page.text and "Logged in as <strong>tom</strong>" in page.text
    rows = {t["name"]: t["rows"] for t in page_model(page.text)["tables"]}
    assert set(rows) == set(app.state.schema.metadata.tables)
    assert rows["catchments"] == 2
    assert {t["name"]: t["number"] for t in page_model(page.text)["tables"]}["catchments"] == 1  # each box shows it
    # How the data tables are split, from diagram.yaml, and what each box's label (e.g. Worked out) means.
    assert '<h2 id="split-title">How the data tables are split</h2>' in page.text
    assert "<p>Each table is filled from one place only: a download, a source file or an Excel upload." in page.text
    assert "<dt>Worked out</dt><dd>Only what the dashboards show," in page.text
    assert 'href="/admin/screenshots"' in page.text


# --- The numbered screenshots of the dashboards ------------------------------------

def test_the_screenshots_have_each_tables_number_now():
    """screenshots/take.mjs put each table's number on them: if diagram.yaml gives a table another number, or a
    screenshot is missing, take them again (screenshots/README.md)."""
    taken = json.loads((SCREENSHOTS_DIR / "screenshots.json").read_text())
    numbers = {t["name"]: t["number"] for t in diagram.model(load_schema())["tables"]}
    shown = set()
    for shot in taken["shots"]:
        assert (SCREENSHOTS_DIR / shot["file"]).is_file(), shot["file"]
        for n in shot["numbers"]:
            assert numbers.get(n["table"]) == n["number"], (shot["file"], n)
            shown.add(n["table"])
    assert shown == {name for name, number in numbers.items() if number is not None}  # every numbered table is on one


def test_the_screenshots_page(app, client):
    page = client.get("/admin/screenshots")
    assert page.status_code == 200
    assert "<h1>Where each part of the dashboard comes from</h1>" in page.text
    assert 'src="/admin/screenshots/1-river-status.webp"' in page.text and "These screenshots are out of date" not in page.text
    # Under each one, each number: its table (on the diagram) and where to update it.
    assert '<a class="key-table" href="/admin#waterbody_figures"><span class="visually-hidden">Table 13: </span>Waterbody Figures</a>' in page.text
    assert '<a class="key-update" href="/admin#upload-waterbody_lookup">Upload file: Waterbody Lookup</a>' in page.text
    assert '<a class="key-update" href="/admin#upload-location_text">Upload data (in Excel)</a>' in page.text
    assert '<a class="key-update" href="/admin#from-ea_rnags">Downloaded from EA Catchment Data Explorer</a>' in page.text
    assert '<a class="key-update" href="/admin#locations">Changed with a database command</a>' in page.text

    image = client.get("/admin/screenshots/1-river-status.webp")
    assert (image.status_code, image.headers["content-type"]) == (200, "image/webp")
    assert image.content[:4] == b"RIFF" and image.content[8:12] == b"WEBP"
    for name in ["nope.webp", "screenshots.json", "take.mjs", "..%2Fapp.py"]:
        assert client.get(f"/admin/screenshots/{name}").status_code == 404, name


def test_the_screenshots_page_says_when_theyre_out_of_date(app, client, tmp_path):
    app.state.screenshots_dir = tmp_path
    assert "There are no screenshots yet" in client.get("/admin/screenshots").text
    (tmp_path / "screenshots.json").write_text(json.dumps({
        "taken": "2026-11-18", "dashboard": "http://localhost:8080/north-devon/", "waterbody": {"id": "X", "name": "Somewhere"},
        "shots": [{"file": "a.webp", "title": "A page", "url": "a/", "note": None, "width": 10, "height": 10,
                   "numbers": [{"number": 1, "table": "catchments", "what": ["Map"]},
                               {"number": 40, "table": "farms", "what": ["Number of Farms"]}]}],
    }))
    page = client.get("/admin/screenshots").text
    assert "These screenshots are out of date." in page and "Number 40 on them" in page
    assert "Taken 18 November 2026 from http://localhost:8080/north-devon/, showing Somewhere." in page
