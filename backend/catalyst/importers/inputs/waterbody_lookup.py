"""Waterbody Lookup: Catchment Ranking, Farms, Sewerage Properties, Ecological Classes and River Information.

The original Power BI dashboard's central table (Waterbody Lookup.xls), typed
up by the North Devon Biosphere: one row per waterbody, with its ranking, its
number of farms, its properties on public and private sewerage, its 2025
ecological class, and its river information (river length, river system, and
the rivers upstream and downstream, typed as names). The original worked out:

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
CLASS_YEAR = 2025  # the year of its ecological class: the EA's cycle 4 classification
# Private sewerage rating, from private sewerage per hectare: the first it's below.
PRIVATE_RATING = ((0.1, "Very Low"), (0.15, "Low"), (0.3, "Medium"), (1.0, "High"))
HIGHEST_RATING = "Very High"


def private_rating(per_ha: float) -> str:
    return next((name for below, name in PRIVATE_RATING if per_ha < below), HIGHEST_RATING)


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    rankings, farms, properties, classes, rivers = [], [], [], [], []
    for row in rows:
        catchment = {"catchment_id": row.catchment_id}
        ranking, _ = count(row, RANKING, problems, blank=None)
        if ranking is not None:
            rankings.append(FileRow(row.line, {**catchment, "ranking": ranking}))
        how_many, _ = count(row, FARMS, problems, blank=None)
        if how_many is not None:
            farms.append(FileRow(row.line, {**catchment, "number_of_farms": how_many}))

        public, _ = count(row, PUBLIC, problems, blank=None)
        private, _ = count(row, PRIVATE, problems, blank=None)
        area_m2 = number(row, AREA, problems)
        area_ha = area_m2 / 10_000 if area_m2 else None  # Power Query: Catchment Area (ha)
        per_ha = private / area_ha if private is not None and area_ha else None  # DIVIDE(): blank if no area
        properties.append(FileRow(row.line, {
            **catchment,
            "public_sewerage_properties": public,
            "private_sewerage_properties": private,
            "private_sewerage_per_ha": per_ha,
            # No figure, no rating. (The original's DAX would say Very Low, as it counts a blank as 0, but
            # every waterbody has a figure.)
            "private_sewerage_rating": private_rating(per_ha) if per_ha is not None else None,
        }))

        status = row.cells.get(CLASS)
        if status is not None:
            classes.append(FileRow(row.line, {**catchment, "year": CLASS_YEAR, "ecological_class": str(status)}))

        length_m = number(row, LENGTH, problems)
        rivers.append(FileRow(row.line, {
            **catchment,
            "catchment_area_ha": area_ha,
            "river_length_km": length_m / 1000 if length_m is not None else None,  # Power Query: River Length (km)
            "river_system": _text(row.cells.get(SYSTEM)),
            "upstream_rivers": _text(row.cells.get(UPSTREAM)),
            "downstream_rivers": _text(row.cells.get(DOWNSTREAM)),
        }))
    return {
        "catchment_rankings": rankings,
        "farms": farms,
        "sewerage_properties": properties,
        "ecological_classes": classes,
        "river_information": rivers,
    }


def _text(value) -> str | None:
    return str(value) if value is not None else None


# --- In words, for the admin page --------------------------------------------------------

def _rating_bands() -> str:
    return ", ".join(f"{name} below {below:g}" for below, name in PRIVATE_RATING) + f", otherwise {HIGHEST_RATING}"


STEPS = {
    "catchment_rankings": (
        Step(
            ("ranking",), (RANKING,),
            "As typed. (It's worked out outside the Power BI, in the EA Standardised Scoring workbook.) The dashboard "
            "shows it as e.g. Catchment Ranking: 68/92.",
            "Waterbody Lookup[Biosphere Ranking], shown by the measure Biosphere Ranking Display",
        ),
    ),
    "farms": (
        Step(
            ("number_of_farms",), (FARMS,),
            "As typed. Where it's blank, the catchment has no row, so no number is shown.",
            "Waterbody Lookup[FARMS], shown by the measure Number of Farms",
        ),
    ),
    "sewerage_properties": (
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
    "ecological_classes": (
        Step(
            ("year",), (),
            f"{CLASS_YEAR}: the year of the lookup's class (the EA's cycle 4 classification).",
            "The measure Waterbody Lookup[ClassECO2025]",
        ),
        Step(
            ("ecological_class",), (CLASS,),
            f"As typed. The EA's Catchment Data Explorer doesn't have {CLASS_YEAR} yet, so the maps, the class counts and "
            f"{CLASS_YEAR} in EA Ecological Classification use this (2019 and 2022 still come from EA Classifications).",
            "Waterbody Lookup[ecological_class]: the map's colours, and the measure ClassECO2025 in the EA Ecological "
            "Classification card",
        ),
    ),
    "river_information": (
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
