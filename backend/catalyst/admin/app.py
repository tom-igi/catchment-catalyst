"""The admin page's web pages.

    /admin                            every table, as a diagram (see diagram.py). Click a
                                      table to see its columns and download it. Each source
                                      file and each Excel table has its own upload on the left
    /admin#<table>                    the diagram with a table's details open
    /admin#upload-<table or input>    ...or with an Excel table's or a source file's upload open
    /admin/tables/<table>/download    any table as an Excel file
    /admin/tables/<table>/example     the real data shown in its Transformation panel, as JSON (see examples.py)
    /admin/tables/<table>/upload      upload an edited copy (Excel tables only)
    /admin/inputs/<input>/upload      upload a source file as it came (see catalyst.importers.inputs)
    /admin/uploads/<id>               preview what an upload will change; approve or cancel
    /admin/publish                    publish the dashboards (the Publish button at the top of /admin)
    /admin/ai-input?catchment=<ID>    a waterbody's data, and its neighbours' up and downstream, as a text file
                                      for an AI to write its River Status Text from (see ai_input.py)
    /admin/screenshots                numbered screenshots of the dashboards: each part's table, by its
                                      number in the diagram (taken by screenshots/take.mjs)

Every page needs a login. Every table can be downloaded. Two kinds can be
uploaded: tables marked `filled_by: excel` in schema.yaml, as an edited copy of
the table (see catalyst.importers.excel), and tables marked `filled_by: input`,
by uploading their source file, which can fill several tables at once (see
catalyst.importers.inputs). An approved upload is only on the public
dashboards once someone presses Publish, which runs the publish step (see
catalyst.publish), so several uploads can be approved, then published at once.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from geoalchemy2 import Geometry
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from catalyst import publish
from catalyst.db import load_schema
from catalyst.importers import excel, inputs

from . import ai_input, diagram, examples, passwords, uploads
from .settings import Settings

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MEDIA_TYPES = {".xlsx": XLSX, ".xls": "application/vnd.ms-excel", ".csv": "text/csv"}
MAX_UPLOAD_MB = 20
ROWS_SHOWN = 200  # per section of the preview
PROBLEMS_SHOWN = 50
RECENT_UPLOADS = 10  # per table
LOGIN_HOURS = 12
UK = ZoneInfo("Europe/London")
SCREENSHOTS_DIR = Path(__file__).with_name("screenshots")  # the numbered screenshots, and screenshots.json
SCREENSHOT_NAME = re.compile(r"[\w-]+\.webp")

router = APIRouter(prefix="/admin")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="Catchment Catalyst admin", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.schema = load_schema()
    app.state.engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
    app.state.templates = _templates()
    app.state.screenshots_dir = SCREENSHOTS_DIR
    app.state.attempts = passwords.Attempts()  # wrong passwords, so someone can't keep guessing
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="catalyst_admin",
        max_age=LOGIN_HOURS * 3600,
        path="/admin",
        same_site="strict",  # the browser never sends it with requests from other sites
        https_only=settings.https_only,
    )
    app.include_router(router)
    app.add_exception_handler(LoginNeeded, lambda request, exc: RedirectResponse("/admin/login", 303))
    app.add_exception_handler(StarletteHTTPException, _error_page)
    app.add_exception_handler(sa.exc.DBAPIError, _database_error_page)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin", 303)

    return app


# --- Logging in ----------------------------------------------------------------

class LoginNeeded(Exception):
    pass


def logged_in_user(request: Request) -> str:
    user = request.session.get("user")
    if user not in request.app.state.settings.users:  # also logs out anyone removed from ADMIN_USERS
        raise LoginNeeded
    return user


User = Annotated[str, Depends(logged_in_user)]


@router.get("/login")
def login_page(request: Request):
    if request.session.get("user") in request.app.state.settings.users:
        return RedirectResponse("/admin", 303)
    return _render(request, "login.html")


@router.post("/login")
def log_in(request: Request, name: Annotated[str, Form()] = "", password: Annotated[str, Form()] = ""):
    attempts: passwords.Attempts = request.app.state.attempts
    address = request.client.host if request.client else ""
    wait = attempts.wait_minutes(name, address)
    if wait:
        return _render(request, "login.html", name=name, status_code=429, error=(
            f"Too many wrong passwords. Try again in {wait} minute{'' if wait == 1 else 's'}."
        ))
    user = passwords.log_in(request.app.state.settings.users, name, password)
    if user is None:
        attempts.wrong(name, address)
        return _render(request, "login.html", name=name, error="That name and password don't match.", status_code=401)
    attempts.right(name, address)
    request.session.clear()
    request.session["user"] = user
    return RedirectResponse("/admin", 303)


@router.post("/logout")
def log_out(request: Request):
    request.session.clear()
    request.session["message"] = "You've logged out."
    return RedirectResponse("/admin/login", 303)


# --- The diagram of every table ---------------------------------------------------

@router.get("")
def home(request: Request, user: User):
    return _render_home(request)


@router.get("/data-map", include_in_schema=False)
def old_data_map():  # where the diagram used to be
    return RedirectResponse("/admin", 303)


def _render_home(request: Request, status_code: int = 200, problems: dict | None = None):
    """The diagram, with each Excel table's uploads. `problems` are an upload's, shown in its table's details."""
    state = request.app.state
    schema = state.schema
    try:
        with state.engine.connect() as conn:
            counts = {t.name: _count(conn, t) for t in schema.metadata.tables.values()}
    except sa.exc.DBAPIError:  # e.g. a table that isn't made yet: show the page without row counts
        counts = None
    try:
        model = diagram.model(schema, counts)
    except ValueError as e:  # e.g. diagram.yaml names a table that's been renamed
        raise HTTPException(500, f"The page couldn't be made: {e}") from e
    with state.engine.connect() as conn:
        last = uploads.last_approved(conn, schema)
        for t in model["tables"]:
            t["download"] = _download_details(schema.metadata.tables[t["name"]])
            if t["name"] in schema.excel_tables:
                t["update"] = _excel_details(conn, state, schema.metadata.tables[t["name"]], last.get(t["name"]))
        for i in model["inputs"]:
            i["update"] = _input_details(conn, state, i["name"], last.get(i["name"]))
        publishing = _publish_details(conn, schema)
        ai_choices = ai_input.choices(conn, schema)
    if problems:
        model["problems"] = problems
    return _render(request, "home.html", model=model, publishing=publishing, ai_choices=ai_choices, status_code=status_code)


# --- Input for AI (at the bottom of /admin) ----------------------------------------------

@router.get("/ai-input")
def ai_input_download(request: Request, user: User, catchment: str = ""):
    """A waterbody's data, and its neighbours' up and downstream, as a text file to give an AI."""
    if not catchment:
        raise HTTPException(400, "Choose a waterbody first.")
    with request.app.state.engine.connect() as conn:
        try:
            file = ai_input.write(conn, request.app.state.schema, catchment, datetime.datetime.now(UK))
        except ai_input.NotFound:
            raise HTTPException(404, "There's no waterbody with that ID.") from None
    return Response(
        file.text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": _attachment(file.name)},
    )


# --- The numbered screenshots of the dashboards --------------------------------------

@router.get("/screenshots")
def screenshots_page(request: Request, user: User):
    """Each screenshot, with the number of each part's table on it (as on that table's box on the diagram)."""
    try:
        model = diagram.model(request.app.state.schema)
    except ValueError as e:
        raise HTTPException(500, f"The page couldn't be made: {e}") from e
    return _render(request, "screenshots.html", **_screenshots(request.app.state.screenshots_dir, model))


@router.get("/screenshots/{name}")
def screenshot(request: Request, name: str, user: User):
    path = request.app.state.screenshots_dir / name
    if not SCREENSHOT_NAME.fullmatch(name) or not path.is_file():
        raise HTTPException(404, "There's no screenshot with that name.")
    return FileResponse(path, media_type="image/webp")


def _screenshots(folder: Path, model: dict) -> dict:
    """screenshots.json (written by screenshots/take.mjs), and any number on them that isn't its table's number any
    more (diagram.yaml changed since they were taken)."""
    try:
        taken = json.loads((folder / "screenshots.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"shots": [], "out_of_date": []}
    numbers = {t["name"]: t["number"] for t in model["tables"]}
    out_of_date = {n["number"] for shot in taken["shots"] for n in shot["numbers"] if numbers.get(n["table"]) != n["number"]}
    shots = [{**shot, "id": shot["file"].rsplit(".", 1)[0]} for shot in taken["shots"]]
    return {"shots": shots, "out_of_date": sorted(out_of_date)}


def _publish_details(conn: sa.Connection, schema) -> dict:
    """What the Publish box says: when the dashboards were last published, and what's been approved since."""
    last = publish.last_publish(conn, schema)
    if last is None:  # not since publishes were first recorded, so what's been approved since is unknown
        return {"last": None, "waiting": 0, "tables": []}
    waiting = uploads.approved_since(conn, schema, last.published_at)
    names = dict.fromkeys(u.uploaded_to for u in waiting)  # each once, in the order approved
    return {
        "last": {"when": _when(last.published_at), "who": last.published_by},
        "waiting": len(waiting),
        "tables": [_uploaded_to_title(schema, n) for n in names],
    }


def _download_details(table: sa.Table) -> dict:
    """What a table's details need for its download."""
    included = excel.downloadable_columns(table)
    return {
        "url": f"/admin/tables/{table.name}/download",
        "left_out": [c.name for c in table.columns if c not in included],  # map shapes and files
        "left_out_why": _left_out_why([c for c in table.columns if c not in included]),
    }


def _left_out_why(columns: list[sa.Column]) -> str | None:
    """Why columns are left out of a table's download, in words."""
    why = []
    if any(isinstance(c.type, Geometry) for c in columns):
        why.append("map shapes")
    if any(isinstance(c.type, sa.LargeBinary) for c in columns):
        why.append("the files themselves (each can be downloaded from its upload)")
    return "; ".join(why) or None


def _excel_details(conn: sa.Connection, state, table: sa.Table, last: sa.Row | None) -> dict:
    """What a table's details need for downloading it, uploading it, and its recent uploads."""
    return {
        "download_url": f"/admin/tables/{table.name}/download",
        "upload_url": f"/admin/tables/{table.name}/upload",
        "key": excel.key_columns(table),
        **_recent_uploads(conn, state, table.name, last),
    }


def _input_details(conn: sa.Connection, state, name: str, last: sa.Row | None) -> dict:
    """What a source file's upload needs: where to upload it, and its recent uploads."""
    return {"upload_url": f"/admin/inputs/{name}/upload", **_recent_uploads(conn, state, name, last)}


def _recent_uploads(conn: sa.Connection, state, uploaded_to: str, last: sa.Row | None) -> dict:
    return {
        "last": {"when": _when(last.approved_at), "who": last.uploaded_by, "file": last.file_name,
                 "file_url": f"/admin/uploads/{last.id}/file"} if last else None,
        "recent": [
            {
                "id": u.id,
                "when": _when(u.uploaded_at),
                "who": u.uploaded_by,
                "file": u.file_name,
                "file_url": f"/admin/uploads/{u.id}/file",
                "url": f"/admin/uploads/{u.id}",
                "status": u.status,
                "added": u.rows_added,
                "changed": u.rows_changed,
                "removed": u.rows_removed,
            }
            for u in uploads.recent(conn, state.schema, uploaded_to, RECENT_UPLOADS)
        ],
    }


# --- Tables ----------------------------------------------------------------------

def any_table(request: Request, table_name: str, user: User) -> sa.Table:
    tables = request.app.state.schema.metadata.tables
    if table_name not in tables:
        raise HTTPException(404, "There's no table by that name.")
    return tables[table_name]


AnyTable = Annotated[sa.Table, Depends(any_table)]


def excel_table(request: Request, table_name: str, user: User) -> sa.Table:
    schema = request.app.state.schema
    if table_name not in schema.excel_tables:
        raise HTTPException(404, "There's no table by that name that can be uploaded here.")
    return schema.metadata.tables[table_name]


ExcelTable = Annotated[sa.Table, Depends(excel_table)]


@router.get("/tables/{table_name}")
def table_page(table: ExcelTable):  # each Excel table's own page, before the diagram had its details
    return RedirectResponse(_upload_panel(table.name), 303)


@router.get("/tables/{table_name}/download")
def download(request: Request, table: AnyTable):
    columns = excel.downloadable_columns(table)  # only these are read: map shapes can be large
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(sa.select(*columns).order_by(*table.primary_key.columns)).mappings().all()
    name = f"{table.name}_{datetime.datetime.now(UK):%Y-%m-%d}.xlsx"
    return Response(
        excel.write_table(table, rows),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/tables/{table_name}/example")
def table_example(request: Request, table: AnyTable):
    """The real data in a source file's or Excel table's Transformation panel: from its last approved file, as kept
    with its upload, or made from the file now if it wasn't kept (an upload before examples were) or the formulas'
    words have changed since."""
    state = request.app.state
    schema = state.schema
    fill = table.info.get("filled_by")
    if fill not in {"input", "excel"}:
        raise HTTPException(404, "Only a source file's or an Excel table's example is made from its file.")
    uploaded_to = table.info["input"] if fill == "input" else table.name
    steps = list(inputs.INPUTS[uploaded_to].table_steps(table.name)) if fill == "input" else []
    with state.engine.connect() as conn:
        last = uploads.last_approved(conn, schema).get(uploaded_to)
        kept = (uploads.examples(conn, schema, last.id) or {}).get(table.name) if last else None
    if last is None:
        what = inputs.INPUTS[uploaded_to].title if fill == "input" else "Excel"
        return JSONResponse({"missing": f"No {what} file approved yet, so no example.",
                             "out": _first_rows(state, table)})
    if examples.out_of_date(kept, steps):
        try:
            with state.engine.begin() as conn:
                made = examples.make(conn, schema, uploaded_to, uploads.file(conn, schema, last.id), last.file_name)
                uploads.keep_examples(conn, schema, last.id, made)
        except excel.UploadError:
            return JSONResponse({"missing": f"The last approved file, {last.file_name}, can't be read as the table is "
                                            "now, so no example.", "out": _first_rows(state, table)})
        kept = made.get(table.name)
    return JSONResponse({
        **examples.shown(kept or {}, steps),
        "file": last.file_name, "when": _when(last.approved_at), "upload_url": f"/admin/uploads/{last.id}",
        "file_url": f"/admin/uploads/{last.id}/file",
    })


def _first_rows(state, table: sa.Table) -> dict:
    """A table's first few rows, as an example's `out`, for a table with no file to make one from."""
    columns = excel.downloadable_columns(table)
    with state.engine.connect() as conn:
        rows = conn.execute(sa.select(*columns).order_by(*table.primary_key.columns).limit(examples.ROWS)).all()
        total = _count(conn, table)
    return {"columns": [c.name for c in columns], "rows": [[examples.plain(v) for v in row] for row in rows],
            "example": [], "total": total}


@router.post("/tables/{table_name}/upload")
def upload(request: Request, user: User, table: ExcelTable, file: Annotated[UploadFile | None, File()] = None):
    return _upload(request, user, table.name, file)


def source_input(request: Request, input_name: str, user: User) -> inputs.Input:
    if input_name not in inputs.INPUTS or input_name not in request.app.state.schema.input_tables.values():
        raise HTTPException(404, "There's no source file by that name that can be uploaded here.")
    return inputs.INPUTS[input_name]


SourceInput = Annotated[inputs.Input, Depends(source_input)]


@router.post("/inputs/{input_name}/upload")
def upload_source_file(request: Request, user: User, source: SourceInput, file: Annotated[UploadFile | None, File()] = None):
    return _upload(request, user, source.name, file)


def _upload(request: Request, user: str, uploaded_to: str, file: UploadFile | None):
    """Read an upload for a table or a source file, and keep it for its preview if it changes anything."""
    state = request.app.state
    if file is None or not file.filename:
        return _upload_problems(request, uploaded_to, None, ["Choose a file to upload."])
    data = file.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        problems = [f"The file is bigger than {MAX_UPLOAD_MB} MB, which is too big to upload here."]
        return _upload_problems(request, uploaded_to, file.filename, problems)
    same = f"{file.filename} is the same as {{tables}}, so there's nothing to change."
    return _keep_for_preview(request, user, uploaded_to, file.filename, data, same)


def _keep_for_preview(request: Request, user: str, uploaded_to: str, file_name: str, data: bytes, same: str):
    """Compare a file with the table(s) it fills, and keep it as an upload to preview if it changes anything.
    `same` is the message if it doesn't, with {tables} for "the table" or "the tables it fills"."""
    state = request.app.state
    try:
        with state.engine.begin() as conn:
            changes = _changes(conn, state, uploaded_to, data, file_name)
            if not changes.has_changes:
                tables = "the table" if len(changes.comparisons) == 1 else "the tables it fills"
                request.session["message"] = same.format(tables=tables)
                return RedirectResponse(_upload_panel(uploaded_to), 303)
            upload_id = uploads.create(
                conn, state.schema, uploaded_to, file_name, data, user, changes.rows_in_file, changes.comparisons,
                source_file=changes.source_file, examples=changes.examples,
            )
    except excel.UploadError as e:
        return _upload_problems(request, uploaded_to, file_name, e.problems)
    return RedirectResponse(f"/admin/uploads/{upload_id}", 303)


def _upload_problems(request: Request, uploaded_to: str, file_name: str | None, problems: list[str]):
    """The diagram again, with the upload open (the table's or the source file's) and the file's problems in it."""
    return _render_home(request, status_code=422, problems={
        "uploaded_to": uploaded_to,
        "file": file_name,
        "items": problems[:PROBLEMS_SHOWN],
        "more": max(len(problems) - PROBLEMS_SHOWN, 0),
    })


def _upload_panel(uploaded_to: str) -> str:
    """The diagram, with the Excel table's or the source file's upload open."""
    return f"/admin#upload-{uploaded_to}"


# --- Uploads ---------------------------------------------------------------------

@router.get("/uploads/{upload_id}")
def preview(request: Request, user: User, upload_id: int):
    state = request.app.state
    with state.engine.connect() as conn:
        upload = _get_upload(conn, state, upload_id)
        changes, problems = None, None
        if upload.status == uploads.PREVIEW:
            try:
                changes = _kept_changes(conn, state, upload)
            except excel.UploadError as e:  # e.g. a catchment it links to has since gone
                problems = e.problems
    tables = state.schema.metadata.tables
    parts = [
        {"table": tables[name], "comparison": comparison, "key": excel.key_columns(tables[name])}
        for name, comparison in (changes.comparisons.items() if changes else [])
    ]
    return _render(
        request, "preview.html", upload=upload, changes=changes, parts=parts, problems=problems,
        uploaded_to=_uploaded_to_title(state.schema, upload.uploaded_to), back=_upload_panel(upload.uploaded_to),
        source_file=upload.uploaded_to in inputs.INPUTS,
        filled=_filled_titles(state.schema, upload), rows_shown=ROWS_SHOWN,
    )


@router.post("/uploads/{upload_id}/approve")
def approve(request: Request, user: User, upload_id: int, check: Annotated[str, Form()] = ""):
    state = request.app.state
    here = RedirectResponse(f"/admin/uploads/{upload_id}", 303)
    try:
        with state.engine.begin() as conn:
            # Not while a publish is reading the tables, and no publish until this is saved, so the Publish box's
            # "Everything approved is on it" is right (see catalyst.publish.run.lock).
            publish.run.lock(conn)
            upload = _get_upload(conn, state, upload_id, for_update=True)
            if upload.status != uploads.PREVIEW:
                request.session["message"] = f"This upload has already been {upload.status}."
                return here
            for name in sorted(_filled(upload.uploaded_to)):  # always in the same order
                excel.lock(conn, state.schema.metadata.tables[name])
            changes = _kept_changes(conn, state, upload)
            if changes.fingerprint != check:
                request.session["message"] = (
                    f"{'The table has' if len(changes.comparisons) == 1 else 'The tables have'} changed since this "
                    "preview was shown, perhaps because someone else uploaded a file. Nothing has been changed yet: "
                    "check the changes below again."
                )
                return here
            for name, comparison in changes.comparisons.items():
                excel.replace(conn, state.schema.metadata.tables[name], comparison)
            uploads.approve(conn, state.schema, upload_id, changes.comparisons, source_file=changes.source_file)
    except excel.UploadError:
        request.session["message"] = "This file can no longer be used, so nothing has been changed. The problems are below."
        return here
    except sa.exc.DBAPIError as e:
        request.session["message"] = f"The database refused the changes, so nothing has been changed. It said: {e.orig}"
        return here
    comparisons = changes.comparisons.values()
    titles = [_title(state.schema.metadata.tables[name]) for name in changes.comparisons]
    request.session["message"] = (
        f"Done. {_and(titles)} now {'matches' if len(titles) == 1 else 'match'} {upload.file_name}: "
        f"{sum(len(c.added) for c in comparisons)} added, {sum(len(c.changed) for c in comparisons)} changed, "
        f"{sum(len(c.removed) for c in comparisons)} deleted. It will be on the public dashboard once you publish."
    )
    return RedirectResponse(_upload_panel(upload.uploaded_to), 303)


@router.post("/uploads/{upload_id}/cancel")
def cancel(request: Request, user: User, upload_id: int):
    state = request.app.state
    with state.engine.begin() as conn:
        upload = _get_upload(conn, state, upload_id, for_update=True)
        if upload.status != uploads.PREVIEW:
            request.session["message"] = f"This upload has already been {upload.status}."
            return RedirectResponse(f"/admin/uploads/{upload_id}", 303)
        uploads.cancel(conn, state.schema, upload_id)
    request.session["message"] = f"Cancelled {upload.file_name}. Nothing has been changed."
    return RedirectResponse(_upload_panel(upload.uploaded_to), 303)


@router.get("/uploads/{upload_id}/file")
def upload_file(request: Request, user: User, upload_id: int):
    state = request.app.state
    with state.engine.connect() as conn:
        upload = _get_upload(conn, state, upload_id)
        data = uploads.file(conn, state.schema, upload_id)
    suffix = Path(upload.file_name).suffix.lower()
    return Response(data, media_type=MEDIA_TYPES.get(suffix, XLSX), headers={"Content-Disposition": _attachment(upload.file_name)})


def _attachment(file_name: str) -> str:
    """A download under the name it was uploaded with, written as FileResponse does."""
    quoted = quote(file_name)
    return f"attachment; filename*=utf-8''{quoted}" if quoted != file_name else f'attachment; filename="{file_name}"'


# --- What an upload changes ----------------------------------------------------------

@dataclass
class Changes:
    """What an upload would change: a Comparison for each table it fills, and anything a source file left out."""
    comparisons: dict[str, excel.Comparison]
    rows_in_file: int
    source_file: bool = False
    notes: list[str] = field(default_factory=list)
    examples: dict[str, dict] = field(default_factory=dict)  # each table's, for its Transformation panel

    @property
    def has_changes(self) -> bool:
        return any(c.has_changes for c in self.comparisons.values())

    @property
    def fingerprint(self) -> str:
        """Identifies exactly these changes, to every table (see Comparison.fingerprint)."""
        parts = sorted(f"{name} {c.fingerprint}" for name, c in self.comparisons.items())
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _changes(conn: sa.Connection, state, uploaded_to: str, data: bytes, file_name: str) -> Changes:
    """Read a file uploaded to a table or a source file, and compare it with the table(s). Raises UploadError."""
    schema = state.schema
    if uploaded_to in inputs.INPUTS:
        source = inputs.INPUTS[uploaded_to]
        result = source.run(conn, schema, data, file_name)
        comparisons = {name: excel.compare(conn, schema.metadata.tables[name], rows) for name, rows in result.tables.items()}
        made = examples.for_input(conn, schema, source, result)
        return Changes(comparisons, result.rows_read, source_file=True, notes=result.notes, examples=made)
    table = schema.metadata.tables[uploaded_to]
    rows = excel.read_upload(table, data)
    return Changes({table.name: excel.compare(conn, table, rows)}, len(rows), examples=examples.for_excel(table, rows))


def _kept_changes(conn: sa.Connection, state, upload: sa.Row) -> Changes:
    """Read the kept file again and compare it with the table(s) as they are now."""
    data = uploads.file(conn, state.schema, upload.id)
    return _changes(conn, state, upload.uploaded_to, data, upload.file_name)


def _filled(uploaded_to: str) -> list[str]:
    """The tables an upload fills: its source file's, or its own table."""
    return inputs.INPUTS[uploaded_to].tables if uploaded_to in inputs.INPUTS else [uploaded_to]


def _filled_titles(schema, upload: sa.Row) -> list[str]:
    tables = schema.metadata.tables
    return [_title(tables[name]) for name in _filled(upload.uploaded_to) if name in tables]


def _uploaded_to_title(schema, name: str) -> str:
    """What an upload was for, by name: a table's title, or a source file's."""
    if name in inputs.INPUTS:
        return inputs.INPUTS[name].title
    tables = schema.metadata.tables
    return _title(tables[name]) if name in tables else name


# --- Publishing -------------------------------------------------------------------

@router.post("/publish")
def publish_dashboards(request: Request, user: User):
    """Write every location's dashboard again from the database, as the publish command does."""
    state = request.app.state
    try:
        published = publish.publish_all(state.engine, state.schema, state.settings.published_dir, published_by=user)
    except publish.PublishProblem as e:
        request.session["message"] = f"Nothing has been published. {e}"
    except sa.exc.DBAPIError as e:
        request.session["message"] = f"Nothing has been published, because the database gave an error. It said: {e.orig}"
    except OSError as e:  # e.g. the folder for the pages can't be written to
        request.session["message"] = (
            f"The dashboard's pages couldn't all be written, so it may not show the latest data. The error was: {e}"
        )
    else:
        names = _and([l.name for l in published])
        request.session["message"] = f"Published {names}. The public dashboard now shows everything approved so far."
    return RedirectResponse("/admin", 303)


def _get_upload(conn: sa.Connection, state, upload_id: int, for_update: bool = False) -> sa.Row:
    """An upload that can still be shown: to a table filled by Excel, or a source file that fills tables."""
    upload = uploads.get(conn, state.schema, upload_id, for_update=for_update)
    if upload is None or (
        upload.uploaded_to not in state.schema.excel_tables
        and upload.uploaded_to not in state.schema.input_tables.values()
    ):
        raise HTTPException(404, f"There's no upload {upload_id}.")
    return upload


def _count(conn: sa.Connection, table: sa.Table) -> int:
    return conn.scalar(sa.select(sa.func.count()).select_from(table))


# --- Pages -----------------------------------------------------------------------

def _render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("user", request.session.get("user"))
    context["message"] = request.session.pop("message", None)
    return request.app.state.templates.TemplateResponse(request, template, context, status_code=status_code)


def _error_page(request: Request, exc: StarletteHTTPException):
    return _render(request, "error.html", error=exc.detail, status_code=exc.status_code)


def _database_error_page(request: Request, exc: sa.exc.DBAPIError):
    error = f"The database gave an error: {exc.orig}. If a table is missing, run `schema apply` first."
    return _render(request, "error.html", error=error, status_code=500)


def _templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
    templates.env.globals.update(title=_title)
    templates.env.filters.update(cell=_cell, when=_when, rows=_rows, and_list=_and)
    return templates


def _title(table: sa.Table) -> str:
    return table.info.get("title") or table.name.replace("_", " ").capitalize()


def _cell(value: Any) -> str:
    """A value as shown in the preview."""
    if value is None:
        return "(empty)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _when(value: datetime.datetime | None) -> str:
    if value is None:
        return ""
    local = value.astimezone(UK)
    return f"{local.day} {local:%b %Y, %H:%M}"


def _rows(number: int) -> str:
    return f"{number:,} row{'' if number == 1 else 's'}"


def _and(words: list[str]) -> str:
    """['A', 'B', 'C'] -> 'A, B and C'."""
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
