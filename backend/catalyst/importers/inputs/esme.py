"""ESME: the Runoff, Modification, Invasive Species, Overheating and Running Dry risk levels.

The Ecosystem Service Map Explorer (ESME), from Defra's Natural Capital and
Ecosystem Assessment programme and the EA, scores every river waterbody on
indicators of what its river and land can do (exported as
ESME_River_water_bodies_Phase_4_-8564305916099105313.csv). The original Power
BI dashboard read five of them, and turned each into a risk level with a DAX
measure, for five of its Risk Levels tiles. A score of 1 to 5 is better the
higher it is, so 5 is the lowest risk.

DAX compares text ignoring case ("Shaded" is "shaded"), so this does too.
"""

from __future__ import annotations

from dataclasses import dataclass

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step, count

SCORE_LEVELS = {5: "Very Low", 4: "Low", 3: "Medium", 2: "High", 1: "Very High"}
QUERY = "ESME_River_water_bodies_Phase_4_-8564305916099105313"  # the original's query (table) for it


@dataclass(frozen=True)
class Indicator:
    column: str  # ESME's column
    name: str  # ESME's name for it
    value: str  # the table's column for ESME's value
    level: str  # ...and for the risk level: the Risk Levels tile
    tile: str  # the tile's name on the dashboard
    measure: str  # the original's DAX measure
    levels: dict | None = None  # a category -> its level (by its text, ignoring case); None for a 1-5 score


INDICATORS = (
    Indicator("aa_r1", "R1 River Habitat Quality Index", "habitat_quality", "modification", "Modification", "Modification"),
    Indicator("wf_r24", "R24 Runoff and Infiltration", "runoff_and_infiltration", "runoff", "Runoff", "Runoff"),
    Indicator("ws_r27", "R27 Abstraction sustainability", "abstraction_sustainability", "running_dry", "Running Dry",
              "Running Dry"),
    Indicator("iv_r17", "R17 Invasive non-native species", "invasive_species_found", "invasive_species",
              "Invasive Species", "Invasive Species", {"No": "Low", "One species": "High"}),
    Indicator("wq_r10", "R10 River shade", "river_shade", "overheating", "Overheating", "Overheating",
              {"No shade": "High", "Medium shade": "Medium", "Shaded": "Low"}),
)


def level(indicator: Indicator, value) -> str | None:
    """The risk level for ESME's value, or None if the original's formula doesn't know it (it shows a blank tile)."""
    if indicator.levels is None:
        return SCORE_LEVELS.get(value)
    known = {text.casefold(): name for text, name in indicator.levels.items()}
    return known.get(str(value).casefold()) if value is not None else None


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    risks, unknown = [], {}  # ESME's column -> the values the original's formula doesn't know
    for row in rows:
        values = {"catchment_id": row.catchment_id}
        for indicator in INDICATORS:
            if indicator.levels is None:
                value, text = count(row, indicator.column, problems, blank=None)
                if text is not None:
                    problems.append(f"Row {row.line}, {indicator.column}: {text!r} isn't a score from 1 to 5.")
            else:
                value = row.cells.get(indicator.column)
                value = str(value) if value is not None else None
            values[indicator.value] = value
            values[indicator.level] = level(indicator, value)
            if value is not None and values[indicator.level] is None:
                unknown.setdefault(indicator.column, set()).add(str(value))
        risks.append(FileRow(row.line, values))
    for indicator in INDICATORS:
        values = unknown.get(indicator.column)
        if not values:
            continue
        notes.append(
            f"{indicator.column} ({indicator.name}) has {', '.join(sorted(values))}, which the original's formula doesn't "
            f"know, so the {indicator.tile} tile is left empty there."
        )
    return {"esme_risk_levels": risks}


# --- In words, for the admin page --------------------------------------------------------

def _step(indicator: Indicator) -> Step:
    if indicator.levels is None:
        bands = ", ".join(f"{score} {name}" for score, name in SCORE_LEVELS.items())
        text = f"{indicator.value} is {indicator.name}, a score from 1 to 5, as it is. {indicator.level}: {bands}."
    else:
        bands = ", ".join(f"{value} is {name}" for value, name in indicator.levels.items())
        text = f"{indicator.value} is {indicator.name}, as it is. {indicator.level}: {bands}; anything else leaves it empty."
    return Step((indicator.value, indicator.level), (indicator.column,), text, f"DAX measure {QUERY}[{indicator.measure}]")


ESME = Input(
    name="esme",
    title="ESME river waterbodies",
    provider="The Ecosystem Service Map Explorer (ESME: Defra's Natural Capital and Ecosystem Assessment, with the EA), "
             "exported for the river waterbodies",
    file=QUERY + ".csv",
    sheet=None,
    headings=("WB_ID", *(indicator.column for indicator in INDICATORS)),
    waterbody_heading="WB_ID",
    by_id=True,
    query=QUERY,
    match=f"Relationship {QUERY}[WB_ID] to Waterbody Lookup[WBID]",
    steps={"esme_risk_levels": tuple(_step(indicator) for indicator in INDICATORS)},
    work_out=work_out,
    url="https://experience.arcgis.com/experience/70114cd2e0464dfcb9b1426af826893d/page/Homepage",
)
