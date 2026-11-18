"""SAGIS phosphate: Phosphate Sources, and Phosphate Continuous and Diffuse.

The EA's SAGIS model estimates where each waterbody's phosphate comes from
(SAGIS Phosphate source.xlsx): on one sheet by source (Arable, Livestock, STW
(SWW) and so on), and on another split into Continuous (point) and Diffuse, as
the EA works it out (that includes phosphate from upstream, so adding up the
sources doesn't always give the same split). Each is a percentage at the end
of AMP7 (2025) and of AMP8 (2030). The original Power BI dashboard read both
sheets as they are: "Phosphate Source breakdown" and "Phosphate Point vs
Diffuse".

Here each of the two percentages becomes a row, with its year.
"""

from __future__ import annotations

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step, number

BREAKDOWN, SPLIT = "Phosphate Source breakdown", "Phosphate Point vs Diffuse"
TABLES = {BREAKDOWN: "phosphate_sources", SPLIT: "phosphate_point_diffuse"}
ID, SOURCE = "Waterbody ID", "Source"
YEARS = {2025: "% contribution at end of AMP7 (2025)", 2030: "% contribution at end of AMP8 (2030)"}
HEADINGS = (ID, SOURCE, *YEARS.values())


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    tables: dict[str, list[FileRow]] = {table: [] for table in TABLES.values()}
    seen: dict[tuple, int] = {}
    for row in rows:
        source = row.cells.get(SOURCE)
        if source is None:
            problems.append(f"{row.where}: {SOURCE} is empty.")
            continue
        key = (row.sheet, row.catchment_id, str(source).casefold())
        if key in seen:
            problems.append(f"{row.sheet}: rows {seen[key]} and {row.line} are both for {source} in the same waterbody.")
            continue
        seen[key] = row.line
        for year, heading in YEARS.items():
            percent = number(row, heading, problems)
            if percent is not None:  # a blank is no figure, so no row
                tables[TABLES[row.sheet]].append(FileRow(row.line, {
                    "catchment_id": row.catchment_id, "source": str(source), "year": year, "percent": percent,
                }))
    return tables


def _years() -> str:
    return " and ".join(f"{heading} as {year}" for year, heading in YEARS.items())


SAGIS_PHOSPHATE = Input(
    name="sagis_phosphate",
    title="SAGIS phosphate sources",
    provider="The EA's SAGIS phosphate modelling (the 2024 run), for each waterbody",
    file="SAGIS Phosphate source.xlsx",
    sheet=BREAKDOWN,
    headings=HEADINGS,
    more_sheets={SPLIT: HEADINGS},
    waterbody_heading=ID,
    by_id=True,
    one_row_each=False,
    query=f"{BREAKDOWN} and {SPLIT}",
    match=f"Relationships {BREAKDOWN}[Waterbody ID] and {SPLIT}[Waterbody ID] to Waterbody Lookup[WBID]",
    table_sheets={"phosphate_point_diffuse": SPLIT},
    steps={
        "phosphate_sources": (
            Step(("source",), (SOURCE,), "As it is, e.g. Arable, Livestock, STW (SWW).",
                 f"Power Query, {BREAKDOWN} (its two empty columns removed)"),
            Step(("year", "percent"), tuple(YEARS.values()), f"A row for each year: {_years()}. Blank: no row.",
                 f"The Scorecard's table of Source and the two percentages"),
        ),
        "phosphate_point_diffuse": (
            Step(("source",), (SOURCE,), "As it is: Continuous or Diffuse.", f"Power Query, {SPLIT}"),
            Step(("year", "percent"), tuple(YEARS.values()), f"A row for each year: {_years()}. Blank: no row.",
                 "The measures Phosphate % from treated sewage (2025) and (2030) read its Continuous row"),
        ),
    },
    work_out=work_out,
)
