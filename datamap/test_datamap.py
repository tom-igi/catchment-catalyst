"""The data map page lists everything in the master schema file."""

import html

from catalyst.db import load_schema
from catalyst.db.schema import build_schema

from datamap import build


def test_page_shows_every_table_and_column(tmp_path):
    schema = load_schema()
    page = build(schema, tmp_path).read_text()
    for table in schema.metadata.tables.values():
        assert f'id="{table.name}"' in page
        assert html.escape(table.info["title"]) in page
        for column in table.columns:
            assert f"<code>{column.name}</code>" in page
    assert '<meta name="robots" content="noindex, nofollow">' in page


def test_text_from_the_schema_is_escaped(tmp_path):
    schema = build_schema({"tables": {"things": {
        "title": "Fish & <chips>",
        "columns": {"id": {"type": "integer", "primary_key": True, "example": "<b>1</b>"}},
    }}})
    page = build(schema, tmp_path).read_text()
    assert "Fish &amp; &lt;chips&gt;" in page
    assert "<b>1</b>" not in page
