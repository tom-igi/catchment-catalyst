"""The admin page: logging in, uploading an Excel file through to approval, and publishing.

The page itself (the diagram of every table) is tested in test_diagram.py.
"""

import io
import json
import re

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from catalyst.admin import passwords
from catalyst.admin.app import create_app
from catalyst.admin.settings import Settings, SettingsError
from catalyst.db import load_schema
from catalyst.db.sync import apply_changes

from .test_excel import EAST, HEADINGS, WEST, add_catchments, ea_scores, xlsx

PASSWORD = "a long test password"
SCORES = xlsx(HEADINGS, (WEST, "Fish", 2025, "Poor", 0.16), (EAST, "Fish", 2025, "Good", 0.7))
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


def upload(client, data, table="ea_scores", name="scores.xlsx"):
    return client.post(f"/admin/tables/{table}/upload", files={"file": (name, data)}, follow_redirects=False)


def approve(client, upload_id):
    page = client.get(f"/admin/uploads/{upload_id}").text
    check = re.search(r'name="check" value="(\w+)"', page).group(1)
    return client.post(f"/admin/uploads/{upload_id}/approve", data={"check": check})


def page_model(page: str) -> dict:
    """What the admin page's diagram is drawn from."""
    return json.loads(MODEL_TAG.search(page).group(1))


def table_details(client, table="ea_scores") -> dict:
    """What the admin page knows about a table."""
    return next(t for t in page_model(client.get("/admin").text)["tables"] if t["name"] == table)


def uploads_table(app) -> list[tuple]:
    with app.state.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(
            "SELECT id, table_name, uploaded_by, status, rows_added, rows_changed, rows_removed FROM uploads ORDER BY id"
        ))]


# --- Logging in ----------------------------------------------------------------

def test_every_page_needs_a_login(app):
    client = TestClient(app)
    for path in ["/admin", "/admin/tables/ea_scores", "/admin/tables/catchments/download", "/admin/uploads/1"]:
        response = client.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/admin/login")
    assert upload(client, SCORES).headers["location"] == "/admin/login"
    assert client.post("/admin/publish", follow_redirects=False).headers["location"] == "/admin/login"


def test_a_wrong_password_is_refused(app):
    client = TestClient(app)
    for name, password in [("tom", "wrong"), ("nobody", PASSWORD)]:
        response = client.post("/admin/login", data={"name": name, "password": password})
        assert response.status_code == 401
        assert "That name and password don&#39;t match." in response.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


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
    assert {"ea_scores", "habitat_land_use", "risk_levels", "location_text"} <= set(app.state.schema.excel_tables)
    assert "ea_classifications" not in app.state.schema.excel_tables
    assert table_details(client)["update"]["download_url"] == "/admin/tables/ea_scores/download"
    assert table_details(client)["update"]["key"] == ["catchment_id", "measure", "year"]
    assert client.get("/admin/tables/catchments").status_code == 404
    assert upload(client, SCORES, table="catchments").status_code == 404


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
    response = client.get("/admin/tables/ea_scores", follow_redirects=False)
    assert response.headers["location"] == "/admin#upload-ea_scores"  # with its upload open
    assert client.get("/admin/data-map", follow_redirects=False).headers["location"] == "/admin"


def test_download_upload_preview_and_approve(app, client, tmp_path):
    download = client.get("/admin/tables/ea_scores/download")
    assert [c.value for c in load_workbook(io.BytesIO(download.content)).active[1]] == list(HEADINGS)

    response = upload(client, SCORES, name="October scores.xlsx")
    assert response.headers["location"] == "/admin/uploads/1"
    preview = client.get("/admin/uploads/1").text
    assert "Check the changes" in preview and "October scores.xlsx" in preview
    assert ea_scores(app.state.engine) == []  # nothing changes before approval
    (waiting,) = table_details(client)["update"]["recent"]
    assert (waiting["status"], waiting["url"], waiting["file"]) == ("preview", "/admin/uploads/1", "October scores.xlsx")

    page = approve(client, 1)
    assert page.history[-1].headers["location"] == "/admin#upload-ea_scores"  # back to the table's upload
    assert "Done. EA Scores now matches October scores.xlsx: 2 added, 0 changed, 0 deleted." in page.text
    details = next(t for t in page_model(page.text)["tables"] if t["name"] == "ea_scores")
    assert (details["rows"], details["update"]["last"]["who"], details["update"]["recent"][0]["status"]) == (2, "tom", "approved")
    assert ea_scores(app.state.engine) == [(WEST, "Fish", 2025, "Poor", 0.16), (EAST, "Fish", 2025, "Good", 0.7)]
    assert uploads_table(app) == [(1, "ea_scores", "tom", "approved", 2, 0, 0)]
    (kept,) = (tmp_path / "ea_scores").iterdir()
    assert kept.read_bytes() == SCORES
    assert client.get("/admin/uploads/1/file").content == SCORES

    # Uploading the same file again changes nothing, so there's nothing to approve.
    page = upload(client, SCORES)
    assert page.headers["location"] == "/admin#upload-ea_scores"
    assert "is the same as the table, so there&#39;s nothing to change" in client.get(page.headers["location"]).text


def test_problems_are_shown_and_nothing_is_kept(app, client, tmp_path):
    response = upload(client, xlsx(HEADINGS, ("GB999", "Fish", "soon", None, None)))
    assert response.status_code == 422
    problems = page_model(response.text)["problems"]  # shown in the table's upload, opened by the page
    assert (problems["table"], problems["file"], problems["more"]) == ("ea_scores", "scores.xlsx", 0)
    assert "Row 2, year: 'soon' isn't a whole number." in problems["items"]
    assert uploads_table(app) == []
    assert list(tmp_path.iterdir()) == []


def test_deleting_rows_is_warned_about(client):
    upload(client, SCORES)
    approve(client, 1)
    upload(client, xlsx(HEADINGS, (WEST, "Fish", 2025, "Poor", 0.16)))
    assert "1 row will be deleted," in client.get("/admin/uploads/2").text
    upload(client, xlsx(HEADINGS))
    assert "This deletes every row that" in client.get("/admin/uploads/3").text


def test_a_preview_that_is_out_of_date_is_not_approved(app, client):
    upload(client, SCORES)
    page = client.get("/admin/uploads/1").text
    check = re.search(r'name="check" value="(\w+)"', page).group(1)
    with app.state.engine.begin() as conn:  # someone else changes the table meanwhile
        conn.execute(sa.text(f"INSERT INTO ea_scores VALUES ('{WEST}', 'Fish', 2025, 'Bad', 0.1)"))

    page = client.post("/admin/uploads/1/approve", data={"check": check})
    assert page.url.path == "/admin/uploads/1"
    assert "The table has changed since this preview was shown" in page.text
    assert ea_scores(app.state.engine) == [(WEST, "Fish", 2025, "Bad", 0.1)]
    assert uploads_table(app)[0][3] == "preview"

    approve(client, 1)  # with the up-to-date preview
    assert ea_scores(app.state.engine) == [(WEST, "Fish", 2025, "Poor", 0.16), (EAST, "Fish", 2025, "Good", 0.7)]


def test_cancelling(app, client):
    upload(client, SCORES)
    page = client.post("/admin/uploads/1/cancel")
    assert page.history[-1].headers["location"] == "/admin#upload-ea_scores"
    assert "Cancelled scores.xlsx. Nothing has been changed." in page.text
    assert "already been cancelled" in approve_anyway(client, 1).text
    assert ea_scores(app.state.engine) == []
    assert uploads_table(app)[0][3] == "cancelled"


def approve_anyway(client, upload_id):
    return client.post(f"/admin/uploads/{upload_id}/approve", data={"check": "anything"})


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
    upload(client, SCORES)
    page = approve(client, 1)
    assert "It will be on the public dashboard once you publish." in page.text
    upload(client, xlsx(HEADINGS, (WEST, "Fish", 2025, "Poor", 0.16)))
    approve(client, 2)
    page = client.get("/admin").text
    assert "2 uploads approved since the last publish, so not on it yet: EA Scores." in publish_box(page)
    assert '<section class="publish is-waiting"' in page
    with app.state.engine.begin() as conn:  # a different table
        conn.execute(sa.text("UPDATE uploads SET table_name = 'farms' WHERE id = 2"))
    assert "so not on it yet: EA Scores and Farms." in publish_box(client.get("/admin").text)

    client.post("/admin/publish")
    assert "Everything approved is on it." in publish_box(client.get("/admin").text)
    assert published_by(app) == ["tom", "tom"]


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
