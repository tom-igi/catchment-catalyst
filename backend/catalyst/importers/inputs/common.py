"""What every source file has in common: reading it, matching its rows to catchments, and its steps.

An input reads one sheet of its file (or several, by name) by the column
headings in row 1, as the original Power BI dashboard did (Power Query's
"Promoted Headers"), so the columns can move about. Headings are matched
ignoring case, spaces and line breaks ("Beef Density\\nPer SqKm" is "Beef
Density Per SqKm").
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
import xlrd
from openpyxl import load_workbook

from catalyst.db import Schema
from catalyst.importers.excel import FileRow, UploadError

NAMES_LISTED = 10  # in notes and problems
READS = {".xlsx": "Excel workbook", ".xls": "older Excel workbook", ".csv": "CSV file"}


@dataclass(frozen=True)
class Step:
    """How some of a table's columns are worked out: from which inputs, how (in words), and where that is in
    the original Power BI file (e.g. "Power Query, APHA Livestock Data: step Custom1").

    `inputs` are the file's columns it reads, or the table's own columns worked out by an earlier step (or,
    rarely, another table the same file fills). The admin page shows them as the step's inputs."""
    columns: tuple[str, ...]  # the table's columns it fills
    inputs: tuple[str, ...]
    text: str
    power_bi: str


@dataclass
class SourceRow:
    line: int  # the row's number in the file; the headings are row 1
    cells: dict[str, Any]  # heading (as the input names it) -> value
    catchment_id: str = ""
    sheet: str = ""  # for an input that reads several sheets, the sheet it's on

    @property
    def where(self) -> str:
        """Where it is in the file, for problems: e.g. Row 5, or Phosphate Point vs Diffuse, row 5."""
        return f"{self.sheet}, row {self.line}" if self.sheet else f"Row {self.line}"


@dataclass
class Result:
    """What a source file fills: each table's rows, and what was left out on the way."""
    tables: dict[str, list[FileRow]]
    rows_read: int
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Input:
    """One of the files the original Power BI dashboard read, and the tables worked out from it."""
    name: str  # its code: `input` in schema.yaml, e.g. apha_livestock
    title: str  # e.g. APHA livestock data
    provider: str  # where the file comes from, in a few words
    file: str  # the file the original read, e.g. APHA Livestock Data Feb 2026.xlsx
    sheet: str | None  # the sheet it read; None for the first (or a CSV file)
    headings: tuple[str, ...]  # the columns it reads
    waterbody_heading: str  # the column with each row's waterbody: its name, or with `by_id`, its ID
    query: str  # the original Power BI file's query (table) for it, e.g. APHA Livestock Data
    match: str  # how the original matched its rows to waterbodies, e.g. its relationship
    steps: dict[str, tuple[Step, ...]]  # each table it fills -> how its columns are worked out, in order (but catchment_id)
    # (rows, problems, notes) -> each table's rows. Problems stop the upload; notes are shown in its preview.
    work_out: Callable[[list[SourceRow], list[str], list[str]], dict[str, list[FileRow]]]
    url: str | None = None  # the provider's web page, if any
    by_id: bool = False  # rows are matched by the waterbody's ID (the EA's), not its name
    # A column with each row's EA management catchment (e.g. North Devon), for a file covering more than one, where
    # waterbody names repeat: a row only matches a catchment in the same management catchment.
    area_heading: str | None = None
    one_row_each: bool = True  # each waterbody has one row; False for several (e.g. a row per habitat)
    # More sheets it reads, by their exact names -> their columns (each with the waterbody column too). With
    # these, `sheet` must be there by its name as well, and each row says which sheet it's on.
    more_sheets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    table_sheets: dict[str, str] = field(default_factory=dict)  # a table that's from another of the sheets -> it

    @property
    def tables(self) -> list[str]:
        return list(self.steps)

    @property
    def match_step(self) -> Step:
        """How each row's catchment_id is found: the first step for every table."""
        area = (f" and its {self.area_heading} (as waterbody names repeat across England; the original matched by "
                "name alone)") if self.area_heading else ""
        return Step(
            ("catchment_id",), (self.waterbody_heading, *([self.area_heading] if self.area_heading else [])),
            f"Matched to a catchment by its waterbody {'ID' if self.by_id else 'name'}{area}. Rows for anywhere else "
            "are left out, and the preview lists them.",
            self.match,
        )

    def table_steps(self, table: str) -> tuple[Step, ...]:
        """How each of the table's columns is worked out, in order, starting with catchment_id."""
        return (self.match_step, *self.steps[table])

    def table_sheet(self, table: str) -> str | None:
        """The sheet the table is worked out from (None for a CSV file or the first sheet)."""
        return self.table_sheets.get(table, self.sheet)

    def file_columns(self, table: str) -> list[str]:
        """The file's columns the table is worked out from, in the file's order."""
        used = {name for step in self.table_steps(table) for name in step.inputs}
        sheet = self.table_sheet(table)
        headings = self.headings if sheet == self.sheet else self.more_sheets[sheet]
        return [h for h in headings if h in used]

    def run(self, conn: sa.Connection, schema: Schema, data: bytes, file_name: str) -> Result:
        """Read the file and work out every table's rows. Raises UploadError listing every problem."""
        sheets = [(self.sheet, self.headings), *self.more_sheets.items()]
        rows = [row for found in read_sheets(data, file_name, sheets, by_name=bool(self.more_sheets)) for row in found]
        notes, problems = [], []
        matched = _match(conn, schema, self.waterbody_heading, self.by_id, self.one_row_each, rows, notes, problems,
                         area_heading=self.area_heading)
        tables = self.work_out(matched, problems, notes) if not problems else {}
        for name, table_rows in tables.items():
            problems.extend(_missing_values(schema.metadata.tables[name], table_rows))
        if problems:
            raise UploadError(problems)
        return Result(tables, len(rows), notes)


# --- Reading the file ------------------------------------------------------------

def heading_key(text: Any) -> str:
    """A heading as it's compared: no case, and spaces and line breaks made single spaces."""
    return " ".join(str(text if text is not None else "").split()).casefold()


def read_sheet(data: bytes, file_name: str, sheet: str | None, headings: tuple[str, ...]) -> list[SourceRow]:
    """The rows of the sheet, each with the cells under `headings`. Empty rows are skipped.

    Reads the named sheet if the file has it, otherwise the first sheet with every heading.
    """
    (rows,) = read_sheets(data, file_name, [(sheet, headings)])
    return rows


def read_sheets(data: bytes, file_name: str, wanted: list[tuple[str | None, tuple[str, ...]]],
                by_name: bool = False) -> list[list[SourceRow]]:
    """Each sheet's rows, as read_sheet, for (sheet, headings) in `wanted`, from one opening of the file.

    With `by_name` (for an input that reads several sheets), each sheet must be there by its name, and
    each row says which sheet it's on.
    """
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix not in READS:
        raise UploadError([
            f"{file_name} isn't a kind of file that can be read here. Upload the file as it came: an "
            f"{' or '.join(READS.values())} ({', '.join(READS)})."
        ])
    sheets = {".csv": _csv_sheets, ".xls": _xls_sheets}.get(suffix, _xlsx_sheets)(data)
    names = [name for name, _ in sheets]
    found, problems = [], []
    for sheet, headings in wanted:
        if by_name and sheet not in names:
            problems.append(f"The workbook has no sheet called {sheet}. Its sheets are: {', '.join(names)}.")
            continue
        candidates = [s for s in sheets if s[0] == sheet] if sheet in names else sheets
        try:
            found.append(_read(candidates, headings, sheet if by_name else ""))
        except UploadError as e:
            problems.extend(e.problems)
    if problems:
        raise UploadError(problems)
    return found


def _read(sheets: list[tuple[str, Any]], headings: tuple[str, ...], label: str) -> list[SourceRow]:
    """The rows of the first of these sheets with every heading. `label` is the sheet's name for its rows, if any."""
    wanted = {heading_key(h): h for h in headings}
    missing: list[str] = []
    for _, cells_by_line in sheets:
        top = [heading_key(cell) for cell in next(iter(cells_by_line), ())]
        positions = {wanted[k]: i for i, k in reversed(list(enumerate(top))) if k in wanted}  # the first of two
        missing = [h for h in headings if h not in positions]
        if missing:
            continue
        rows = []
        for line, cells in enumerate(cells_by_line, start=2):
            values = {h: _clean(cells[i]) if i < len(cells) else None for h, i in positions.items()}
            if any(v is not None for v in values.values()):
                rows.append(SourceRow(line, values, sheet=label))
        return rows
    where = f"The sheet {label}'s row 1" if label else "Row 1" if len(sheets) == 1 else (
        "None of the sheets has every column it needs in row 1. On the first, row 1")
    raise UploadError([
        f"{where} is missing {'this column' if len(missing) == 1 else 'these columns'}: {', '.join(missing)}. "
        f"The columns it needs are: {', '.join(headings)}."
    ])


def _xlsx_sheets(data: bytes) -> list[tuple[str, Iterator[tuple]]]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # openpyxl raises many kinds of error for files it can't read
        raise UploadError(["This isn't an Excel workbook (.xlsx) that can be read. Upload the file as it came."]) from None
    sheets = []
    for worksheet in workbook.worksheets:
        worksheet.reset_dimensions()  # read every row, even if the file says it has fewer
        sheets.append((worksheet.title, worksheet.iter_rows(values_only=True)))
    return sheets


def _xls_sheets(data: bytes) -> list[tuple[str, Iterator[tuple]]]:
    try:
        workbook = xlrd.open_workbook(file_contents=data)
    except Exception:  # xlrd raises several kinds of error for files it can't read
        raise UploadError(["This isn't an older Excel workbook (.xls) that can be read. Upload the file as it came."]) from None
    return [(sheet.name, _xls_rows(sheet)) for sheet in workbook.sheets()]


def _xls_rows(sheet) -> Iterator[tuple]:
    return (tuple(sheet.row_values(r)) for r in range(sheet.nrows))


def _csv_sheets(data: bytes) -> list[tuple[str, Iterator[tuple]]]:
    for encoding in ("utf-8-sig", "cp1252"):  # Power BI read most as UTF-8, a few as Windows' own
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UploadError(["This CSV file's text can't be read. Upload the file as it came."])
    return [("", (tuple(row) for row in csv.reader(io.StringIO(text))))]


def _clean(value: Any) -> Any:
    """A cell's value, with spaces trimmed from text and empty text as None."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# --- Matching rows to catchments ----------------------------------------------------

def _match(conn, schema: Schema, heading: str, by_id: bool, one_row_each: bool, rows: list[SourceRow],
           notes: list[str], problems: list[str], area_heading: str | None = None) -> list[SourceRow]:
    """The rows for a catchment in the Catchments table, each with its ID. Notes say what was left out.

    With area_heading, a row only matches a catchment in the management catchment that column names (or one
    whose management catchment isn't known)."""
    catchments = schema.metadata.tables["catchments"]
    by_name: dict[str, list[tuple[str, str]]] = {}  # by its name, or with by_id, its ID
    areas: dict[str, str | None] = {}  # each catchment's management catchment
    for catchment_id, name, area in conn.execute(
        sa.select(catchments.c.id, catchments.c.name, catchments.c.management_catchment).order_by(catchments.c.name)
    ):
        by_name.setdefault(heading_key(catchment_id if by_id else name), []).append((catchment_id, name))
        areas[catchment_id] = area

    matched, left_out, elsewhere, first_line = [], [], [], {}
    for row in rows:
        name = row.cells.get(heading)
        if name is None:
            continue
        found = by_name.get(heading_key(name), [])
        if found and area_heading:
            here = [f for f in found if areas[f[0]] is None or heading_key(areas[f[0]]) == heading_key(row.cells.get(area_heading))]
            if not here:
                elsewhere.append(f"{name} ({row.cells.get(area_heading) or f'no {area_heading}'})")
                continue
            found = here
        if not found:
            left_out.append(str(name))
            continue
        if len(found) > 1:
            problems.append(
                f"{row.where}: {name} is the name of {len(found)} catchments ({', '.join(i for i, _ in found)}), "
                "so the row can't be matched to one."
            )
            continue
        row.catchment_id = found[0][0]
        if one_row_each and row.catchment_id in first_line:
            problems.append(
                f"Rows {first_line[row.catchment_id]} and {row.line} are both for {found[0][1]}"
                f"{f' ({row.catchment_id})' if by_id else ''}. Each can only appear once."
            )
            continue
        first_line.setdefault(row.catchment_id, row.line)
        matched.append(row)

    if left_out:
        notes.append(
            f"{_count(len(left_out), 'row')} {'isn' if len(left_out) == 1 else 'aren'}'t for a catchment in the Catchments "
            f"table, so {'it is' if len(left_out) == 1 else 'they are'} left out: {_listed(left_out)}."
        )
    if elsewhere:
        notes.append(
            f"{_count(len(elsewhere), 'row')} {'has' if len(elsewhere) == 1 else 'have'} the name of a catchment in the "
            f"Catchments table but {'is' if len(elsewhere) == 1 else 'are'} in another {area_heading}, so "
            f"{'it is' if len(elsewhere) == 1 else 'they are'} left out: {_listed(elsewhere)}."
        )
    without = [name for found in by_name.values() for catchment_id, name in found if catchment_id not in first_line]
    if without and matched:
        notes.append(f"The file has no row for {_count(len(without), 'catchment')} in the Catchments table: {_listed(without)}.")
    return matched


def _missing_values(table: sa.Table, rows: list[FileRow]) -> list[str]:
    """A required column the formulas left empty (a mistake in the input's code, so worth saying)."""
    required = [c.name for c in table.columns if not c.nullable]
    return [
        f"Row {row.line}: {table.name}.{name} would be empty, but needs a value."
        for row in rows for name in required if row.values.get(name) is None
    ]


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _listed(names: list[str]) -> str:
    shown = ", ".join(names[:NAMES_LISTED])
    return shown + (f" and {len(names) - NAMES_LISTED} more" if len(names) > NAMES_LISTED else "")


# --- Cells as numbers -------------------------------------------------------------------

def number(row: SourceRow, heading: str, problems: list[str], blank: float | None = None) -> float | None:
    """A cell as a number, or `blank` if it's empty."""
    value = row.cells.get(heading)
    if value is None:
        return blank
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.replace(",", ""))
            if math.isfinite(parsed):
                return parsed
        except ValueError:
            pass
    problems.append(f"{row.where}, {heading}: {value!r} isn't a number.")
    return blank


def count(row: SourceRow, heading: str, problems: list[str], blank: int | None = 0) -> tuple[int | None, str | None]:
    """A cell as a whole number, or (None, its text) if it's text instead, e.g. Less than 5."""
    value = row.cells.get(heading)
    if value is None:
        return blank, None
    if isinstance(value, str):
        try:
            value = float(value.replace(",", ""))
        except ValueError:
            return None, value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        return int(value), None
    problems.append(f"{row.where}, {heading}: {value!r} isn't a whole number.")
    return blank, None


def banded(value: float, bands: tuple[tuple[float, str], ...], otherwise: str) -> str:
    """The name of the first band the value is above, highest first, e.g. ((80, "High"), (30, "Medium"))."""
    return next((name for above, name in bands if value > above), otherwise)

