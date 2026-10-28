"""Reading and checking schema.yaml (no database needed)."""

import pytest

from catalyst.db.schema import SchemaError, load_schema

from .conftest import make_schema


CATCHMENTS = """
    tables:
      catchments:
        columns:
          id: {type: text, primary_key: true}
"""


def test_master_file_is_valid():
    schema = load_schema()
    assert {"catchments", "locations", "location_catchments", "datasets"} <= set(schema.metadata.tables)
    assert {"ea_scores", "habitat_land_use"} <= set(schema.data_tables)
    assert "postgis" in schema.extensions


def test_geometry_index_is_spatial():
    table = load_schema().metadata.tables["catchments"]
    index = next(i for i in table.indexes if i.columns.keys() == ["boundary"])
    assert index.dialect_options["postgresql"]["using"] == "gist"


def data_table(column: str) -> str:
    return CATCHMENTS + f"""
    data_tables:
      scores:
        columns:
          {column}
"""


def test_data_tables_must_link_every_row_to_a_catchment():
    schema = make_schema(data_table("catchment_id: {type: text, required: true, references: catchments.id}"))
    assert schema.data_tables == ["scores"]

    for bad in [
        "score: {type: double}",                                  # no catchment_id
        "catchment_id: {type: text, required: true}",             # not linked to catchments
        "catchment_id: {type: text, references: catchments.id}",  # not required
    ]:
        with pytest.raises(SchemaError, match="every data table needs a required 'catchment_id'"):
            make_schema(data_table(bad))


def test_all_mistakes_are_reported_together():
    with pytest.raises(SchemaError) as error:
        make_schema("""
            tables:
              things:
                colums: {}
              others:
                columns:
                  id: {type: integer, primary_key: true, required: false}
                  name: {type: txt}
                  code: {type: text, identity: true}
                  flag: {type: boolean, required: "yes"}
                  thing_id: {type: integer, references: thing.id}
                  owner_id: {type: integer, on_delete: cascade}
                  BadName: {type: text}
        """)
    problems = "\n".join(error.value.problems)
    for expected in [
        "tables.things: needs a 'columns' section",
        "tables.things: unknown option 'colums'",
        "others.columns.id: primary key columns are always required",
        "others.columns.name: unknown type 'txt'",
        "others.columns.code: 'identity' only works on integer columns",
        "others.columns.flag: 'required' must be true or false",
        "others.columns.thing_id: references unknown table 'thing'",
        "others.columns.owner_id: 'on_delete' only makes sense with 'references'",
        "others.columns.BadName: 'BadName' is not a valid name",
    ]:
        assert expected in problems


def test_duplicate_names_are_rejected(tmp_path):
    path = tmp_path / "schema.yaml"
    path.write_text(
        "tables:\n"
        "  things:\n"
        "    columns:\n"
        "      id: {type: integer, primary_key: true}\n"
        "      id: {type: text}\n"
    )
    with pytest.raises(SchemaError, match="'id' appears twice"):
        load_schema(path)
