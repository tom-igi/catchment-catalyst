"""Water UK's storm overflow plans: Sewerage Improvements.

Water UK's national storm overflows plan (National Plan Data - updated.xlsx,
from water.org.uk/overflows-plan): a row per storm overflow in England, with
the water company's planned improvements, the year they're due and the spills
a year expected afterwards. The original Power BI dashboard read it as the
"Water Company Asset Plans" query, matched it to waterbodies by name, and
showed each site's improvements list, predicted spills and year. Waterbody
names repeat across England, so here a row must also be in the waterbody's
management catchment.

In this file two headings are the wrong way round: "Spill improvements
planned?" holds the delivery year, and "Rainfall Improvement Target Delivery
Year" holds Y or blank. The original showed the first (as the year), and so
does this; if a later file puts the year under the right heading, that's used.

The original's table added up rows with the same site and improvements list,
so two overflows at one works showed as one row with their years added
together. Here each overflow keeps its own row, and where a site has several
in a waterbody, each is named with Water UK's ID, e.g. OKEHAMPTON STW (SWW0562).
"""

from __future__ import annotations

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step, count

SHEET = "Water Company Asset Plans"
ID, SITE, WATER_BODY, AREA = "Unique ID", "EA site name", "Water Body", "Management Catchment"
IMPROVEMENTS = "Improvements List"
PLANNED, DELIVERY = "Spill improvements planned?", "Rainfall Improvement Target Delivery Year"
SPILLS = "Predicted average annual spill frequency following scheme implementation where applicable"


def year(row: SourceRow) -> int | None:
    """The year the work is due: from the delivery year's column if it holds a year, otherwise (as in this file,
    whose headings are swapped) from the column headed Spill improvements planned?. None if neither does."""
    for heading in (DELIVERY, PLANNED):
        value, _ = count(row, heading, [], blank=None)  # Y, N or text isn't a year: no problem, just not this column
        if value is not None and 2000 <= value <= 2100:
            return value
    return None


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    by_site: dict[tuple[str, str], list[SourceRow]] = {}
    for row in rows:
        site = row.cells.get(SITE) or row.cells.get(ID)
        if site is None:
            problems.append(f"{row.where}: has no {SITE} or {ID}.")
            continue
        by_site.setdefault((row.catchment_id, str(site)), []).append(row)
    improvements, names = [], {}
    for (catchment_id, site), site_rows in by_site.items():
        for row in site_rows:
            name = site if len(site_rows) == 1 else f"{site} ({row.cells.get(ID) or row.line})"
            if (catchment_id, name) in names:
                problems.append(f"Rows {names[catchment_id, name]} and {row.line} are both for {name}.")
                continue
            names[catchment_id, name] = row.line
            spills, _ = count(row, SPILLS, problems, blank=None)
            text = row.cells.get(IMPROVEMENTS)
            improvements.append(FileRow(row.line, {
                "catchment_id": catchment_id,
                "site_name": name,
                "improvements": str(text) if text is not None else None,
                "completion_year": year(row),
                "predicted_spills_per_year": spills,
            }))
    return {"sewerage_improvements": improvements}


WATER_COMPANY_PLANS = Input(
    name="water_company_plans",
    title="Water UK storm overflow plans",
    provider="Water UK's national storm overflows plan, a row per storm overflow in England",
    file="National Plan Data - updated.xlsx",
    sheet=SHEET,
    headings=(WATER_BODY, AREA, ID, SITE, IMPROVEMENTS, PLANNED, DELIVERY, SPILLS),
    waterbody_heading=WATER_BODY,
    area_heading=AREA,
    one_row_each=False,
    query=SHEET,
    match=f"Relationship {SHEET}[Water Body] to Waterbody Lookup[water_body_name]",
    url="https://www.water.org.uk/overflows-plan",
    steps={"sewerage_improvements": (
        Step(
            ("site_name",), (SITE, ID),
            f"{SITE}. Where a site has several overflows into one waterbody, each keeps its own row, named with its {ID}, "
            "e.g. OKEHAMPTON STW (SWW0562).",
            f"The Scorecard's table of {SHEET}: EA site name and Improvements List",
        ),
        Step(("improvements",), (IMPROVEMENTS,), "As it is.", f"{SHEET}[Improvements List]"),
        Step(
            ("completion_year",), (PLANNED, DELIVERY),
            f"The column headed {PLANNED}, which in this file holds the year (its heading and {DELIVERY}'s are the "
            f"wrong way round). If {DELIVERY} holds a year, that's used instead.",
            f"Sum({SHEET}[Spill improvements planned?]) in the Scorecard's table",
        ),
        Step(
            ("predicted_spills_per_year",), (SPILLS,), "As it is.",
            f"Sum({SHEET}[Predicted average annual spill frequency …]) in the Scorecard's table",
        ),
    )},
    work_out=work_out,
)
