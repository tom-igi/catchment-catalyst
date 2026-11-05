"""The data map page lists everything in the master schema file, behind the admin login.

Skipped if the optional catalyst/datamap folder has been removed.
"""

import html

import pytest
from fastapi.testclient import TestClient

from catalyst.db import load_schema
from catalyst.db.schema import build_schema

datamap = pytest.importorskip("catalyst.datamap")

from .test_admin import app, client  # noqa: E402, F401  (the logged-in admin page)

ONLY_DATA_TABLES_SECTION = """
sections: []
data_tables: {title: Data tables, description: One per dataset.}
"""


def test_page_shows_every_table_and_column():
    schema = load_schema()
    page = datamap.render(schema)
    for table in schema.metadata.tables.values():
        assert f'id="{table.name}"' in page
        assert html.escape(table.info["title"]) in page
        for column in table.columns:
            assert f"<code>{column.name}</code>" in page
    assert '<meta name="robots" content="noindex, nofollow">' in page
    assert "<strong>How it's filled:</strong> uploaded as an Excel file in the admin page." in page


def test_sections_come_in_the_order_of_sections_yaml():
    page = datamap.render(load_schema())
    positions = [page.index(f"<h2>{title}</h2>") for title in ["Locations", "Catchments", "Datasets", "Uploads", "Data tables"]]
    assert positions == sorted(positions)
    assert "Other tables" not in page  # every core table has a section


def test_a_table_missing_from_the_schema_is_reported(tmp_path):
    sections = tmp_path / "sections.yaml"
    sections.write_text(ONLY_DATA_TABLES_SECTION.replace("sections: []", "sections: [{title: X, description: Y, tables: [nope]}]"))
    with pytest.raises(ValueError, match="lists nope, which isn't a core table"):
        datamap.render(load_schema(), sections)


def test_text_from_the_schema_is_escaped(tmp_path):
    sections = tmp_path / "sections.yaml"
    sections.write_text(ONLY_DATA_TABLES_SECTION)
    schema = build_schema({"tables": {"things": {
        "title": "Fish & <chips>",
        "columns": {"id": {"type": "integer", "primary_key": True, "example": "<b>1</b>"}},
    }}})
    page = datamap.render(schema, sections)
    assert "Fish &amp; &lt;chips&gt;" in page
    assert "<b>1</b>" not in page
    assert "<h2>Other tables</h2>" in page  # a table without a section still appears


# --- In the admin page -----------------------------------------------------------

def test_the_admin_page_shows_the_data_map_after_logging_in(app, client):
    response = TestClient(app).get("/admin/data-map", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, "/admin/login")

    assert '<a href="/admin/data-map">Data map</a>' in client.get("/admin").text
    page = client.get("/admin/data-map")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert '<a class="back" href="/admin">← Admin</a>' in page.text
    for table in app.state.schema.metadata.tables.values():
        assert f'id="{table.name}"' in page.text
