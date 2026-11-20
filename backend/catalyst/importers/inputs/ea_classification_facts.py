"""The EA's classification facts: EA Scores and EA Thresholds.

The EA's classification facts for every waterbody (North Devon WB
Classification Facts Data.xlsx, "Classification Data" sheet): a row per fact
per monitoring site per year, such as a site's fish EQR, its phosphate
reading, or the waterbody's Good/Moderate boundary for phosphate. The original
Power BI dashboard read it as the "EA Classification Data" query and worked
out, for its EA Data page, with DAX measures:

- each measure's value for each year: the average of the sites' EQRs for
  biology (fish, invertebrates, macrophytes, phytobenthos), and the median of
  the readings for physico-chemistry (ammonia, dissolved oxygen, phosphate,
  temperature, pH)
- each measure's thresholds: fixed for biology; for physico-chemistry, the
  waterbody's boundaries in the latest year that has them
- each value's colour, from its thresholds (here, its status)

Values are rounded as the dashboard shows them (halves up, as Excel and Power
BI do): 3 decimal places, or 2 for dissolved oxygen, temperature and pH. Each
status is worked out before rounding.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from catalyst.importers.excel import FileRow

from .common import Example, Input, SourceRow, Step

SHEET = "Classification Data"
ID, YEAR, ITEM, FACT, CODE, SET_TYPE, VALUE = (
    "WATERBODY_ID", "CAL_YEAR", "CLASS_ITEM_NAME", "FACT_NAME", "FACT_CODE", "SET_TYPE_NAME", "FACTVALUE",
)
YEARS = (2016, 2019, 2022, 2025)  # the years the original's EA Data page shows
LEVELS = ("high", "good", "moderate", "poor")  # each threshold is that level's lower boundary (upper, if lower is better)

# How a value's status follows from its thresholds (the original's EAColour measures). One difference: the original
# never coloured Macrophytes or Phytobenthos Bad (Poor at or below the Moderate threshold); here they use "above",
# so a value at or below the Poor threshold is Bad, as for the other EQRs (BUG-REPORT.md, C8).
#   at_or_above  higher is better; High at or above the high threshold, and so on, Bad below poor
#   above        higher is better; High above the high threshold, and so on, Bad at or below poor
#   below        lower is better; High below the high threshold, and so on, Bad at or above poor
RULES: dict[str, Callable[[float, dict], str | None]] = {
    "at_or_above": lambda v, t: next((name.capitalize() for name in LEVELS if v >= t[name]), "Bad"),
    "above": lambda v, t: next((name.capitalize() for name in LEVELS if v > t[name]), "Bad"),
    "below": lambda v, t: next((name.capitalize() for name in LEVELS if v < t[name]), "Bad"),
}
RULE_WORDS = {
    "at_or_above": "High at or above the High threshold, Good at or above Good, and so on, Bad below Poor",
    "above": "High above the High threshold, Good above Good, and so on, Bad at or below Poor",
    "below": "lower is better: High below the High threshold, Good below Good, and so on, Bad at or above Poor",
}


@dataclass(frozen=True)
class Measure:
    name: str  # as on the EA Data page, and in EA Scores
    pick: Callable[[dict], bool]  # which of a year's facts are its values (the original's filters, ignoring case)
    how: str  # "average" or "median"
    decimals: int
    rule: str  # how its status follows from its thresholds (RULES)
    fixed: tuple[float, float, float, float] | None = None  # high, good, moderate, poor; or None to read them
    boundary: tuple[str, str] | None = None  # (class item, unit) of the boundary facts it reads its thresholds from
    words: str = ""  # its values, in words, for the admin page
    power_bi: str = ""  # the original's measures
    reads: tuple[str, ...] = ()  # the file's columns its values are picked by, for the admin page


def _is(cells: dict, heading: str, text: str) -> bool:
    return str(cells.get(heading) or "").casefold() == text.casefold()


def _biology(item: str, **also: str) -> Callable[[dict], bool]:
    return lambda c: _is(c, ITEM, item) and all(_is(c, h, v) for h, v in also.items())


def _reading(fact: str) -> Callable[[dict], bool]:
    return lambda c: _is(c, FACT, fact)


MEASURES = (
    Measure("Fish (EQR)", _biology("Fish", **{FACT: "EQR"}), "average", 3, "at_or_above", (0.7, 0.4, 0.2, 0.03),
            words="the average of the year's EQR facts for Fish", power_bi="FishValue2016 … FishValue2025",
            reads=(ITEM, FACT)),
    Measure("Inverts NTAXA (EQR)", _biology("Invertebrates", **{CODE: "NTAXA_EQR", SET_TYPE: "Site"}), "average", 3, "above",
            (0.8, 0.68, 0.56, 0.47), words="the average of the year's sites' NTAXA_EQR facts for Invertebrates",
            power_bi="InvertsNTAXAValue2016 …", reads=(ITEM, CODE, SET_TYPE)),
    Measure("Inverts ASPT (EQR)", _biology("Invertebrates", **{CODE: "ASPT_EQR", SET_TYPE: "Site"}), "average", 3, "above",
            (0.97, 0.86, 0.72, 0.59), words="the average of the year's sites' ASPT_EQR facts for Invertebrates",
            power_bi="InvertsASPTValue2016 …", reads=(ITEM, CODE, SET_TYPE)),
    Measure("Macrophytes Sub Element (EQR)", _biology("Macrophytes Sub Element", **{CODE: "MEAN_EQR_SITE"}), "average", 3,
            "above", (0.8, 0.6, 0.4, 0.2), words="the average of the year's MEAN_EQR_SITE facts for Macrophytes Sub Element",
            power_bi="MacrophytesValue2016 …", reads=(ITEM, CODE)),
    Measure("Phytobenthos Sub Element (EQR)", _biology("Phytobenthos Sub Element", **{CODE: "MEAN_EQR_SITE"}), "average", 3,
            "above", (0.8, 0.6, 0.4, 0.2), words="the average of the year's MEAN_EQR_SITE facts for Phytobenthos Sub Element",
            power_bi="PhytobenthosValue2016 …", reads=(ITEM, CODE)),
    Measure("Ammonia (mg/l)", _reading("Ammonia (PhysChem)"), "median", 3, "below", boundary=("Ammonia (Phys-Chem)", "mg/l"),
            words="the median of the year's Ammonia (PhysChem) facts", power_bi="AmmoniaValue2016 …", reads=(FACT,)),
    Measure("Dissolved Oxygen (%)", _reading("Dissolved Oxygen"), "median", 2, "above",
            boundary=("Dissolved oxygen", "% saturation"), words="the median of the year's Dissolved Oxygen facts",
            power_bi="DOValue2016 …", reads=(FACT,)),
    Measure("Phosphate (mg/l)", _reading("Phosphate"), "median", 3, "below", boundary=("Phosphate", "mg/l"),
            words="the median of the year's Phosphate facts", power_bi="PhosphateValue2016 …", reads=(FACT,)),
    Measure("Temperature (C)", _reading("Temperature"), "median", 2, "below", boundary=("Temperature", "celsius"),
            words="the median of the year's Temperature facts", power_bi="TempValue2016 …", reads=(FACT,)),
    Measure("pH Lower", _reading("pH (Lower)"), "median", 2, "above", boundary=("pH Lower", "pH Unit"),
            words="the median of the year's pH (Lower) facts", power_bi="pHLowerValue2016 …", reads=(FACT,)),
    Measure("pH Upper", _reading("pH (Upper)"), "median", 2, "below", boundary=("pH Upper", "pH Unit"),
            words="the median of the year's pH (Upper) facts", power_bi="pHUpperValue2016 …", reads=(FACT,)),
)
BOUNDARIES = {"high": "High/Good", "good": "Good/Moderate", "moderate": "Moderate/Poor", "poor": "Poor/Bad"}


def _number(value) -> float | None:
    """A fact's value as a number, or None (the original's FACT_VALUE_NUM: VALUE(), or blank if it isn't one)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # not NaN


def rounded(value: float, decimals: int) -> float:
    """Rounded with halves up, as Excel and Power BI show it (0.0465 is 0.047)."""
    return float(Decimal(repr(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP))


def work_out(rows: list[SourceRow], problems: list[str], notes: list[str]) -> dict[str, list[FileRow]]:
    values: dict[tuple[str, str, int], list[float]] = {}  # (catchment, measure, year) -> its facts' values
    lines: dict[tuple, int] = {}  # the first row in the file for each value, measure and catchment
    bounds: dict[tuple[str, str, str], dict[int, list[float]]] = {}  # (catchment, item, fact) -> year -> values
    for row in rows:
        lines.setdefault((row.catchment_id,), row.line)
        number = _number(row.cells.get(VALUE))
        year = row.cells.get(YEAR)
        if number is None or year is None:
            continue
        if (as_number := _number(year)) is None or not as_number.is_integer():
            problems.append(f"{row.where}, {YEAR}: {year!r} isn't a year.")
            continue
        year = int(as_number)
        key = (row.catchment_id, str(row.cells.get(ITEM) or "").casefold(), str(row.cells.get(FACT) or "").casefold())
        bounds.setdefault(key, {}).setdefault(year, []).append(number)
        if year in YEARS:
            for measure in MEASURES:
                if measure.pick(row.cells):
                    values.setdefault((row.catchment_id, measure.name, year), []).append(number)
                    lines.setdefault((row.catchment_id, measure.name, year), row.line)
                    lines.setdefault((row.catchment_id, measure.name), row.line)

    catchments = sorted({row.catchment_id for row in rows})
    thresholds, limits = [], {}
    for catchment_id in catchments:
        for measure in MEASURES:
            if measure.fixed:
                found = dict(zip(LEVELS, measure.fixed))
            else:
                item, unit = measure.boundary
                found = {}
                for level, boundary in BOUNDARIES.items():
                    by_year = bounds.get((catchment_id, item.casefold(), f"{boundary} Boundary - {unit}".casefold()))
                    found[level] = max(by_year[max(by_year)]) if by_year else None  # MAX in its latest year
                if all(v is None for v in found.values()):
                    continue
            limits[catchment_id, measure.name] = found
            line = lines.get((catchment_id, measure.name)) or lines[catchment_id,]
            thresholds.append(FileRow(line, {"catchment_id": catchment_id, "measure": measure.name, **found}))

    scores = []
    for (catchment_id, name, year), found in sorted(values.items()):
        measure = next(m for m in MEASURES if m.name == name)
        value = statistics.fmean(found) if measure.how == "average" else statistics.median(found)
        limit = limits.get((catchment_id, name), {})
        status = RULES[measure.rule](value, limit) if all(limit.get(level) is not None for level in LEVELS) else None
        scores.append(FileRow(lines[catchment_id, name, year], {
            "catchment_id": catchment_id, "measure": name, "year": year,
            "value": rounded(value, measure.decimals), "status": status,
        }))
    return {"ea_scores": scores, "ea_thresholds": thresholds}


# --- In words, for the admin page --------------------------------------------------------

def _listed(values: list[float], most: int = 8) -> str:
    """e.g. 0.71, 0.74 and 0.72; or the first 8 and how many more. As in the file, not rounded."""
    shown = [f"{v:g}" for v in values[:most]]
    if len(values) > most:
        return f"{', '.join(shown)} and {len(values) - most} more"
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def _value_example(measure: Measure):
    """The measure's value for the waterbody in the year with the most facts (the latest, if several have as many):
    e.g. In 2019, the average of 0.71, 0.74 and 0.72 is 0.72333, which rounds to 0.723."""
    def example(ex: Example) -> str | None:
        found = {row["year"]: row["value"] for row in ex.out if row["measure"] == measure.name}
        facts = {year: [] for year in found}
        for row in ex.rows:
            year = _number(row.cells.get(YEAR))
            if year in facts and measure.pick(row.cells) and (number := _number(row.cells.get(VALUE))) is not None:
                facts[year].append(number)
        if not found or not any(facts.values()):
            return None
        year = max(found, key=lambda y: (len(facts[y]), y))
        values, shown = facts[year], found[year]
        if len(values) == 1:
            worked = f"In {year}, its one fact is {values[0]:g}"
        else:
            raw = statistics.fmean(values) if measure.how == "average" else statistics.median(values)
            worked = f"In {year}, the {measure.how} of {_listed(values)} is {raw:.6g}"
        return worked + (f", which rounds to {shown:g}" if f"{shown:g}" != f"{values[0] if len(values) == 1 else raw:.6g}" else "")
    return example


def _status_example(ex: Example) -> str | None:
    """e.g. Fish (EQR) in 2025: 0.723, with High at 0.7, Good 0.4, Moderate 0.2 and Poor 0.03, is High."""
    row = next((row for row in ex.out if row["status"]), None)
    limits = next((t for t in ex.tables.get("ea_thresholds", []) if row and t["measure"] == row["measure"]), None)
    if row is None or limits is None:
        return None
    return (f"{row['measure']} in {row['year']}: {row['value']:g}, with High at {limits['high']:g}, Good {limits['good']:g}, "
            f"Moderate {limits['moderate']:g} and Poor {limits['poor']:g}, is {row['status']}")


def _boundary_example(ex: Example) -> str | None:
    """e.g. Phosphate (mg/l): its boundaries in 2022, the latest year with them, are 0.036, 0.069, 0.164 and 1.003."""
    for row in ex.out:
        measure = next((m for m in MEASURES if m.name == row["measure"] and m.boundary), None)
        if measure is None:
            continue
        item, unit = measure.boundary
        years = {
            int(year) for r in ex.rows
            if str(r.cells.get(ITEM) or "").casefold() == item.casefold()
            and str(r.cells.get(FACT) or "").casefold().endswith(f"boundary - {unit}".casefold())
            and (year := _number(r.cells.get(YEAR))) is not None
        }
        found = ", ".join(f"{BOUNDARIES[level]} {row[level]:g}" for level in LEVELS if row[level] is not None)
        latest = f" in {max(years)}, the latest year with them" if years else ""
        return f"{measure.name}: its boundaries{latest}: {found}"
    return None


def _score_steps() -> tuple[Step, ...]:
    groups: dict[str, list[str]] = {}
    for m in MEASURES:
        groups.setdefault(m.rule, []).append(m.name)
    status = "; ".join(f"{', '.join(names)}: {RULE_WORDS[rule]}" for rule, names in groups.items())
    return (
        Step(
            ("measure", "year"), (YEAR,),
            f"A row for each measure below and each of {', '.join(map(str, YEARS))} that has its facts.",
            "The EA Data page's rows (the EA scores table) and its year columns",
        ),
        *(Step(("value",), (*m.reads, YEAR, VALUE),
               f"{m.name}: {m.words}, rounded to {m.decimals} decimal places (halves up).",
               f"DAX measures EA Classification Data[{m.power_bi}]", _value_example(m)) for m in MEASURES),
        Step(
            ("status",), ("value", "EA Thresholds"),
            f"From the value (before rounding) and its thresholds: {status}.",
            "DAX measures EA Classification Data[EAColour2016] … [EAColour2025] (each value's colour)",
            _status_example,
        ),
    )


def _threshold_steps() -> tuple[Step, ...]:
    fixed = "; ".join(f"{m.name} {', '.join(f'{v:g}' for v in m.fixed)}" for m in MEASURES if m.fixed)
    read = ", ".join(m.name for m in MEASURES if m.boundary)
    return (
        Step(
            ("measure",), (),
            "A row for each measure: the five biological ones for every waterbody in the file, and each "
            "physico-chemical one where the waterbody has boundaries.",
            "The EA Data page's threshold columns: DAX measures EA Classification Data[High], [Good], [Moderate], [Poor]",
        ),
        Step(
            ("high", "good", "moderate", "poor"), (),
            f"Biology's are fixed (High, Good, Moderate, Poor): {fixed}.",
            "DAX measures EA Classification Data[FishHigh], [FishGood] … (value(0.7) and so on)",
        ),
        Step(
            ("high", "good", "moderate", "poor"), (ITEM, FACT, YEAR, VALUE),
            f"Physico-chemistry's ({read}): the waterbody's High/Good, Good/Moderate, Moderate/Poor and Poor/Bad "
            "Boundary facts, from the latest year that has each (the largest, if there are several).",
            "DAX measures EA Classification Data[AmmoniaHigh], [AmmoniaGood] … (MAX in the LatestYear)",
            _boundary_example,
        ),
    )


EA_CLASSIFICATION_FACTS = Input(
    name="ea_classification_facts",
    title="EA classification facts",
    provider="The EA, who send the classification facts for each waterbody on request",
    file="North Devon WB Classification Facts Data.xlsx",
    sheet=SHEET,
    headings=(ID, YEAR, ITEM, FACT, CODE, SET_TYPE, VALUE),
    waterbody_heading=ID,
    by_id=True,
    one_row_each=False,
    query="EA Classification Data",
    match="Relationship EA Classification Data[WATERBODY_NAME] to Waterbody Lookup[water_body_name]",
    steps={"ea_scores": _score_steps(), "ea_thresholds": _threshold_steps()},
    work_out=work_out,
)
