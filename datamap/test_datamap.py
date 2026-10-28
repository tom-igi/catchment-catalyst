"""The data map page lists everything in the master schema file."""

import html

import pytest

from catalyst.db import load_schema
from catalyst.db.schema import build_schema

from datamap import build

ONLY_DATA_TABLES_SECTION = """
sections: []
data_tables: {title: Data tables, description: One per dataset.}
"""


def test_page_shows_every_table_and_column(tmp_path):
    schema = load_schema()
    page = build(schema, tmp_path).read_text()
    for table in schema.metadata.tables.values():
        assert f'id="{table.name}"' in page
        assert html.escape(table.info["title"]) in page
        for column in table.columns:
            assert f"<code>{column.name}</code>" in page
    assert '<meta name="robots" content="noindex, nofollow">' in page


def test_sections_come_in_the_order_of_sections_yaml(tmp_path):
    page = build(load_schema(), tmp_path).read_text()
    positions = [page.index(f"<h2>{title}</h2>") for title in ["Locations", "Catchments", "Datasets", "Data tables"]]
    assert positions == sorted(positions)
    assert "Other tables" not in page  # every core table has a section


def test_a_table_missing_from_the_schema_is_reported(tmp_path):
    sections = tmp_path / "sections.yaml"
    sections.write_text(ONLY_DATA_TABLES_SECTION.replace("sections: []", "sections: [{title: X, description: Y, tables: [nope]}]"))
    with pytest.raises(ValueError, match="lists nope, which isn't a core table"):
        build(load_schema(), tmp_path, sections)


def test_text_from_the_schema_is_escaped(tmp_path):
    sections = tmp_path / "sections.yaml"
    sections.write_text(ONLY_DATA_TABLES_SECTION)
    schema = build_schema({"tables": {"things": {
        "title": "Fish & <chips>",
        "columns": {"id": {"type": "integer", "primary_key": True, "example": "<b>1</b>"}},
    }}})
    page = build(schema, tmp_path, sections).read_text()
    assert "Fish &amp; &lt;chips&gt;" in page
    assert "<b>1</b>" not in page
    assert "<h2>Other tables</h2>" in page  # a table without a section still appears
