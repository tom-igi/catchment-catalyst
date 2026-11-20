"""The admin page: logging in, uploading an Excel file through to approval, and publishing.

The page itself (the diagram of every table) is tested in test_diagram.py.
"""

import io
import json
import re
import threading

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from catalyst.admin import passwords
from catalyst.admin.app import create_app
from catalyst.admin.settings import Settings, SettingsError
from catalyst.db import load_schema
from catalyst.db.sync import apply_changes
from catalyst.publish import run as publish_run

from .test_excel import EAST, WEST, add_catchments, xlsx
from .test_inputs import ABBEY_ROW, BADGWORTHY_ROW, apha_file

PASSWORD = "a long test password"
# The example of a table uploaded 1 to 1 in Excel: Intervention Waterbodies (it links to catchments).
TABLE = "intervention_waterbodies"
HEADINGS = ("catchment_id", "intervention", "group_number", "note", "size", "estimated_cost", "funding_available",
            "started_delivery", "finished_delivery", "lead")


def plan(catchment_id, intervention, group_number, cost) -> tuple:
    return (catchment_id, intervention, group_number, None, None, cost, None, None, None, None)


PLANS = xlsx(HEADINGS, plan(WEST, 3, 1, 250000.0), plan(EAST, 12, 1, 500000.0))
SAVED = [(WEST, 3, 1, 250000.0), (EAST, 12, 1, 500000.0)]


def saved(engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(
            "SELECT catchment_id, intervention, group_number, estimated_cost FROM intervention_waterbodies ORDER BY 2"
        ))]
MODEL_TAG = re.compile(r'<script id="model" type="application/json">(.*?)</script>', re.S)


@pytest.fixture
def app(engine, tmp_path):
    apply_changes(engine, load_schema())
    add_catchments(engine, WEST, EAST)
    app = create_app(Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        users={"tom": passwords.hash_password(PASSWORD)},
        secret_key="test secret",
        published_dir=tmp_path / "published",
    ))
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    """Logged in as tom."""
    client = TestClient(app)
    assert client.post("/admin/login", data={"name": "Tom", "password": PASSWORD}).url.path == "/admin"
    return client


def upload(client, data, table=TABLE, name="plans.xlsx"):
    return client.post(f"/admin/tables/{table}/upload", files={"file": (name, data)}, follow_redirects=False)


def approve(client, upload_id):
    page = client.get(f"/admin/uploads/{upload_id}").text
    check = re.search(r'name="check" value="(\w+)"', page).group(1)
    return client.post(f"/admin/uploads/{upload_id}/approve", data={"check": check})


def page_model(page: str) -> dict:
    """What the admin page's diagram is drawn from."""
    return json.loads(MODEL_TAG.search(page).group(1))


def table_details(client, table=TABLE) -> dict:
    """What the admin page knows about a table."""
    return next(t for t in page_model(client.get("/admin").text)["tables"] if t["name"] == table)


def kept_file(app, upload_id: int) -> bytes:
    """An upload's file, as kept in the uploads table."""
    with app.state.engine.connect() as conn:
        return bytes(conn.scalar(sa.text("SELECT file FROM uploads WHERE id = :id"), {"id": upload_id}))


def uploads_table(app) -> list[tuple]:
    with app.state.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(
            "SELECT id, uploaded_to, uploaded_by, status, rows_added, rows_changed, rows_removed FROM uploads ORDER BY id"
        ))]


# --- Logging in ----------------------------------------------------------------

def test_every_page_needs_a_login(app):
    client = TestClient(app)
    for path in ["/admin", f"/admin/tables/{TABLE}", "/admin/tables/catchments/download", "/admin/uploads/1",
                 "/admin/screenshots", "/admin/screenshots/1-river-status.webp"]:
        response = client.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/admin/login")
    assert upload(client, PLANS).headers["location"] == "/admin/login"
    assert client.post("/admin/publish", follow_redirects=False).headers["location"] == "/admin/login"


def test_a_wrong_password_is_refused(app):
    client = TestClient(app)
    for name, password in [("tom", "wrong"), ("nobody", PASSWORD)]:
        response = client.post("/admin/login", data={"name": name, "password": password})
        assert response.status_code == 401
        assert "That name and password don&#39;t match." in response.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_too_many_wrong_passwords_have_to_wait(app):
    clock = [1000.0]
    app.state.attempts = passwords.Attempts(clock=lambda: clock[0])
    client = TestClient(app)

    def log_in(name, password):
        return client.post("/admin/login", data={"name": name, "password": password}, follow_redirects=False)

    for _ in range(passwords.Attempts.MAX):
        assert log_in("tom", "wrong").status_code == 401
    response = log_in("tom", PASSWORD)  # even the right password, so a guesser can't tell
    assert response.status_code == 429
    assert "Too many wrong passwords. Try again in 15 minutes." in response.text
    assert log_in("alex", "wrong").status_code == 429  # from the same address

    clock[0] += 14 * 60 + 1
    assert "Try again in 1 minute." in log_in("tom", PASSWORD).text
    clock[0] += 60
    assert log_in("tom", PASSWORD).status_code == 303  # the first wrong one is 15 minutes old

    # A name being guessed at from many addresses has to wait too, and a right password clears it.
    attempts = passwords.Attempts(clock=lambda: clock[0])
    for n in range(passwords.Attempts.MAX):
        attempts.wrong("Tom ", f"10.0.0.{n}")
    assert attempts.wait_minutes("tom", "10.0.0.99") == 15
    assert attempts.wait_minutes("alex", "10.0.0.99") == 0
    attempts.right("tom", "10.0.0.99")
    assert attempts.wait_minutes("tom", "10.0.0.99") == 0


def test_logging_out(client):
    client.post("/admin/logout")
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"


def test_users_setting():
    users = passwords.parse_users(f" tom:{passwords.hash_password('one')} , Alex:{passwords.hash_password('two')}")
    assert list(users) == ["tom", "alex"]
    assert passwords.log_in(users, "ALEX ", "two") == "alex"
    assert passwords.log_in(users, "alex", "one") is None
    for bad, message in [
        ("", "doesn't list anyone"),
        ("tom:secret", "entry 1 should look like name:scrypt"),
        (f"tom:{users['tom']},tom:{users['tom']}", "lists tom more than once"),
    ]:
        with pytest.raises(ValueError, match=message):
            passwords.parse_users(bad)


def test_settings_must_be_set(monkeypatch):
    for name in ["DATABASE_URL", "ADMIN_USERS", "ADMIN_SECRET_KEY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    with pytest.raises(SettingsError, match="Not set: ADMIN_USERS, ADMIN_SECRET_KEY"):
        Settings.from_environment()


# --- Uploading -------------------------------------------------------------------

def test_only_tables_filled_by_excel_can_be_updated(app, client):
    tables = page_model(client.get("/admin").text)["tables"]
    assert {t["name"] for t in tables if "update" in t} == set(app.state.schema.excel_tables)
    assert upload(client, PLANS, table="livestock").status_code == 404  # worked out from a source file instead
    assert {TABLE, "location_text", "datasets"} <= set(app.state.schema.excel_tables)
    assert "ea_classifications" not in app.state.schema.excel_tables
    assert table_details(client)["update"]["download_url"] == f"/admin/tables/{TABLE}/download"
    assert table_details(client)["update"]["key"] == ["catchment_id", "intervention"]
    assert client.get("/admin/tables/catchments").status_code == 404
    assert upload(client, PLANS, table="catchments").status_code == 404


def test_every_table_can_be_downloaded(app, client):
    tables = {t["name"]: t for t in page_model(client.get("/admin").text)["tables"]}
    for name in app.state.schema.metadata.tables:
        if name in tables:  # (Uploads and Publishes aren't on the page, but can be downloaded too)
            assert tables[name]["download"]["url"] == f"/admin/tables/{name}/download"
        response = client.get(f"/admin/tables/{name}/download")
        assert response.status_code == 200, name
        assert response.headers["content-disposition"].startswith(f'attachment; filename="{name}_')
    assert tables["catchments"]["download"]["left_out"] == ["boundary", "river_line"]  # map shapes
    assert tables["catchments"]["download"]["left_out_why"] == "map shapes"
    uploads_sheet = load_workbook(io.BytesIO(client.get("/admin/tables/uploads/download").content)).active
    assert "file" not in [c.value for c in uploads_sheet[1]]  # the files themselves: each from its upload
    assert tables["ea_scores"]["download"]["left_out"] == [] and tables["ea_scores"]["download"]["left_out_why"] is None

    sheet = load_workbook(io.BytesIO(client.get("/admin/tables/catchments/download").content)).active
    assert [c.value for c in sheet["A"]] == ["id", "GB108050008080", "GB108050008100"]
    assert client.get("/admin/tables/nope/download").status_code == 404


def test_old_addresses_go_to_the_admin_page(client):
    response = client.get(f"/admin/tables/{TABLE}", follow_redirects=False)
    assert response.headers["location"] == f"/admin#upload-{TABLE}"  # with its upload open
    assert client.get("/admin/data-map", follow_redirects=False).headers["location"] == "/admin"


def test_download_upload_preview_and_approve(app, client):
    download = client.get(f"/admin/tables/{TABLE}/download")
    assert [c.value for c in load_workbook(io.BytesIO(download.content)).active[1]] == list(HEADINGS)

    response = upload(client, PLANS, name="October plans.xlsx")
    assert response.headers["location"] == "/admin/uploads/1"
    preview = client.get("/admin/uploads/1").text
    assert "Check the changes" in preview and "October plans.xlsx" in preview
    assert saved(app.state.engine) == []  # nothing changes before approval
    (waiting,) = table_details(client)["update"]["recent"]
    assert (waiting["status"], waiting["url"], waiting["file"]) == ("preview", "/admin/uploads/1", "October plans.xlsx")

    page = approve(client, 1)
    assert page.history[-1].headers["location"] == f"/admin#upload-{TABLE}"  # back to the table's upload
    assert "Done. Intervention Waterbodies now matches October plans.xlsx: 2 added, 0 changed, 0 deleted." in page.text
    details = next(t for t in page_model(page.text)["tables"] if t["name"] == TABLE)
    assert (details["rows"], details["update"]["last"]["who"], details["update"]["recent"][0]["status"]) == (2, "tom", "approved")
    # The last approved file, as the example of what to upload (a source file's upload offers it).
    assert (details["update"]["last"]["file"], details["update"]["last"]["file_url"]) == ("October plans.xlsx", "/admin/uploads/1/file")
    assert saved(app.state.engine) == SAVED
    assert uploads_table(app) == [(1, TABLE, "tom", "approved", 2, 0, 0)]
    assert kept_file(app, 1) == PLANS  # kept in the database, so it's in its backups
    file = client.get("/admin/uploads/1/file")
    assert (file.content, file.headers["content-disposition"]) == (PLANS, "attachment; filename*=utf-8''October%20plans.xlsx")

    # Uploading the same file again changes nothing, so there's nothing to approve.
    page = upload(client, PLANS)
    assert page.headers["location"] == f"/admin#upload-{TABLE}"
    assert "is the same as the table, so there&#39;s nothing to change" in client.get(page.headers["location"]).text


def test_problems_are_shown_and_nothing_is_kept(app, client):
    response = upload(client, xlsx(HEADINGS, plan("GB999", "soon", 1, None)))
    assert response.status_code == 422
    problems = page_model(response.text)["problems"]  # shown in the table's upload, opened by the page
    assert (problems["uploaded_to"], problems["file"], problems["more"]) == (TABLE, "plans.xlsx", 0)
    assert "Row 2, intervention: 'soon' isn't a whole number." in problems["items"]
    assert uploads_table(app) == []


def test_deleting_rows_is_warned_about(client):
    upload(client, PLANS)
    approve(client, 1)
    upload(client, xlsx(HEADINGS, plan(WEST, 3, 1, 250000.0)))
    assert "1 row will be deleted," in client.get("/admin/uploads/2").text
    upload(client, xlsx(HEADINGS))
    assert "This deletes every row that" in client.get("/admin/uploads/3").text


def test_a_preview_that_is_out_of_date_is_not_approved(app, client):
    upload(client, PLANS)
    page = client.get("/admin/uploads/1").text
    check = re.search(r'name="check" value="(\w+)"', page).group(1)
    with app.state.engine.begin() as conn:  # someone else changes the table meanwhile
        conn.execute(sa.text(f"INSERT INTO intervention_waterbodies (catchment_id, intervention, group_number) VALUES ('{WEST}', 3, 2)"))

    page = client.post("/admin/uploads/1/approve", data={"check": check})
    assert page.url.path == "/admin/uploads/1"
    assert "The table has changed since this preview was shown" in page.text
    assert saved(app.state.engine) == [(WEST, 3, 2, None)]
    assert uploads_table(app)[0][3] == "preview"

    approve(client, 1)  # with the up-to-date preview
    assert saved(app.state.engine) == SAVED


def test_cancelling(app, client):
    upload(client, PLANS)
    page = client.post("/admin/uploads/1/cancel")
    assert page.history[-1].headers["location"] == f"/admin#upload-{TABLE}"
    assert "Cancelled plans.xlsx. Nothing has been changed." in page.text
    assert "already been cancelled" in approve_anyway(client, 1).text
    assert saved(app.state.engine) == []
    assert uploads_table(app)[0][3] == "cancelled"


def approve_anyway(client, upload_id):
    return client.post(f"/admin/uploads/{upload_id}/approve", data={"check": "anything"})


# --- Uploading a source file ---------------------------------------------------------

def add_named_catchments(app):
    with app.state.engine.begin() as conn:
        conn.execute(sa.text("UPDATE catchments SET name = 'Abbey River' WHERE id = :id"), {"id": WEST})
        conn.execute(sa.text("UPDATE catchments SET name = 'Badgworthy Water' WHERE id = :id"), {"id": EAST})


def upload_source(client, data, name="APHA Livestock Data Feb 2026.xlsx", source="apha_livestock"):
    return client.post(f"/admin/inputs/{source}/upload", files={"file": (name, data)}, follow_redirects=False)


def rows_in(app, table) -> list[tuple]:
    with app.state.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {table} ORDER BY 1, 2"))]


def test_a_source_file_fills_its_tables(app, client):
    add_named_catchments(app)
    with app.state.engine.begin() as conn:  # published before, so the Publish box counts what's approved since
        conn.execute(sa.text("INSERT INTO publishes (published_at) VALUES (now() - interval '1 hour')"))
    source = next(i for i in page_model(client.get("/admin").text)["inputs"] if i["name"] == "apha_livestock")
    assert (source["title"], source["tables"]) == ("APHA livestock data", ["livestock", "livestock_pressure"])
    assert source["update"]["upload_url"] == "/admin/inputs/apha_livestock/upload"
    assert table_details(client, "livestock")["input"] == "apha_livestock"
    assert table_details(client, "livestock_pressure")["transform"]["steps"][1]["columns"] == ["nitrogen_load"]

    data = apha_file(ABBEY_ROW, BADGWORTHY_ROW, ("Somewhere Else",) + ABBEY_ROW[1:])
    response = upload_source(client, data)
    assert response.headers["location"] == "/admin/uploads/1"
    preview = client.get("/admin/uploads/1").text
    assert "uploaded to APHA livestock data by tom" in preview and "It fills Livestock and Livestock Pressure." in preview
    assert '<h2 class="part">Livestock Pressure</h2>' in preview
    assert "so it is left out: Somewhere Else." in preview
    assert "Approve and update the tables" in preview
    assert rows_in(app, "livestock") == []  # nothing changes before approval
    assert source_details(client)["update"]["recent"][0]["status"] == "preview"

    page = approve(client, 1)
    assert page.history[-1].headers["location"] == "/admin#upload-apha_livestock"  # back to the source file's upload
    assert "Done. Livestock and Livestock Pressure now match APHA Livestock Data Feb 2026.xlsx: 12 added, 0 changed, 0 deleted." in page.text
    assert len(rows_in(app, "livestock")) == 10 and len(rows_in(app, "livestock_pressure")) == 2
    assert rows_in(app, "livestock_pressure")[0][-1] in {"Medium", "Very Low"}
    assert uploads_table(app) == [(1, "apha_livestock", "tom", "approved", 12, 0, 0)]
    with app.state.engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT changes FROM uploads")) == {"livestock": [10, 0, 0], "livestock_pressure": [2, 0, 0]}
    assert kept_file(app, 1) == data
    file = client.get("/admin/uploads/1/file")
    assert (file.content, file.headers["content-type"]) == (data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "1 upload approved since the last publish, so not on it yet: APHA livestock data." in publish_box(client.get("/admin").text)

    # The same file again changes nothing.
    page = client.get(upload_source(client, data).headers["location"])
    assert "is the same as the tables it fills, so there&#39;s nothing to change" in page.text


def source_details(client) -> dict:
    return next(i for i in page_model(client.get("/admin").text)["inputs"] if i["name"] == "apha_livestock")


def test_a_source_files_problems_are_shown_in_its_upload(app, client):
    add_named_catchments(app)
    response = upload_source(client, apha_file(ABBEY_ROW, ABBEY_ROW), name="twice.xlsx")
    assert response.status_code == 422
    problems = page_model(response.text)["problems"]
    assert (problems["uploaded_to"], problems["file"]) == ("apha_livestock", "twice.xlsx")
    assert problems["items"] == ["Rows 2 and 3 are both for Abbey River. Each can only appear once."]
    assert upload_source(client, b"x", name="old.xls").status_code == 422
    assert uploads_table(app) == []
    assert upload_source(client, b"x", source="nope").status_code == 404
    assert upload_source(client, b"x", source="livestock").status_code == 404  # a table, not a source file


def test_a_transformations_example_is_from_its_last_approved_file(app, client):
    """The real data in a Transformation panel: rows of the file, each step done to one waterbody's, and the rows they
    make in the table. (A downloaded table's is in diagram.yaml: test_diagram.py.)"""
    add_named_catchments(app)
    example = client.get("/admin/tables/livestock_pressure/example").json()
    assert example["missing"] == "No APHA livestock data file approved yet, so no example."
    assert (example["out"]["rows"], example["out"]["total"]) == ([], 0)  # the table as it is now
    assert client.get("/admin/tables/catchments/example").status_code == 404

    upload_source(client, apha_file(ABBEY_ROW, BADGWORTHY_ROW), name="APHA February.xlsx")
    assert client.get("/admin/tables/livestock_pressure/example").json()["missing"]  # not until it's approved
    approve(client, 1)
    example = client.get("/admin/tables/livestock_pressure/example").json()
    assert (example["file"], example["file_url"], example["waterbody"]) == ("APHA February.xlsx", "/admin/uploads/1/file", "Abbey River")
    assert example["in"]["columns"][:2] == ["Catchment Name", "Beef Density Per SqKm"]  # only the columns it uses
    assert [row[0] for row in example["in"]["rows"]] == ["Abbey River", "Badgworthy Water"]
    assert (example["in"]["example"], example["in"]["total"]) == ([0], 2)  # the example's highlighted
    assert example["out"]["columns"][:2] == ["catchment_id", "nitrogen_load"]
    assert [row[0] for row in example["out"]["rows"]] == [WEST, EAST] and example["out"]["rows"][0][-1] == "Medium"
    steps = example["steps"]  # one for each of the table's steps, in order
    assert steps[0] == {"in": [["Catchment Name", "Abbey River", False]], "out": [["catchment_id", WEST]]}
    assert steps[1] == "37.37 × 70 + 73.27 × 110 + 14.59 × 20 + 57.32 × 13 + 907.59 × 0.6 = 12,257.13"  # in its words
    assert [name for name, _, own in steps[3]["in"] if own] == ["nitrogen_load", "phosphate_load"]  # worked out before
    livestock = client.get("/admin/tables/livestock/example").json()
    assert livestock["waterbody"] == "Abbey River" and len(livestock["out"]["rows"]) == 5  # its five kinds of livestock
    assert len(livestock["in"]["rows"]) == 1  # all from its one row

    # Kept with the upload; made again from its file if it wasn't (an upload before 20 November 2026).
    with app.state.engine.begin() as conn:
        assert set(conn.scalar(sa.text("SELECT examples FROM uploads WHERE id = 1"))) == {"livestock", "livestock_pressure"}
        conn.execute(sa.text("UPDATE uploads SET examples = NULL"))
    assert client.get("/admin/tables/livestock_pressure/example").json()["steps"] == steps
    with app.state.engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT examples IS NOT NULL FROM uploads WHERE id = 1"))

    # An Excel table's: its file's first rows, which go into the table as they are.
    upload(client, PLANS)
    approve(client, 2)
    example = client.get(f"/admin/tables/{TABLE}/example").json()
    assert example["in"]["columns"] == list(HEADINGS) and example["in"]["total"] == 2
    assert example["out"] == example["in"] and example["steps"] == []


def test_a_source_file_cancelled_or_out_of_date(app, client):
    add_named_catchments(app)
    upload_source(client, apha_file(ABBEY_ROW))
    check = re.search(r'name="check" value="(\w+)"', client.get("/admin/uploads/1").text).group(1)
    with app.state.engine.begin() as conn:  # someone changes one of its tables meanwhile
        conn.execute(sa.text(f"INSERT INTO livestock_pressure VALUES ('{WEST}', 1, 1, 2, 'Low')"))
    page = client.post("/admin/uploads/1/approve", data={"check": check})
    assert "The tables have changed since this preview was shown" in page.text
    assert rows_in(app, "livestock") == []
    page = client.post("/admin/uploads/1/cancel")
    assert page.history[-1].headers["location"] == "/admin#upload-apha_livestock"
    assert uploads_table(app)[0][3] == "cancelled"


# --- Publishing ------------------------------------------------------------------

def publish_box(page: str) -> str:
    """The Publish box at the top of the admin page, as plain text."""
    box = re.search(r'<section class="publish[^"]*".*?</section>', page, re.S).group(0)
    return " ".join(re.sub(r"<[^>]+>", " ", box).split())


def add_location(app):
    with app.state.engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', :ids)"), {"ids": [WEST, EAST]})


def published_by(app) -> list:
    with app.state.engine.connect() as conn:
        return list(conn.scalars(sa.text("SELECT published_by FROM publishes ORDER BY id")))


def test_publishing_puts_what_is_approved_on_the_dashboard(app, client, tmp_path):
    add_location(app)
    box = publish_box(client.get("/admin").text)
    assert "Approved uploads go on it when you publish. No publish recorded yet." in box

    page = client.post("/admin/publish")
    assert page.history[-1].headers["location"] == "/admin"
    assert "Published North Devon. The public dashboard now shows everything approved so far." in page.text
    assert (tmp_path / "published" / "north-devon" / "index.html").is_file()
    assert published_by(app) == ["tom"]
    assert re.fullmatch(r"Public dashboard Everything approved is on it\. Last published \d+ \w+ \d{4}, \d\d:\d\d, by tom\. Publish",
                        publish_box(page.text))
    assert '<section class="publish"' in page.text  # not marked as waiting

    # Approving an upload puts it in the box, until the next publish.
    upload(client, PLANS)
    page = approve(client, 1)
    assert "It will be on the public dashboard once you publish." in page.text
    upload(client, xlsx(HEADINGS, plan(WEST, 3, 1, 250000.0)))
    approve(client, 2)
    page = client.get("/admin").text
    assert "2 uploads approved since the last publish, so not on it yet: Intervention Waterbodies." in publish_box(page)
    assert '<section class="publish is-waiting"' in page
    with app.state.engine.begin() as conn:  # a different table
        conn.execute(sa.text("UPDATE uploads SET uploaded_to = 'waterbody_lookup' WHERE id = 2"))
    assert "so not on it yet: Intervention Waterbodies and Waterbody Lookup." in publish_box(client.get("/admin").text)

    client.post("/admin/publish")
    assert "Everything approved is on it." in publish_box(client.get("/admin").text)
    assert published_by(app) == ["tom", "tom"]


def test_an_approval_waits_for_a_publish_and_is_timed_after_it(app, client):
    upload(client, PLANS)
    page = client.get("/admin/uploads/1").text
    check = re.search(r'name="check" value="(\w+)"', page).group(1)
    done = threading.Event()

    def approving():
        client.post("/admin/uploads/1/approve", data={"check": check})
        done.set()

    with app.state.engine.connect() as publishing:  # a publish is reading the tables
        publishing.execute(sa.select(sa.func.pg_advisory_xact_lock(publish_run.LOCK)))
        publishing.execute(app.state.schema.metadata.tables["publishes"].insert().values(published_at=sa.func.clock_timestamp()))
        thread = threading.Thread(target=approving)
        thread.start()
        assert not done.wait(1)  # the approval waits for it
        assert saved(app.state.engine) == []
        publishing.commit()
    assert done.wait(30)
    thread.join()
    assert saved(app.state.engine) == SAVED
    assert "1 upload approved since the last publish, so not on it yet" in publish_box(client.get("/admin").text)


def test_the_publish_commands_publishes_are_shown_too(app, client):
    with app.state.engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO publishes (published_by) VALUES (NULL)"))
    assert ", with the publish command." in publish_box(client.get("/admin").text)


def test_a_problem_publishing_is_shown_and_nothing_changes(app, client, tmp_path):
    page = client.post("/admin/publish")  # no locations yet
    assert "Nothing has been published. There are no locations to publish yet." in page.text
    assert published_by(app) == []
    assert not (tmp_path / "published").exists()

    add_location(app)
    app.state.settings.published_dir = tmp_path / "scores.xlsx"  # a file, not a folder
    app.state.settings.published_dir.write_text("")
    page = client.post("/admin/publish")
    assert "The dashboard&#39;s pages couldn&#39;t all be written" in page.text
    assert published_by(app) == []


# --- Input for AI ------------------------------------------------------------------

# Hole Water flows into Bray (Mole to Hole Water), as do Nadrid Water and Ash Brook (not imported). Bray flows into
# Mole (Taw to Bray), then the Taw, then the estuary (not imported).
BRAY, HOLE, NADRID, ASH, MOLE, TAW, ESTUARY = (
    "GB108050019910", "GB108050019930", "GB108050013950", "GB108050099999", "GB108050014380", "GB108050014220",
    "GB540805015500",
)


def add_river(app):
    rows = [
        (BRAY, "Bray (Mole to Hole Water)", [NADRID, HOLE, ASH], [MOLE]),
        (HOLE, "Hole Water", [], [BRAY]),
        (NADRID, "Nadrid Water", [], [BRAY]),
        (MOLE, "Mole (Taw to Bray)", [BRAY], [TAW]),
        (TAW, "Taw (River Mole to Estuary)", [MOLE], [ESTUARY]),
    ]
    with app.state.engine.begin() as conn:
        for catchment_id, name, up, down in rows:
            conn.execute(sa.text(
                "INSERT INTO catchments (id, name, waterbody_type, upstream_ids, downstream_ids, area_ha)"
                " VALUES (:id, :name, 'River', :up, :down, 4212.6)"
            ), {"id": catchment_id, "name": name, "up": up, "down": down})
        location = conn.scalar(sa.text("INSERT INTO locations (name, catchment_ids) VALUES ('North Devon', :ids) RETURNING id"),
                               {"ids": [r[0] for r in rows]})
        for catchment_id, why in ((BRAY, "Bray fails on **phosphate**.\n### Not a section of the file"), (HOLE, "Hole Water's own text")):
            conn.execute(sa.text(
                "INSERT INTO river_status_text (catchment_id, why_failing, hypothesis_confidence) VALUES (:id, :why, 'High')"
            ), {"id": catchment_id, "why": why})
        conn.execute(sa.text(
            "INSERT INTO ea_classifications (catchment_id, item, year, cycle, level, status, certainty) VALUES"
            " (:id, 'Ecological', 2019, 2, 'Ecological, chemical or quantitative status', 'Good', 'Uncertain'),"
            " (:id, 'Ecological', 2019, 3, 'Ecological, chemical or quantitative status', 'Moderate', 'Very Certain'),"
            " (:id, 'Phosphate', 2019, 3, 'Element', 'Poor', 'Quite Certain'),"
            " (:id, 'Fish', 2013, 2, 'Element', 'High', 'No Information')"
        ), {"id": BRAY})
        conn.execute(sa.text("INSERT INTO waterbody_figures (catchment_id, ranking) VALUES (:id, 68)"), {"id": BRAY})
        conn.execute(sa.text("INSERT INTO postcodes (postcode, catchment_id) VALUES ('EX36 3AA', :id)"), {"id": BRAY})
        conn.execute(sa.text(
            "INSERT INTO storm_overflows (catchment_id, year, site_name, latitude, spill_hours) VALUES"
            " (:id, 2025, 'BRAY STW', 50.987654, 12.3456)"
        ), {"id": HOLE})
        conn.execute(sa.text(
            "INSERT INTO intervention_types (location_id, number, name, summary_group) VALUES (:loc, 3, 'Farm advice', 'Priority')"
        ), {"loc": location})
        conn.execute(sa.text(
            "INSERT INTO intervention_waterbodies (catchment_id, intervention, group_number, size) VALUES (:id, 3, 1, 'c.6 farms | more')"
        ), {"id": BRAY})


def ai_input(client, catchment_id) -> str:
    response = client.get("/admin/ai-input", params={"catchment": catchment_id})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    return response.text


def section(text: str, heading: str) -> str:
    """The part of the file under a ## heading, up to the next one."""
    return text.split(f"\n## {heading}", 1)[1].split("\n## ", 1)[0]


def test_input_for_ai_has_the_waterbody_and_its_neighbours(app, client):
    add_river(app)
    response = client.get("/admin/ai-input", params={"catchment": BRAY})
    assert re.fullmatch(r"attachment; filename\*=utf-8''AI%20input%20-%20Bray%20%28Mole%20to%20Hole%20Water%29%20-%20\d{4}-\d\d-\d\d\.txt",
                        response.headers["content-disposition"])
    text = ai_input(client, BRAY)
    assert text.startswith("# Input for AI: Bray (Mole to Hole Water)\n")
    assert "one waterbody in North Devon: **Bray (Mole to Hole Water)** (the Environment Agency's ID GB108050019910)" in text
    assert "3 waterbodies that flow straight into it (upstream) and 1 waterbody it flows straight into (downstream)" in text

    # The waterbodies: the chosen one, upstream by name (one not imported), downstream, then further downstream by name.
    assert section(text, "The waterbodies in this file").split("\n\n")[1].splitlines()[2:] == [
        f"| Bray (Mole to Hole Water) | {BRAY} | The waterbody the text is for |",
        f"| {ASH} | {ASH} | Upstream: flows straight into Bray (Mole to Hole Water). It isn't in Catchment Catalyst, so there's no data for it here |",
        f"| Hole Water | {HOLE} | Upstream: flows straight into Bray (Mole to Hole Water) |",
        f"| Nadrid Water | {NADRID} | Upstream: flows straight into Bray (Mole to Hole Water) |",
        f"| Mole (Taw to Bray) | {MOLE} | Downstream: Bray (Mole to Hole Water) flows straight into it |",
    ]
    assert (f"After Mole (Taw to Bray), the river goes on to (names only, not in this file): "
            f"Taw (River Mole to Estuary) → {ESTUARY} (not in Catchment Catalyst).") in text
    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## About this file", "## The waterbodies in this file", "## What the text is for", "## What the tables hold",
        "## 1. Bray (Mole to Hole Water): the waterbody the text is for",
        f"## 2. {ASH}: upstream, flows straight into Bray (Mole to Hole Water)",
        "## 3. Hole Water: upstream, flows straight into Bray (Mole to Hole Water)",
        "## 4. Nadrid Water: upstream, flows straight into Bray (Mole to Hole Water)",
        "## 5. Mole (Taw to Bray): downstream, Bray (Mole to Hole Water) flows straight into it",
    ]

    # Its current text, fenced so its marks are its own; not the neighbours'.
    assert "```text\nBray fails on **phosphate**.\n### Not a section of the file\n```" in section(text, "What the text is for")
    assert "**Intervention hypothesis (confidence: High)**\n\n```text\n(empty)\n```" in text
    assert "Hole Water's own text" not in text
    assert "### River Status Text" not in text and "### Postcodes" not in text and "EX36" not in text

    chosen = section(text, "1. Bray")
    assert "- Ecological status: Moderate (2019)\n- Failing elements (2019): Phosphate\n" in chosen
    assert "- Ranking: 68 of 5 rivers" in chosen
    assert "- Area (ha): 4212.6" in chosen
    # EA Classifications as a grid: the latest cycle's status each year, broadest level first.
    assert (
        "| Item | Level | 2013 | 2019 | Certainty (latest) |\n|---|---|---|---|---|\n"
        "| Ecological | Ecological, chemical or quantitative status |  | Moderate | Very Certain |\n"
        "| Fish | Element | High |  | No Information |\n"
        "| Phosphate | Element |  | Poor | Quite Certain |"
    ) in chosen
    # An intervention has its type's name; a | in a cell can't split it.
    assert "| 3 (Farm advice) | 1 |  | c.6 farms \\| more |" in chosen
    assert "### Storm Overflows\n\nNone." in chosen

    # A neighbour's rows: coordinates left out, numbers rounded.
    hole = section(text, "3. Hole Water")
    assert "| Year | Company | Site name |" in hole and "| 2025 |  | BRAY STW |" in hole and "12.35 |" in hole
    assert "Latitude" not in text and "50.98" not in text
    assert section(text, f"2. {ASH}").strip().endswith(f"{ASH} isn't in Catchment Catalyst, so there's no data for it here.")


def test_input_for_ai_is_chosen_at_the_bottom_of_the_admin_page(app, client):
    add_river(app)
    page = client.get("/admin").text
    box = page.split('<section class="ai-input"', 1)[1].split("</section>", 1)[0]
    assert '<form method="get" action="/admin/ai-input">' in box
    assert (f'<option value="{BRAY}" data-includes="Upstream: {ASH} (no data), Hole Water, Nadrid Water. '
            f'Downstream: Mole (Taw to Bray).">Bray (Mole to Hole Water)</option>') in box
    assert f'<option value="{HOLE}" data-includes="Upstream: none. Downstream: Bray (Mole to Hole Water).">Hole Water</option>' in box


def test_input_for_ai_needs_a_waterbody_that_exists(app, client):
    assert client.get("/admin/ai-input").status_code == 400
    assert client.get("/admin/ai-input", params={"catchment": "GB000"}).status_code == 404
    assert TestClient(app).get(f"/admin/ai-input?catchment={WEST}", follow_redirects=False).headers["location"] == "/admin/login"
    # A waterbody that's in no location, with no neighbours or data.
    text = ai_input(client, WEST)
    assert "one waterbody: **GB108050008080**" in text and "There's no text for it yet." in text
    assert "no waterbodies that flow straight into it (upstream) and no waterbodies it flows straight into" in text
    assert "- Ecological status: none\n- Failing elements: no classification from the EA" in text
    assert "the river goes on to" not in text
