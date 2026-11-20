"""A worked example of each table's transformation, for the admin page.

Each table's Transformation panel shows real data going through it: a few rows
coming in (as they are in the file), each step done to one waterbody's, and
the same rows going out (as they are in the table).

A source file's and an Excel table's are made from the file when it's
uploaded, and kept with its upload (the uploads table's `examples` column), so
the page shows its last approved file's. The waterbody is the one with the
most figures, in every table the file fills. A step shows its inputs' values,
then its columns', unless its input's code says it in words (Step.example), as
when it's an average of many rows.

They're kept by each step's words, so if a formula's words change, the page
makes them again from the file (`make`). A downloaded table's example is
written in diagram.yaml instead (diagram.py), as its download isn't kept here.
"""

from __future__ import annotations

import datetime
import decimal
import math
from typing import Any

import sqlalchemy as sa

from catalyst.db import Schema
from catalyst.importers import excel, inputs
from catalyst.importers.excel import FileRow

ROWS = 3  # rows shown, where a table has that many
MOST = 5  # and at most this many: e.g. one waterbody's five kinds of livestock
LONGEST = 300  # characters of text kept


def make(conn: sa.Connection, schema: Schema, uploaded_to: str, data: bytes, file_name: str) -> dict[str, dict]:
    """Each table's example from a file uploaded to a source file or a table. Raises UploadError if it can't be read."""
    if uploaded_to in inputs.INPUTS:
        source = inputs.INPUTS[uploaded_to]
        return for_input(conn, schema, source, source.run(conn, schema, data, file_name))
    table = schema.metadata.tables[uploaded_to]
    return for_excel(table, excel.read_upload(table, data))


def for_input(conn: sa.Connection, schema: Schema, source: inputs.Input, result: inputs.Result) -> dict[str, dict]:
    """Each of a source file's tables' example, all following the same waterbody."""
    by_catchment: dict[str, dict[str, list[FileRow]]] = {}  # catchment -> table -> its rows
    for name, rows in result.tables.items():
        for row in rows:
            by_catchment.setdefault(row.values["catchment_id"], {}).setdefault(name, []).append(row)
    if not by_catchment:
        return {}
    first_line, file_rows = {}, {}
    for row in result.rows:
        first_line.setdefault(row.catchment_id, row.line)
        file_rows[row.catchment_id] = file_rows.get(row.catchment_id, 0) + 1
    # The waterbody in the most tables, with the most rows in the file (so an average is of several), then the
    # most figures, and the first in the file if several have as many.
    example = max(by_catchment, key=lambda c: (
        len(by_catchment[c]), file_rows.get(c, 0),
        sum(_filled(r.values) for rows in by_catchment[c].values() for r in rows), -first_line.get(c, 0),
    ))
    catchments = schema.metadata.tables["catchments"]
    name = conn.scalar(sa.select(catchments.c.name).where(catchments.c.id == example)) or example
    tables = {table: [r.values for r in rows] for table, rows in by_catchment[example].items()}
    return {
        table: _input_table(source, table, rows, result.rows, example, name, tables)
        for table, rows in result.tables.items()
    }


def _input_table(source: inputs.Input, table: str, out: list[FileRow], file_rows: list[inputs.SourceRow],
                 example: str, name: str, tables: dict[str, list[dict]]) -> dict:
    sheet = source.table_sheet(table)
    on_sheet = [r for r in file_rows if not r.sheet or r.sheet == sheet]
    mine = [r for r in out if r.values["catchment_id"] == example]
    shown = mine[:MOST] + [r for r in out if r.values["catchment_id"] != example][:max(0, ROWS - len(mine))]
    by_line = {r.line: r for r in on_sheet}
    came_from = [by_line[line] for line in dict.fromkeys(r.line for r in shown) if line in by_line]
    headings = source.file_columns(table)
    columns = list(out[0].values) if out else []

    own = inputs.Example([r for r in on_sheet if r.catchment_id == example], [r.values for r in mine], tables)
    first = mine[0] if mine else None
    first_in = by_line.get(first.line) if first else None
    steps = {}
    for step in source.table_steps(table):
        if step.example is not None:
            steps[step.text] = step.example(own)
        elif first is not None:
            steps[step.text] = _step(step, first.values, first_in)
        else:
            steps[step.text] = None
    return {
        "waterbody": name,
        "in": {
            "columns": headings,
            "rows": [[plain(r.cells.get(h)) for h in headings] for r in came_from],
            "example": [i for i, r in enumerate(came_from) if r.catchment_id == example],
            "total": len(on_sheet),
        },
        "out": {
            "columns": columns,
            "rows": [[plain(r.values.get(c)) for c in columns] for r in shown],
            "example": [i for i, r in enumerate(shown) if r.values["catchment_id"] == example],
            "total": len(out),
        },
        "steps": steps,
    }


def _step(step: inputs.Step, values: dict[str, Any], came_from: inputs.SourceRow | None) -> dict | None:
    """A step done to one row: its inputs' values (the table's own columns, or the file's), then its columns'."""
    used = []
    for name in step.inputs:
        if name in values:
            used.append([name, plain(values[name]), True])  # one of the table's own columns
        elif came_from is not None and name in came_from.cells:
            used.append([name, plain(came_from.cells[name]), False])
    made = [[column, plain(values.get(column))] for column in step.columns]
    return {"in": used, "out": made}


def for_excel(table: sa.Table, rows: list[FileRow]) -> dict[str, dict]:
    """An Excel table's example: its first few rows, which go into the table as they are (so they're kept once, as
    `in`, and go `out` the same)."""
    columns = [c.name for c in table.columns if c.name in (rows[0].values if rows else {})]
    shown = {"columns": columns, "rows": [[plain(r.values.get(c)) for c in columns] for r in rows[:ROWS]],
             "example": [], "total": len(rows)}
    return {table.name: {"waterbody": None, "in": shown, "steps": {}}}


def shown(example: dict, steps: list[inputs.Step] | None) -> dict:
    """An example as the page shows it: what goes out (an Excel table's is what comes in), and each step's, in the
    order of the steps (None where there isn't one)."""
    kept = example.get("steps") or {}
    return {**example, "out": example.get("out") or example.get("in"), "steps": [kept.get(step.text) for step in steps or []]}


def out_of_date(example: dict | None, steps: list[inputs.Step]) -> bool:
    """Whether the example was made before the steps' words were as they are now (or before examples were kept)."""
    return example is None or any(step.text not in (example.get("steps") or {}) for step in steps)


def _filled(values: dict[str, Any]) -> int:
    """How many of a row's values are figures: not empty, and not 0."""
    return sum(1 for v in values.values() if v not in (None, "", 0, 0.0))


def plain(value: Any) -> Any:
    """A value as it's kept: text, a number, Yes / No or empty."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    text = str(value)
    return text if len(text) <= LONGEST else text[:LONGEST - 1] + "…"
