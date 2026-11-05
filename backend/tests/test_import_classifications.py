"""The EA classifications and RNAGs importer.

Uses real EA downloads for North Devon in tests/fixtures/ea, cut down to the two
test catchments and Langham Lake (EA data, Open Government Licence).
"""

import pytest
import sqlalchemy as sa

from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.importers.api import catchments, classifications
from catalyst.importers.api.catchments import ImportProblem

from .test_import_catchments import EAST_OKEMONT, WEST_OKEMENT, FakeEA

SCHEMA = load_schema()


@pytest.fixture
def database(engine):
    """The two test catchments, imported."""
    apply_changes(engine, SCHEMA)
    found, _ = catchments.fetch([WEST_OKEMENT, EAST_OKEMONT], FakeEA())
    with engine.begin() as conn:
        catchments.save(conn, SCHEMA, found)
    return engine


def test_downloads_each_management_catchment_once(database):
    with database.connect() as conn:
        assert classifications.management_catchments(conn, SCHEMA) == {3062: {WEST_OKEMENT, EAST_OKEMONT}}
    downloads = classifications.fetch([3062], FakeEA())
    assert sorted(downloads[0].files) == ["classifications.csv", "rnags.csv"]


def test_keeps_only_the_imported_catchments_rows():
    rows = classifications.read(classifications.fetch([3062], FakeEA()), {WEST_OKEMENT})
    assert {r["catchment_id"] for r in rows["ea_classifications"]} == {WEST_OKEMENT}  # not Langham Lake's
    fish = [r for r in rows["ea_classifications"] if r["item"] == "Fish" and r["year"] == 2022]
    assert fish == [{
        "catchment_id": WEST_OKEMENT, "item": "Fish", "year": 2022, "cycle": 3,
        "level": "Element", "status": "Poor", "certainty": "Very Certain",
    }]
    reasons = {r["activity"] for r in rows["ea_rnags"]}
    assert "Abandoned mine" in reasons
    assert all(isinstance(r["id"], int) for r in rows["ea_rnags"])


def test_importing_replaces_every_row(database):
    downloads = classifications.fetch([3062], FakeEA())
    for ids in ({WEST_OKEMENT, EAST_OKEMONT}, {EAST_OKEMONT}):
        with database.begin() as conn:
            classifications.save(conn, SCHEMA, classifications.read(downloads, ids))
    with database.connect() as conn:
        assert conn.scalars(sa.text("SELECT DISTINCT catchment_id FROM ea_classifications")).all() == [EAST_OKEMONT]
        assert classifications.current_counts(conn, SCHEMA)["ea_classifications"] > 0


def test_a_changed_file_is_reported_rather_than_guessed():
    source = classifications.SOURCES[0]
    data = b'"Water Body ID","Classification Item","Year"\n"GB1","Fish","2022"\n'
    with pytest.raises(ImportProblem, match="has no Cycle, Classification Level, Status, Certainty column"):
        classifications.read_file(data, source, {"GB1"})
    data = (b'"Water Body ID","Classification Item","Year","Cycle","Classification Level","Status","Certainty"\n'
            b'"GB1","Fish","twenty","3","Element","Poor",""\n')
    with pytest.raises(ImportProblem, match="line 2: 'twenty' in Year isn't a whole number"):
        classifications.read_file(data, source, {"GB1"})


def test_downloads_are_kept_as_they_were(tmp_path):
    downloads = classifications.fetch([3062], FakeEA())
    run_dir = classifications.save_raw_files(downloads, tmp_path)
    assert (run_dir / "3062" / "rnags.csv").read_bytes() == downloads[0].files["rnags.csv"]
