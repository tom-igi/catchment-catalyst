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
    assert {"catchments", "locations", "datasets"} <= set(schema.metadata.tables)
    assert list(schema.metadata.tables["locations"].columns.keys()) == ["id", "name", "catchment_ids"]
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


def test_list_types():
    from sqlalchemy.dialects import postgresql
    schema = make_schema(CATCHMENTS.replace(
        "id: {type: text, primary_key: true}",
        "id: {type: text, primary_key: true}\n          tags: {type: \"text[]\", index: true}",
    ))
    table = schema.metadata.tables["catchments"]
    assert isinstance(table.c.tags.type, postgresql.ARRAY)
    (index,) = table.indexes
    assert index.dialect_options["postgresql"]["using"] == "gin"
    with pytest.raises(SchemaError, match="lists of this type aren't supported"):
        make_schema(CATCHMENTS.replace("{type: text, primary_key: true}", '{type: "jsonb[]", primary_key: true}'))


def test_a_file_column():
    """bytea: a file, kept as it came (e.g. each upload's, in the uploads table)."""
    from sqlalchemy.dialects import postgresql
    schema = make_schema(CATCHMENTS.replace(
        "id: {type: text, primary_key: true}",
        "id: {type: text, primary_key: true}\n          photo: {type: bytea}",
    ))
    assert isinstance(schema.metadata.tables["catchments"].c.photo.type, postgresql.BYTEA)
    assert isinstance(load_schema().metadata.tables["uploads"].c.file.type, postgresql.BYTEA)
    with pytest.raises(SchemaError, match="lists of this type aren't supported"):
        make_schema(CATCHMENTS.replace("{type: text, primary_key: true}", '{type: "bytea[]", primary_key: true}'))


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


LOCATIONS = CATCHMENTS + """
      locations:
        columns:
          id: {type: integer, primary_key: true}
    data_tables:
      words:
        columns:
"""


def test_data_about_a_whole_location_is_linked_to_the_location():
    schema = make_schema(LOCATIONS + "          location_id: {type: integer, primary_key: true, references: locations.id}\n")
    assert schema.data_tables == ["words"]
    for bad in [
        "          location_id: {type: integer, references: locations.id}\n",  # not required
        "          location_id: {type: integer, primary_key: true, references: locations.id}\n"  # both
        "          catchment_id: {type: text, required: true, references: catchments.id}\n",
    ]:
        with pytest.raises(SchemaError, match="or \\(for data about a whole location\\) a required 'location_id'"):
            make_schema(LOCATIONS + bad)


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


def test_examples_are_a_row_each():
    schema = make_schema("""
        tables:
          things:
            columns:
              id: {type: integer, primary_key: true, example: [1, 2, 3]}
              name: {type: text, example: [Farmland, null, Urban]}
              note: {type: text}
          others:
            columns:
              id: {type: integer, primary_key: true, example: 7}
    """)
    things = schema.metadata.tables["things"]
    assert (things.c.id.info["example"], things.c.name.info["example"]) == ([1, 2, 3], ["Farmland", None, "Urban"])
    assert schema.metadata.tables["others"].c.id.info["example"] == 7  # one value: one row

    with pytest.raises(SchemaError) as error:
        make_schema("""
            tables:
              things:
                columns:
                  id: {type: integer, primary_key: true, example: [1, 2, 3]}
                  name: {type: text, example: [Farmland, Urban]}
              others:
                columns:
                  id: {type: integer, primary_key: true, example: [1, 2]}
                  name: {type: text, example: Farmland}
              more:
                columns:
                  id: {type: integer, primary_key: true, example: [[1], {a: 2}]}
        """)
    problems = "\n".join(error.value.problems)
    for expected in [
        "tables.things: every column's 'example' needs the same number of values",
        "tables.others: every column's 'example' needs the same number of values",
        "more.columns.id: 'example' must be a value, or a list of them (one for each example row)",
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


def test_which_tables_are_filled_by_excel():
    schema = load_schema()
    assert schema.excel_tables[:3] == ["datasets", "river_status_text", "intervention_types"]  # in the order of schema.yaml
    assert {"intervention_waterbodies", "location_text"} <= set(schema.excel_tables)
    assert not {"catchments", "ea_classifications", "storm_overflows"} & set(schema.excel_tables)
    assert schema.metadata.tables["catchments"].info["filled_by"] == "api"


def test_tables_filled_by_excel_must_suit_an_upload():
    with pytest.raises(SchemaError) as error:
        make_schema("""
            tables:
              things:
                filled_by: excel
                columns:
                  id: {type: integer, primary_key: true, identity: true}
                  shape: {type: "geometry(Point, 4326)"}
                  tags: {type: "text[]"}
                  score: {type: real}
              keyless:
                filled_by: excel
                columns:
                  name: {type: text}
              others:
                filled_by: spreadsheet
                columns:
                  name: {type: text}
        """)
    problems = "\n".join(error.value.problems)
    for expected in [
        "tables.things.columns.id: tables filled by Excel can't have numbered ('identity') columns",
        "tables.things.columns.shape: Excel uploads can only fill text, varchar(N), integer",
        "tables.things.columns.tags: Excel uploads can only fill",
        "tables.things.columns.score: Excel uploads can only fill",
        "tables.keyless: tables filled by Excel need a primary key",
        "tables.others: 'filled_by' must be one of: api, excel, input",
    ]:
        assert expected in problems


def test_tables_worked_out_from_a_source_file_say_which():
    schema = load_schema()
    assert schema.input_tables == {
        "waterbody_figures": "waterbody_lookup", "livestock": "apha_livestock", "livestock_pressure": "apha_livestock",
        "esme_risk_levels": "esme", "habitat_land_use": "habitat",
        "phosphate_sources": "sagis_phosphate",
        "phosphate_point_diffuse": "sagis_phosphate", "sewerage_improvements": "water_company_plans",
        "ea_scores": "ea_classification_facts", "ea_thresholds": "ea_classification_facts",
    }
    assert not set(schema.input_tables) & set(schema.excel_tables)  # not uploaded 1 to 1 as well
    with pytest.raises(SchemaError) as error:
        make_schema("""
            tables:
              unnamed:
                filled_by: input
                columns:
                  id: {type: integer, primary_key: true}
              misplaced:
                filled_by: excel
                input: apha_livestock
                columns:
                  id: {type: integer, primary_key: true}
              keyless:
                filled_by: input
                input: somewhere
                columns:
                  name: {type: text}
        """)
    problems = "\n".join(error.value.problems)
    for expected in [
        "tables.unnamed: tables with 'filled_by: input' need 'input'",
        "tables.misplaced: 'input' is only for tables with 'filled_by: input'",
        "tables.keyless: tables filled by Excel need a primary key",  # the same rules as an Excel upload
    ]:
        assert expected in problems
