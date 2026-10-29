"""The admin page: logging in, and uploading an Excel file through to approval."""

import io
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


@pytest.fixture
def app(engine, tmp_path):
    apply_changes(engine, load_schema())
    add_catchments(engine, WEST, EAST)
    app = create_app(Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        users={"tom": passwords.hash_password(PASSWORD)},
        secret_key="test secret",
        raw_files_dir=tmp_path,
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


def uploads_table(app) -> list[tuple]:
    with app.state.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(sa.text(
            "SELECT id, table_name, uploaded_by, status, rows_added, rows_changed, rows_removed FROM uploads ORDER BY id"
        ))]


# --- Logging in ----------------------------------------------------------------

def test_every_page_needs_a_login(app):
    client = TestClient(app)
    for path in ["/admin", "/admin/tables/ea_scores", "/admin/tables/ea_scores/download", "/admin/uploads/1"]:
        response = client.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/admin/login")
    assert upload(client, SCORES).headers["location"] == "/admin/login"


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

def test_only_tables_filled_by_excel_are_shown(client):
    page = client.get("/admin").text
    assert "EA Scores" in page and "Habitat &amp; Land Use" in page
    assert "Catchments" not in page
    assert client.get("/admin/tables/catchments").status_code == 404


def test_download_upload_preview_and_approve(app, client, tmp_path):
    download = client.get("/admin/tables/ea_scores/download")
    assert [c.value for c in load_workbook(io.BytesIO(download.content)).active[1]] == list(HEADINGS)

    response = upload(client, SCORES, name="October scores.xlsx")
    assert response.headers["location"] == "/admin/uploads/1"
    preview = client.get("/admin/uploads/1").text
    assert "Check the changes" in preview and "October scores.xlsx" in preview
    assert ea_scores(app.state.engine) == []  # nothing changes before approval

    page = approve(client, 1)
    assert page.url.path == "/admin/tables/ea_scores"
    assert "Done. EA Scores now matches October scores.xlsx: 2 added, 0 changed, 0 deleted." in page.text
    assert ea_scores(app.state.engine) == [(WEST, "Fish", 2025, "Poor", 0.16), (EAST, "Fish", 2025, "Good", 0.7)]
    assert uploads_table(app) == [(1, "ea_scores", "tom", "approved", 2, 0, 0)]
    (kept,) = (tmp_path / "ea_scores").iterdir()
    assert kept.read_bytes() == SCORES
    assert client.get("/admin/uploads/1/file").content == SCORES

    # Uploading the same file again changes nothing, so there's nothing to approve.
    page = upload(client, SCORES)
    assert page.headers["location"] == "/admin/tables/ea_scores"
    assert "is the same as the table, so there&#39;s nothing to change" in client.get(page.headers["location"]).text


def test_problems_are_shown_and_nothing_is_kept(app, client, tmp_path):
    response = upload(client, xlsx(HEADINGS, ("GB999", "Fish", "soon", None, None)))
    assert response.status_code == 422
    assert "Row 2, year: &#39;soon&#39; isn&#39;t a whole number." in response.text
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
    assert "Cancelled scores.xlsx. Nothing has been changed." in page.text
    assert "already been cancelled" in approve_anyway(client, 1).text
    assert ea_scores(app.state.engine) == []
    assert uploads_table(app)[0][3] == "cancelled"


def approve_anyway(client, upload_id):
    return client.post(f"/admin/uploads/{upload_id}/approve", data={"check": "anything"})
