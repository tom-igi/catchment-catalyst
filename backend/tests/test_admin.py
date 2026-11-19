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
        raw_files_dir=tmp_path,
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
        assert tables[name]["download"]["url"] == f"/admin/tables/{name}/download"
        response = client.get(f"/admin/tables/{name}/download")
        assert response.status_code == 200, name
        assert response.headers["content-disposition"].startswith(f'attachment; filename="{name}_')
    assert tables["catchments"]["download"]["left_out"] == ["boundary", "river_line"]  # map shapes
    assert tables["ea_scores"]["download"]["left_out"] == []

    sheet = load_workbook(io.BytesIO(client.get("/admin/tables/catchments/download").content)).active
    assert [c.value for c in sheet["A"]] == ["id", "GB108050008080", "GB108050008100"]
    assert client.get("/admin/tables/nope/download").status_code == 404


def test_old_addresses_go_to_the_admin_page(client):
    response = client.get(f"/admin/tables/{TABLE}", follow_redirects=False)
    assert response.headers["location"] == f"/admin#upload-{TABLE}"  # with its upload open
    assert client.get("/admin/data-map", follow_redirects=False).headers["location"] == "/admin"


def test_download_upload_preview_and_approve(app, client, tmp_path):
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
    assert saved(app.state.engine) == SAVED
    assert uploads_table(app) == [(1, TABLE, "tom", "approved", 2, 0, 0)]
    (kept,) = (tmp_path / TABLE).iterdir()
    assert kept.read_bytes() == PLANS
    assert client.get("/admin/uploads/1/file").content == PLANS

    # Uploading the same file again changes nothing, so there's nothing to approve.
    page = upload(client, PLANS)
    assert page.headers["location"] == f"/admin#upload-{TABLE}"
    assert "is the same as the table, so there&#39;s nothing to change" in client.get(page.headers["location"]).text


def test_problems_are_shown_and_nothing_is_kept(app, client, tmp_path):
    response = upload(client, xlsx(HEADINGS, plan("GB999", "soon", 1, None)))
    assert response.status_code == 422
    problems = page_model(response.text)["problems"]  # shown in the table's upload, opened by the page
    assert (problems["uploaded_to"], problems["file"], problems["more"]) == (TABLE, "plans.xlsx", 0)
    assert "Row 2, intervention: 'soon' isn't a whole number." in problems["items"]
    assert uploads_table(app) == []
    assert list(tmp_path.iterdir()) == []


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


def test_a_source_file_fills_its_tables(app, client, tmp_path):
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
    (kept,) = (tmp_path / "apha_livestock").iterdir()
    assert kept.read_bytes() == data and kept.suffix == ".xlsx"
    assert client.get("/admin/uploads/1/file").content == data
    assert "1 upload approved since the last publish, so not on it yet: APHA livestock data." in publish_box(client.get("/admin").text)

    # The same file again changes nothing.
    page = client.get(upload_source(client, data).headers["location"])
    assert "is the same as the tables it fills, so there&#39;s nothing to change" in page.text


def source_details(client) -> dict:
    return next(i for i in page_model(client.get("/admin").text)["inputs"] if i["name"] == "apha_livestock")


def test_a_source_files_problems_are_shown_in_its_upload(app, client, tmp_path):
    add_named_catchments(app)
    response = upload_source(client, apha_file(ABBEY_ROW, ABBEY_ROW), name="twice.xlsx")
    assert response.status_code == 422
    problems = page_model(response.text)["problems"]
    assert (problems["uploaded_to"], problems["file"]) == ("apha_livestock", "twice.xlsx")
    assert problems["items"] == ["Rows 2 and 3 are both for Abbey River. Each can only appear once."]
    assert upload_source(client, b"x", name="old.xls").status_code == 422
    assert uploads_table(app) == [] and list(tmp_path.iterdir()) == []
    assert upload_source(client, b"x", source="nope").status_code == 404
    assert upload_source(client, b"x", source="livestock").status_code == 404  # a table, not a source file


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
        conn.execute(sa.text("UPDATE uploads SET uploaded_to = 'farms' WHERE id = 2"))
    assert "so not on it yet: Intervention Waterbodies and Farms." in publish_box(client.get("/admin").text)

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
