"""APHA's livestock data: Livestock and Livestock Pressure.

The Animal and Plant Health Agency (APHA) sends, on request, the number of
each kind of livestock in each waterbody and its density per square kilometre
(e.g. APHA Livestock Data Feb 2026.xlsx). The original Power BI dashboard read
it as the "APHA Livestock Data" query and worked out:

- in Power Query: blank densities as 0, the nitrogen and phosphate loads from
  the densities, and the livestock pressure from their total
- in DAX: each kind of livestock's density rating (calculated columns), and
  the numbers shown, 0 where blank (the LivestockType[Total Number] measure)

The numbers and bands below are the original's. The admin page shows them, in
words made from these same numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from catalyst.importers.excel import FileRow

from .common import Input, SourceRow, Step, banded, count, number

NAME = "Catchment Name"


@dataclass(frozen=True)
class Animal:
    name: str  # as on the dashboard (the original's LivestockType table)
    number: str  # APHA's column: how many
    density: str  # APHA's column: how many per km²
    nitrogen: float  # kg of nitrogen a year, per one per km²
    phosphate: float  # kg of phosphate a year, per one per km²
    medium: float  # density rating: Medium above this
    high: float  # ...and High above this
    rating_column: str  # the original's DAX column for its density rating


# In the order of the original's formulas for the loads.
ANIMALS = (
    Animal("Beef cattle", "Beef Population", "Beef Density Per SqKm", 70, 13, 30, 80, "Beef Density Rating"),
    Animal("Dairy cattle", "Dairy Population", "Dairy Density Per SqKm", 110, 23, 40, 100, "Dairy Density Rating"),
    Animal("Pigs", "Total Pig Numbers", "Pig Density Per SqKm", 20, 5, 30, 100, "Pig Density Rating"),
    Animal("Sheep", "Total Sheep Numbers", "Sheep Density Per SqKm", 13, 3, 100, 300, "Sheep Density Rating"),
    Animal("Poultry", "Total Poultry Numbers", "Poultry Per SqKm", 0.6, 0.3, 1000, 5000, "Poultry Density Rating"),
)
# Livestock pressure, from the nitrogen and phosphate load (kg a year per km²): the first it's above.
PRESSURE = ((40000, "Very High"), (20000, "High"), (10000, "Medium"), (5000, "Low"))
LOWEST_PRESSURE = "Very Low"


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    livestock, pressure = [], []
    for row in rows:
        densities = {}
        for animal in ANIMALS:
            how_many, note = count(row, animal.number, problems)
            density = number(row, animal.density, problems, blank=0.0)
            densities[animal.name] = density
            livestock.append(FileRow(row.line, {
                "catchment_id": row.catchment_id,
                "livestock": animal.name,
                "number": how_many,
                "number_note": note,
                "density": density,
                "density_rating": banded(density, ((animal.high, "High"), (animal.medium, "Medium")), "Low"),
            }))
        nitrogen = phosphate = 0.0
        for animal in ANIMALS:  # added up in the original's order, so the result is the same to the last digit
            nitrogen += densities[animal.name] * animal.nitrogen
            phosphate += densities[animal.name] * animal.phosphate
        total = nitrogen + phosphate
        pressure.append(FileRow(row.line, {
            "catchment_id": row.catchment_id,
            "nitrogen_load": nitrogen,
            "phosphate_load": phosphate,
            "nitrogen_and_phosphate_load": total,
            "pressure": banded(total, PRESSURE, LOWEST_PRESSURE),
        }))
    return {"livestock": livestock, "livestock_pressure": pressure}


# --- In words, for the admin page --------------------------------------------------------

def _n(value: float) -> str:
    return f"{value:,g}"


def _sum(weight: str) -> str:
    return " + ".join(f"{a.name.lower()} × {_n(getattr(a, weight))}" for a in ANIMALS)


def _bands(bands, lowest: str) -> str:
    return ", ".join(f"{name} above {_n(above)}" for above, name in bands) + f", otherwise {lowest}"


NUMBERS = tuple(a.number for a in ANIMALS)
DENSITIES = tuple(a.density for a in ANIMALS)
STEPS = {
    "livestock": (
        Step(
            ("livestock",), (),
            "A row for each kind of livestock: " + ", ".join(a.name for a in ANIMALS) + ".",
            "DAX table LivestockType",
        ),
        Step(
            ("number", "number_note"), NUMBERS,
            "Each kind's number as APHA gives it, and 0 where it's blank. Where APHA gives a range instead, such as "
            "Less than 5, number is left empty and the range goes in number_note.",
            "DAX measure LivestockType[Total Number]",
        ),
        Step(
            ("density",), DENSITIES,
            "Each kind's number per km² as APHA gives it, and 0 where it's blank.",
            "Power Query, APHA Livestock Data: step Custom1 (blanks replaced by 0)",
        ),
        Step(
            ("density_rating",), ("density",),
            "; ".join(f"{a.name}: High above {_n(a.high)}, Medium above {_n(a.medium)}" for a in ANIMALS) + "; otherwise Low.",
            "DAX columns APHA Livestock Data[" + "], [".join(a.rating_column for a in ANIMALS) + "]",
        ),
    ),
    "livestock_pressure": (
        Step(
            ("nitrogen_load",), DENSITIES,
            "Kg a year per km² = " + _sum("nitrogen") + " (each the density, blank as 0).",
            "Power Query, APHA Livestock Data: step Added Custom (Nitrogen Load kg per yr per sqKm)",
        ),
        Step(
            ("phosphate_load",), DENSITIES,
            "Kg a year per km² = " + _sum("phosphate") + ".",
            "Power Query, APHA Livestock Data: step Added Custom1 (Phosphate Load kg per yr per sqKm)",
        ),
        Step(
            ("nitrogen_and_phosphate_load",), ("nitrogen_load", "phosphate_load"),
            "The two added up.",
            "Power Query, APHA Livestock Data: step Added Custom2 (N + P Load)",
        ),
        Step(
            ("pressure",), ("nitrogen_and_phosphate_load",),
            _bands(PRESSURE, LOWEST_PRESSURE) + ". It's the Livestock tile in Risk Levels.",
            "Power Query, APHA Livestock Data: step Added Custom3 (Livestock Pressure column)",
        ),
    ),
}

APHA_LIVESTOCK = Input(
    name="apha_livestock",
    title="APHA livestock data",
    provider="The Animal and Plant Health Agency (APHA), sent on request",
    file="APHA Livestock Data Feb 2026.xlsx",
    sheet="Appendix 1 EIR2026_00630",
    headings=(NAME, *(heading for a in ANIMALS for heading in (a.number, a.density))),
    waterbody_heading=NAME,
    query="APHA Livestock Data",
    match="Relationship Waterbody Lookup[water_body_name] to APHA Livestock Data[Catchment Name]",
    steps=STEPS,
    work_out=work_out,
)
