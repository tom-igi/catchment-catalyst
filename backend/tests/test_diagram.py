"""The admin page's diagram of every table, made from the master schema file."""

import pytest
from fastapi.testclient import TestClient

from catalyst.admin import diagram
from catalyst.admin.app import _templates
from catalyst.db import load_schema
from catalyst.db.schema import build_schema

from .test_admin import app, client, page_model  # noqa: F401  (the logged-in admin page)

ONLY_DATA_TABLES_SECTION = """
sections: []
data_tables: {title: Data tables, description: One per dataset.}
"""


def render(model: dict, **context) -> str:
    """The admin page for a model, without the database."""
    return _templates().env.get_template("home.html").render({"model": model, "user": "tom", "message": None, **context})


def test_the_model_has_every_table_and_column():
    schema = load_schema()
    tables = {t["name"]: t for t in diagram.model(schema)["tables"]}
    assert set(tables) == set(schema.metadata.tables)
    for table in schema.metadata.tables.values():
        assert tables[table.name]["title"] == table.info["title"]
        assert [c["name"] for c in tables[table.name]["columns"]] == [c.name for c in table.columns]


def test_sections_come_in_the_order_of_diagram_yaml():
    sections = [s["title"] for s in diagram.model(load_schema())["sections"]]
    assert sections == ["Locations", "Catchments", "Datasets", "Uploads", "Data tables"]  # every core table has a section


def test_the_model_says_how_each_table_is_filled():
    tables = {t["name"]: t for t in diagram.model(load_schema())["tables"]}
    assert tables["catchments"]["fill"] == "api"
    assert tables["catchments"]["source"] == "Environment Agency, Catchment Data Explorer"
    assert tables["catchments"]["command"] == "docker compose run --rm importer catchments imports/catchments.json"
    assert tables["ea_scores"]["fill"] == "excel"
    assert (tables["uploads"]["fill"], tables["locations"]["fill"]) == ("admin", "command")
    assert all(t["fill"] in {"api", "excel"} for t in tables.values() if t["kind"] == "data")
    assert tables["locations"]["summary"].startswith("One row per dashboard location (e.g. North Devon): ")
    assert tables["ea_scores"]["one_row_per"] == ["Catchment ID", "Measure", "Year"]


def test_the_model_has_every_link():
    model = diagram.model(load_schema())
    links = {(l["from"], l["column"], l["to"], l["kind"]) for l in model["links"]}
    data_tables = [t["name"] for t in model["tables"] if t["kind"] == "data"]
    assert {(name, "catchment_id", "catchments", "id") for name in data_tables} <= links
    assert ("locations", "catchment_ids", "catchments", "list") in links
    assert {("datasets", "table_name", name, "name") for name in data_tables} <= links
    assert ("uploads", "table_name", "ea_scores", "name") in links


def test_a_mistake_in_diagram_yaml_is_reported(tmp_path):
    settings = tmp_path / "diagram.yaml"
    settings.write_text(ONLY_DATA_TABLES_SECTION.replace("sections: []", "sections: [{title: X, description: Y, tables: [nope]}]"))
    with pytest.raises(ValueError, match="lists nope, which isn't a core table"):
        diagram.model(load_schema(), diagram_file=settings)
    settings.write_text(ONLY_DATA_TABLES_SECTION + "filled: {nope: {how: admin}}\n")
    with pytest.raises(ValueError, match="has nope, which isn't in schema.yaml"):
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
