"""Waterbody Lookup: Waterbody Figures, one row per waterbody.

The original Power BI dashboard's central table (Waterbody Lookup.xls), typed
up by the North Devon Biosphere: one row per waterbody, with its ranking, its
number of farms, its properties on public and private sewerage, its 2025
ecological class, and its river information (river length, river system, and
the rivers upstream and downstream, typed as names). They're all one row per
waterbody from the one file, so they're one table, with a figure the file
doesn't have left empty. The original worked out:

- in Power Query: the catchment's area in hectares, from its area in m², and
  the river's length in km, from metres
- in DAX: private sewerage per hectare, and its rating (calculated columns)

and coloured its map by the ecological class, which also gave 2025 in its "EA
Ecological Classification" card (2019 and 2022 came from the EA's
classifications, as they do here).
"""

from __future__ import annotations

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step, count, number

ID, AREA, RANKING, CLASS = "WBID", "Shape_Area", "Biosphere Ranking", "ecological_class"
FARMS, PUBLIC, PRIVATE = "FARMS", "SWW Sewerage", "Private Sewerage"
LENGTH, SYSTEM, UPSTREAM, DOWNSTREAM = "River Length (m)", "River System", "Upstream Rivers", "Downstream Rivers"
TABLE = "waterbody_figures"  # the one table it fills
CLASS_YEAR = 2025  # the year of its ecological class: the EA's cycle 4 classification
CLASSES = ("High", "Good", "Moderate", "Poor", "Bad")  # the ecological classes it can be (any case)
# Private sewerage rating, from private sewerage per hectare: the first it's below.
PRIVATE_RATING = ((0.1, "Very Low"), (0.15, "Low"), (0.3, "Medium"), (1.0, "High"))
HIGHEST_RATING = "Very High"


def private_rating(per_ha: float) -> str:
    return next((name for below, name in PRIVATE_RATING if per_ha < below), HIGHEST_RATING)


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    lookup = []
    for row in rows:
        ranking = _whole(row, RANKING, problems, notes)
        farms = _whole(row, FARMS, problems, notes)
        public = _whole(row, PUBLIC, problems, notes)
        private = _whole(row, PRIVATE, problems, notes)
        area_m2 = number(row, AREA, problems)
        area_ha = area_m2 / 10_000 if area_m2 else None  # Power Query: Catchment Area (ha)
        per_ha = private / area_ha if private is not None and area_ha else None  # DIVIDE(): blank if no area
        ecological_class = _ecological_class(row, problems)
        length_m = number(row, LENGTH, problems)
        lookup.append(FileRow(row.line, {
            "catchment_id": row.catchment_id,
            "ranking": ranking,
            "ecological_class_year": CLASS_YEAR if ecological_class else None,
            "ecological_class": ecological_class,
            "catchment_area_ha": area_ha,
            "river_length_km": length_m / 1000 if length_m is not None else None,  # Power Query: River Length (km)
            "river_system": _text(row.cells.get(SYSTEM)),
            "upstream_rivers": _text(row.cells.get(UPSTREAM)),
            "downstream_rivers": _text(row.cells.get(DOWNSTREAM)),
            "number_of_farms": farms,
            "public_sewerage_properties": public,
            "private_sewerage_properties": private,
            "private_sewerage_per_ha": per_ha,
            # No figure, no rating. (The original's DAX would say Very Low, as it counts a blank as 0, but
            # every waterbody has a figure.)
            "private_sewerage_rating": private_rating(per_ha) if per_ha is not None else None,
        }))
    return {TABLE: lookup}


def _ecological_class(row: SourceRow, problems: list[str]) -> str | None:
    """One of the EA's five, written as the dashboard's colours and counts expect (a typo would colour the map grey
    and count as a class of its own), or None if it's blank."""
    status = row.cells.get(CLASS)
    if status is None:
        return None
    known = {name.casefold(): name for name in CLASSES}.get(str(status).strip().casefold())
    if known is None:
        problems.append(f"{row.where}, {CLASS}: {status!r} isn't one of {', '.join(CLASSES[:-1])} or {CLASSES[-1]}.")
    return known


def _text(value) -> str | None:
    return str(value) if value is not None else None


def _whole(row: SourceRow, heading: str, problems: list[str], notes: list[str]) -> int | None:
    """A whole number, or None if it's blank. Text (e.g. N/A) is left empty too, with a note in the preview, so a
    waterbody doesn't lose its figure without anyone seeing why."""
    value, text = count(row, heading, problems, blank=None)
    if text is not None:
        notes.append(f"{row.where}, {heading}: {text!r} isn't a number, so it's left empty.")
    return value


# --- In words, for the admin page --------------------------------------------------------

def _rating_bands() -> str:
    return ", ".join(f"{name} below {below:g}" for below, name in PRIVATE_RATING) + f", otherwise {HIGHEST_RATING}"


STEPS = {
    TABLE: (
        Step(
            ("ranking",), (RANKING,),
            "As typed (it's worked out in the EA Standardised Scoring workbook). The dashboard shows it as e.g. "
            "Catchment Ranking: 68/92.",
            "Waterbody Lookup[Biosphere Ranking], shown by the measure Biosphere Ranking Display",
        ),
        Step(
            ("ecological_class_year",), (CLASS,),
            f"{CLASS_YEAR}, where it has an ecological class: the year of the lookup's classes (the EA's cycle 4 "
            "classification).",
            "The measure Waterbody Lookup[ClassECO2025]",
        ),
        Step(
            ("ecological_class",), (CLASS,),
            f"As typed. The EA's Catchment Data Explorer doesn't have {CLASS_YEAR} yet, so the maps, the class counts and "
            f"{CLASS_YEAR} in EA Ecological Classification use this (2019 and 2022 still come from EA Classifications).",
            "Waterbody Lookup[ecological_class]: the map's colours, and the measure ClassECO2025 in the EA Ecological "
            "Classification card",
        ),
        Step(
            ("catchment_area_ha",), (AREA,),
            f"{AREA} (in m²) ÷ 10,000.",
            "Power Query, Waterbody Lookup: step Added Custom (Catchment Area (ha))",
        ),
        Step(
            ("river_length_km",), (LENGTH,),
            f"{LENGTH} ÷ 1,000.",
            "Power Query, Waterbody Lookup: step Added Custom1 (River Length (km))",
        ),
        Step(
            ("river_system", "upstream_rivers", "downstream_rivers"), (SYSTEM, UPSTREAM, DOWNSTREAM),
            "As typed. The dashboard links each river name that's one of the location's catchments to its page.",
            "Waterbody Lookup[River System], [Upstream Rivers] and [Downstream Rivers], shown by the measure "
            "Waterbody Lookup[Value] in the River Info table",
        ),
        Step(
            ("number_of_farms",), (FARMS,),
            "As typed. Where it's blank, it's left empty, so no number is shown.",
            "Waterbody Lookup[FARMS], shown by the measure Number of Farms",
        ),
        Step(
            ("public_sewerage_properties", "private_sewerage_properties"), (PUBLIC, PRIVATE),
            "As typed.",
            "Waterbody Lookup[SWW Sewerage] and [Private Sewerage], shown by the measures SWW Sewerage HTML and Sewerage HTML",
        ),
        Step(
            ("private_sewerage_per_ha",), (PRIVATE, AREA),
            f"{PRIVATE} ÷ the catchment's area in hectares ({AREA}, in m², ÷ 10,000).",
            "Power Query, Waterbody Lookup: step Added Custom (Catchment Area (ha)); DAX column "
            "Waterbody Lookup[Private sewerage per ha]",
        ),
        Step(
            ("private_sewerage_rating",), ("private_sewerage_per_ha",),
            _rating_bands() + ". It's the Sewage (Private) tile in Risk Levels.",
            "DAX column Waterbody Lookup[Private sewerage rating], shown by the measure Private Sewerage Pressure",
        ),
    ),
}

WATERBODY_LOOKUP = Input(
    name="waterbody_lookup",
    title="Waterbody Lookup",
    provider="The North Devon Biosphere, who keep it up to date by hand",
    file="Waterbody Lookup.xls",
    sheet="Waterbody Lookup",
    headings=(ID, AREA, RANKING, CLASS, FARMS, PUBLIC, PRIVATE, LENGTH, SYSTEM, UPSTREAM, DOWNSTREAM),
    waterbody_heading=ID,
    by_id=True,
    query="Waterbody Lookup",
    match="Waterbody Lookup is the central table: the others join to its WBID or water_body_name",
    steps=STEPS,
    work_out=work_out,
)
