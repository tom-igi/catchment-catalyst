"""Applying schema changes to a real database. Each test gets an empty database."""

import pytest
import sqlalchemy as sa

from catalyst.db.schema import load_schema
from catalyst.db.sync import DataLossError, PlanChangedError, apply_changes, plan_changes

from .conftest import make_schema

THINGS = """
    tables:
      things:
        description: Things
        columns:
          id: {type: integer, primary_key: true, identity: true}
          name: {type: text, required: true}
"""


def setup_things(engine, rows=("a", "b")):
    apply_changes(engine, make_schema(THINGS))
    with engine.begin() as conn:
        for name in rows:
            conn.execute(sa.text("INSERT INTO things (name) VALUES (:n)"), {"n": name})


def names(engine, column="name", table="things"):
    with engine.connect() as conn:
        return conn.scalars(sa.text(f"SELECT {column} FROM {table} ORDER BY id")).all()


def test_master_schema_applies_cleanly_and_is_then_up_to_date(engine):
    schema = load_schema()
    plan = apply_changes(engine, schema)
    assert plan.summaries[0] == "add extension postgis"
    assert not plan.data_loss
    assert plan_changes(engine, schema).changes == []


def test_plan_changes_nothing(engine):
    plan = plan_changes(engine, make_schema(THINGS))
    assert plan.summaries == ["create table things"]
    assert plan_changes(engine, make_schema(THINGS)).summaries == ["create table things"]


def test_adding_a_column_keeps_existing_rows(engine):
    setup_things(engine)
    schema = make_schema(THINGS + "          colour: {type: text, default: \"'red'\"}\n")
    plan = apply_changes(engine, schema)
    assert plan.summaries == ["add column things.colour"]
    assert names(engine, "colour") == ["red", "red"]
    assert plan_changes(engine, schema).changes == []


def test_adding_a_unique_column_adds_exactly_one_unique_rule(engine):
    setup_things(engine, rows=())
    schema = make_schema(THINGS + "          code: {type: text, required: true, unique: true}\n")
    apply_changes(engine, schema)
    with engine.connect() as conn:
        rules = sa.inspect(conn).get_unique_constraints("things")
    assert [r["name"] for r in rules] == ["uq_things_code"]
    assert plan_changes(engine, schema).changes == []


def test_renaming_a_column_keeps_its_data(engine):
    setup_things(engine)
    schema = make_schema(THINGS.replace(
        "name: {type: text, required: true}",
        "title: {type: text, required: true, renamed_from: name}",
    ))
    plan = apply_changes(engine, schema)
    assert plan.summaries == ["rename column things.name → title"]
    assert names(engine, "title") == ["a", "b"]
    # The renamed_from line can stay in the file afterwards.
    assert plan_changes(engine, schema).changes == []


def test_renaming_a_table_keeps_its_data(engine):
    setup_things(engine)
    schema = make_schema(THINGS.replace("things:", "items:\n        renamed_from: things"))
    apply_changes(engine, schema)
    assert names(engine, table="items") == ["a", "b"]


def test_renames_carry_over_to_index_and_constraint_names(engine):
    apply_changes(engine, make_schema("""
        tables:
          owners:
            columns:
              id: {type: integer, primary_key: true}
          things:
            columns:
              id: {type: integer, primary_key: true}
              code: {type: text, unique: true}
              owner_id: {type: integer, references: owners.id, index: true}
    """))
    renamed = make_schema("""
        tables:
          owners:
            columns:
              id: {type: integer, primary_key: true}
          items:
            renamed_from: things
            columns:
              id: {type: integer, primary_key: true}
              ref: {type: text, unique: true, renamed_from: code}
              owner_id: {type: integer, references: owners.id, index: true}
    """)
    plan = apply_changes(engine, renamed)
    # Everything is renamed in place: nothing is dropped and rebuilt.
    assert all(c.summary.startswith("rename") for c in plan.changes)
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        assert inspector.get_pk_constraint("items")["name"] == "pk_items"
        assert inspector.get_unique_constraints("items")[0]["name"] == "uq_items_ref"
        assert inspector.get_foreign_keys("items")[0]["name"] == "fk_items_owner_id_owners"
        assert {i["name"] for i in inspector.get_indexes("items")} == {"ix_items_owner_id", "uq_items_ref"}
    assert plan_changes(engine, renamed).changes == []


def test_dropping_a_column_needs_permission(engine):
    setup_things(engine)
    schema = make_schema(THINGS.replace("          name: {type: text, required: true}\n", "          other: {type: text}\n"))
    with pytest.raises(DataLossError):
        apply_changes(engine, schema)
    assert names(engine) == ["a", "b"]  # nothing changed, not even the added column

    plan = apply_changes(engine, schema, allow_data_loss=True)
    assert sorted(plan.summaries) == ["add column things.other", "drop column things.name"]


def test_dropping_a_table_needs_permission(engine):
    setup_things(engine)
    schema = make_schema("""
        tables:
          others:
            columns:
              id: {type: integer, primary_key: true}
    """)
    with pytest.raises(DataLossError):
        apply_changes(engine, schema)
    assert names(engine) == ["a", "b"]


def test_changing_a_type_converts_values(engine):
    setup_things(engine, rows=("1", "22"))
    schema = make_schema(THINGS.replace("name: {type: text", "name: {type: integer"))
    plan = plan_changes(engine, schema)
    assert plan.summaries == ["change column things.name"]
    assert plan.changes[0].data_loss
    apply_changes(engine, schema, allow_data_loss=True)
    assert names(engine) == [1, 22]


def test_a_failed_change_rolls_back_everything(engine):
    setup_things(engine)
    # A new required column with no default can't be filled in for existing rows.
    schema = make_schema(THINGS + """
          size: {type: integer, required: true}
      extras:
        columns:
          id: {type: integer, primary_key: true}
    """)
    with pytest.raises(sa.exc.IntegrityError):
        apply_changes(engine, schema)
    with engine.connect() as conn:
        assert not sa.inspect(conn).has_table("extras")


def test_adding_a_reference_to_an_existing_table(engine):
    setup_things(engine)
    schema = make_schema(THINGS + """
          owner_id: {type: integer, references: owners.id, on_delete: set null, index: true}
      owners:
        columns:
          id: {type: integer, primary_key: true}
    """)
    apply_changes(engine, schema)
    assert plan_changes(engine, schema).changes == []
    with engine.connect() as conn:
        (fk,) = sa.inspect(conn).get_foreign_keys("things")
    assert fk["referred_table"] == "owners"
    assert fk["options"]["ondelete"] == "SET NULL"


def test_description_changes_are_applied(engine):
    setup_things(engine)
    schema = make_schema(THINGS.replace("description: Things", "description: Better things"))
    assert plan_changes(engine, schema).summaries == ["update description of table things"]
    apply_changes(engine, schema)
    assert plan_changes(engine, schema).changes == []


def test_apply_stops_if_the_database_changed_since_the_plan(engine):
    schema = make_schema(THINGS)
    plan = plan_changes(engine, schema)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE things (id integer PRIMARY KEY)"))
    with pytest.raises(PlanChangedError):
        apply_changes(engine, schema, expected=plan.summaries)


def test_tables_outside_the_public_schema_are_left_alone(engine):
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE SCHEMA other"))
        conn.execute(sa.text("CREATE TABLE other.stuff (id integer)"))
        conn.execute(sa.text(f'ALTER DATABASE "{engine.url.database}" SET search_path = public, other'))
    engine.dispose()  # reconnect so the search_path applies
    assert plan_changes(engine, make_schema(THINGS)).summaries == ["create table things"]


def test_primary_key_changes_are_pointed_out(engine):
    setup_things(engine)
    schema = make_schema(THINGS.replace(
        "id: {type: integer, primary_key: true, identity: true}",
        "id: {type: integer, identity: true, required: true}",
    ).replace("name: {type: text, required: true}", "name: {type: text, primary_key: true}"))
    assert "primary key" in plan_changes(engine, schema).warnings[0]
