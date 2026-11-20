"""Natural England's habitats: Habitat & Land Use.

Each waterbody's area of each simplified habitat type (Farmland, Not Farmed,
Urban, Wetland, Woodland), from Natural England's habitat map, added up in GIS
(Nat Eng Simplified Habitat.csv, a row per waterbody per habitat). The original
Power BI dashboard read it as the "Nat Eng Simplified Habitat" query and worked
out:

- in Power Query: each area in hectares, from m²
- in DAX: each habitat's share of the waterbody (its area over all the
  waterbody's habitat areas, not the catchment's own area), and its relative
  coverage, Low, Medium or High, with bands for each habitat (measures)
"""

from __future__ import annotations

from catalyst.importers.excel import FileRow

from .common import Example, Input, SourceRow, Step, figure, number

NAME, HABITAT, AREA = "water_body_name", "Simplified_Habitat_Type", "SUM_SHAPE_Area"
# Relative coverage, from a habitat's share of the waterbody: (High at or above, Medium at or above). DAX compares
# the names ignoring case.
COVERAGE = {
    "Farmland": (0.60, 0.40),
    "Not Farmed": (0.40, 0.08),
    "Urban": (0.06, 0.03),
    "Wetland": (0.20, 0.05),
    "Woodland": (0.20, 0.10),
}


def coverage(habitat: str, share: float) -> str | None:
    """Low, Medium or High for the habitat's share (0 to 1); None for a habitat the original's formula doesn't know."""
    bands = {name.casefold(): limits for name, limits in COVERAGE.items()}.get(habitat.casefold())
    if bands is None:
        return None
    high, medium = bands
    return "High" if share >= high else "Medium" if share >= medium else "Low"


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    # Catchment -> habitat -> [area in ha, the file's row]. A habitat twice in a waterbody is added up, as the
    # original's table would.
    areas: dict[str, dict[str, list]] = {}
    for row in rows:
        habitat = row.cells.get(HABITAT)
        if habitat is None:
            problems.append(f"Row {row.line}: {HABITAT} is empty.")
            continue
        area_m2 = number(row, AREA, problems, blank=0.0)
        found = areas.setdefault(row.catchment_id, {}).setdefault(str(habitat), [0.0, row.line])
        found[0] += area_m2 / 10_000  # Power Query: Area (ha)
    unknown = set()
    habitats = []
    for catchment_id, by_habitat in areas.items():
        total = sum(area for area, _ in by_habitat.values())  # DAX: Catchment Total Area (ha)
        for habitat, (area, line) in by_habitat.items():
            share = area / total if total else None  # DAX: Habitat % of Catchment
            level = coverage(habitat, share) if share is not None else None
            if level is None and share is not None:
                unknown.add(habitat)
            habitats.append(FileRow(line, {
                "catchment_id": catchment_id,
                "habitat": habitat,
                "area_ha": area,
                "percent_of_catchment": 100 * share if share is not None else None,
                "relative_coverage": level,
            }))
    if unknown:
        notes.append(
            f"{', '.join(sorted(unknown))} {'isn' if len(unknown) == 1 else 'aren'}'t a habitat the original's formula "
            "gives a relative coverage for, so it's left empty."
        )
    return {"habitat_land_use": habitats}


def _share_example(ex: Example) -> str | None:
    """e.g. Farmland: 1,234.5 ha ÷ 2,706.1 ha (all 5: 1,234.5 + …) × 100 = 45.62%."""
    if not ex.out or ex.out[0]["percent_of_catchment"] is None:
        return None
    first, areas = ex.out[0], [row["area_ha"] for row in ex.out]
    return (f"{first['habitat']}: {figure(first['area_ha'])} ha ÷ {figure(sum(areas))} ha (all {len(areas)}: "
            f"{' + '.join(figure(a) for a in areas)}) × 100 = {figure(first['percent_of_catchment'])}%")


def _bands() -> str:
    return "; ".join(f"{name} High at {high:.0%} or more, Medium at {medium:.0%}" for name, (high, medium) in COVERAGE.items())


HABITAT_FILE = Input(
    name="habitat",
    title="Natural England habitats",
    provider="Natural England's habitat map (22/23), simplified to five habitat types and added up for each "
             "waterbody in GIS",
    file="Nat Eng Simplified Habitat.csv",
    sheet=None,
    headings=(NAME, HABITAT, AREA),
    waterbody_heading=NAME,
    one_row_each=False,
    query="Nat Eng Simplified Habitat",
    match="Relationship Nat Eng Simplified Habitat[water_body_name] to Waterbody Lookup[water_body_name]",
    steps={"habitat_land_use": (
        Step(
            ("habitat",), (HABITAT,),
            "A row for each habitat: Farmland, Not Farmed, Urban, Wetland or Woodland. One there twice in a waterbody is "
            "added up.",
            "Nat Eng Simplified Habitat[Simplified_Habitat_Type]",
        ),
        Step(
            ("area_ha",), (AREA,),
            f"{AREA} (in m²) ÷ 10,000.",
            "Power Query, Nat Eng Simplified Habitat: step Added Custom (Area (ha))",
        ),
        Step(
            ("percent_of_catchment",), ("area_ha",),
            "The habitat's area ÷ all the waterbody's habitat areas added up (not the catchment's own area, so the five "
            "add up to 100%), as a %.",
            "DAX measures Nat Eng Simplified Habitat[Habitat % of Catchment] and [Catchment Total Area (ha)]",
            _share_example,
        ),
        Step(
            ("relative_coverage",), ("habitat", "percent_of_catchment"),
            _bands() + "; otherwise Low.",
            "DAX measure Nat Eng Simplified Habitat[Relative Coverage]",
        ),
    )},
    work_out=work_out,
)
