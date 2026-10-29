"""The admin page's web pages.

    /admin                       choose a table
    /admin/tables/<table>        download it, upload an edited copy, recent uploads
    /admin/uploads/<id>          preview what an upload will change; approve or cancel

Every page needs a login. Only tables marked `filled_by: excel` in schema.yaml
appear, and each works the same way (see catalyst.importers.excel).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from catalyst.db import load_schema
from catalyst.importers import excel

from . import passwords, uploads
from .settings import Settings

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD_MB = 20
ROWS_SHOWN = 200  # per section of the preview
LOGIN_HOURS = 12
UK = ZoneInfo("Europe/London")

router = APIRouter(prefix="/admin")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="Catchment Catalyst admin", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.schema = load_schema()
    app.state.engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
    app.state.templates = _templates()
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
    user = passwords.log_in(request.app.state.settings.users, name, password)
    if user is None:
        return _render(request, "login.html", name=name, error="That name and password don't match.", status_code=401)
    request.session.clear()
    request.session["user"] = user
    return RedirectResponse("/admin", 303)


@router.post("/logout")
def log_out(request: Request):
    request.session.clear()
    request.session["message"] = "You've logged out."
    return RedirectResponse("/admin/login", 303)


# --- Tables ----------------------------------------------------------------------

def excel_table(request: Request, table_name: str, user: User) -> sa.Table:
    schema = request.app.state.schema
    if table_name not in schema.excel_tables:
        raise HTTPException(404, "There's no table by that name that can be uploaded here.")
    return schema.metadata.tables[table_name]


ExcelTable = Annotated[sa.Table, Depends(excel_table)]


@router.get("")
def home(request: Request, user: User):
    schema = request.app.state.schema
    tables = [schema.metadata.tables[name] for name in schema.excel_tables]
    with request.app.state.engine.connect() as conn:
        counts = {t.name: _count(conn, t) for t in tables}
        last = uploads.last_approved(conn, schema)
    return _render(request, "home.html", tables=tables, counts=counts, last=last)


@router.get("/tables/{table_name}")
def table_page(request: Request, table: ExcelTable):
    return _render_table(request, table)


@router.get("/tables/{table_name}/download")
def download(request: Request, table: ExcelTable):
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings().all()
    name = f"{table.name}_{datetime.datetime.now(UK):%Y-%m-%d}.xlsx"
    return Response(
        excel.write_table(table, rows),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/tables/{table_name}/upload")
def upload(request: Request, user: User, table: ExcelTable, file: Annotated[UploadFile | None, File()] = None):
    state = request.app.state
    if file is None or not file.filename:
        return _render_table(request, table, problems=["Choose a file to upload."], status_code=422)
    data = file.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        problems = [f"The file is bigger than {MAX_UPLOAD_MB} MB, which is too big for one table."]
        return _render_table(request, table, problems=problems, file_name=file.filename, status_code=422)
    try:
        rows = excel.read_upload(table, data)
        with state.engine.begin() as conn:
            comparison = excel.compare(conn, table, rows)
            if not comparison.has_changes:
                request.session["message"] = f"{file.filename} is the same as the table, so there's nothing to change."
                return RedirectResponse(f"/admin/tables/{table.name}", 303)
            upload_id = uploads.create(
                conn, state.schema, state.settings.raw_files_dir, table, file.filename, data, user, len(rows), comparison
            )
    except excel.UploadError as e:
        return _render_table(request, table, problems=e.problems, file_name=file.filename, status_code=422)
    return RedirectResponse(f"/admin/uploads/{upload_id}", 303)


def _render_table(request: Request, table: sa.Table, status_code: int = 200, **context):
    state = request.app.state
    with state.engine.connect() as conn:
        count = _count(conn, table)
        recent = uploads.recent(conn, state.schema, table.name)
    return _render(
        request, "table.html", table=table, count=count, recent=recent,
        key=excel.key_columns(table), status_code=status_code, **context,
    )


# --- Uploads ---------------------------------------------------------------------

@router.get("/uploads/{upload_id}")
def preview(request: Request, user: User, upload_id: int):
    state = request.app.state
    with state.engine.connect() as conn:
        upload = _get_upload(conn, state, upload_id)
        table = state.schema.metadata.tables[upload.table_name]
        comparison, problems = None, None
        if upload.status == uploads.PREVIEW:
            try:
                comparison = _compare(conn, state, table, upload)
            except excel.UploadError as e:  # e.g. a catchment it links to has since gone
                problems = e.problems
    return _render(
        request, "preview.html", upload=upload, table=table, comparison=comparison, problems=problems,
        key=excel.key_columns(table), rows_shown=ROWS_SHOWN,
    )


@router.post("/uploads/{upload_id}/approve")
def approve(request: Request, user: User, upload_id: int, check: Annotated[str, Form()] = ""):
    state = request.app.state
    here = RedirectResponse(f"/admin/uploads/{upload_id}", 303)
    try:
        with state.engine.begin() as conn:
            upload = _get_upload(conn, state, upload_id, for_update=True)
            if upload.status != uploads.PREVIEW:
                request.session["message"] = f"This upload has already been {upload.status}."
                return here
            table = state.schema.metadata.tables[upload.table_name]
            excel.lock(conn, table)
            comparison = _compare(conn, state, table, upload)
            if comparison.fingerprint != check:
                request.session["message"] = (
                    "The table has changed since this preview was shown, perhaps because someone else "
                    "uploaded a file. Nothing has been changed yet: check the changes below again."
                )
                return here
            excel.replace(conn, table, comparison)
            uploads.approve(conn, state.schema, upload_id, comparison)
    except excel.UploadError:
        request.session["message"] = "This file can no longer be used, so nothing has been changed. The problems are below."
        return here
    except sa.exc.DBAPIError as e:
        request.session["message"] = f"The database refused the changes, so nothing has been changed. It said: {e.orig}"
        return here
    request.session["message"] = (
        f"Done. {_title(table)} now matches {upload.file_name}: {len(comparison.added)} added, "
        f"{len(comparison.changed)} changed, {len(comparison.removed)} deleted."
    )
    return RedirectResponse(f"/admin/tables/{table.name}", 303)


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
    return RedirectResponse(f"/admin/tables/{upload.table_name}", 303)


@router.get("/uploads/{upload_id}/file")
def upload_file(request: Request, user: User, upload_id: int):
    state = request.app.state
    with state.engine.connect() as conn:
        upload = _get_upload(conn, state, upload_id)
    path = uploads.file_path(state.settings.raw_files_dir, upload)
    if not path.is_file():
        raise HTTPException(404, f"The file for upload {upload_id} isn't there any more ({upload.stored_as}).")
    return FileResponse(path, media_type=XLSX, filename=upload.file_name)


def _get_upload(conn: sa.Connection, state, upload_id: int, for_update: bool = False) -> sa.Row:
    upload = uploads.get(conn, state.schema, upload_id, for_update=for_update)
    if upload is None or upload.table_name not in state.schema.excel_tables:
        raise HTTPException(404, f"There's no upload {upload_id}.")
    return upload


def _compare(conn: sa.Connection, state, table: sa.Table, upload: sa.Row) -> excel.Comparison:
    """Read the kept file again and compare it with the table as it is now."""
    data = uploads.file_path(state.settings.raw_files_dir, upload).read_bytes()
    return excel.compare(conn, table, excel.read_upload(table, data))


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
    templates.env.globals.update(title=_title, type_label=excel.type_label)
    templates.env.filters.update(cell=_cell, when=_when, rows=_rows)
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
