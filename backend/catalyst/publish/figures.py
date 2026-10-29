"""What the dashboard works out from a location's data: each catchment's
ecological status, the counts on the Overview, the EA scoring grid, and each
habitat's share of its catchment.

Like collect.py, this knows nothing about web pages. Each figure copes with its
table not existing (it's simply empty), so the dashboard shows an empty panel
until the table is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .collect import Location

ECOLOGICAL = "Ecological"  # the EA Scores measure the maps are coloured by
CLASSIFICATION_YEARS = 3  # years shown in the "EA Ecological Classification" panel

# The EA's order for its classification items (as on its Catchment Data
# Explorer). Measures not listed go after these, alphabetically.
MEASURE_ORDER = [
    "Ecological",
    "Biological quality elements",
    "Fish",
    "Invertebrates",
    "Macrophytes and phytobenthos",
    "Macrophytes",
    "Phytobenthos",
    "Physico-chemical quality elements",
    "Ammonia",
    "Dissolved oxygen",
    "Phosphate",
    "Temperature",
    "pH",
    "Hydromorphological supporting elements",
    "Hydrological regime",
    "Morphology",
    "Chemical",
]
# Best first. Statuses not listed (e.g. "Fail") are counted after these.
STATUS_ORDER = ["High", "Good", "Moderate", "Poor", "Bad"]


@dataclass
class Score:
    year: int
    status: str | None
    value: float | None


@dataclass
class ScoringRow:
    measure: str
    by_year: dict[int, Score] = field(default_factory=dict)

    @property
    def latest(self) -> Score | None:
        return self.by_year[max(self.by_year)] if self.by_year else None


@dataclass
class Scoring:
    """The EA Data page's grid: a row per measure, a column per year."""
    years: list[int]  # newest first
    rows: list[ScoringRow]


class Figures:
    def __init__(self, location: Location):
        self.location = location
        # Catchment ID -> year -> ecological status
        self.ecological: dict[str, dict[int, str]] = {}
        scores = location.dataset("ea_scores")
        for catchment_id, rows in (scores.rows if scores else {}).items():
            for row in rows:
                if _same(row["measure"], ECOLOGICAL) and row["status"]:
                    self.ecological.setdefault(catchment_id, {})[row["year"]] = row["status"]
        self.years = sorted({y for by_year in self.ecological.values() for y in by_year}, reverse=True)

    def status(self, catchment_id: str) -> str | None:
        """The catchment's latest ecological status."""
        by_year = self.ecological.get(catchment_id)
        return by_year[max(by_year)] if by_year else None

    def classification(self, catchment_id: str) -> list[tuple[int, str | None]]:
        """The catchment's ecological status in each of the latest years."""
        by_year = self.ecological.get(catchment_id, {})
        return [(year, by_year.get(year)) for year in self.years[:CLASSIFICATION_YEARS]]

    def status_counts(self) -> list[tuple[str, int]]:
        """How many catchments have each ecological status in the latest year, most first."""
        if not self.years:
            return []
        counts: dict[str, int] = {}
        for by_year in self.ecological.values():
            if self.years[0] in by_year:
                counts[by_year[self.years[0]]] = counts.get(by_year[self.years[0]], 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], _rank(item[0], STATUS_ORDER)))

    def statuses(self) -> list[str]:
        """The statuses the maps show (each catchment's latest), best first, for their key."""
        found = {self.status(catchment_id) for catchment_id in self.ecological}
        return sorted(found, key=lambda s: _rank(s, STATUS_ORDER))

    def rivers(self) -> int:
        return sum(1 for c in self.location.catchments if c["waterbody_type"] == "River")

    def scoring(self, catchment_id: str) -> Scoring:
        scores = self.location.dataset("ea_scores")
        if not scores:
            return Scoring([], [])
        years = sorted({r["year"] for rows in scores.rows.values() for r in rows}, reverse=True)
        rows: dict[str, ScoringRow] = {}
        for r in scores.rows_for(catchment_id):
            row = rows.setdefault(r["measure"], ScoringRow(r["measure"]))
            row.by_year[r["year"]] = Score(r["year"], r["status"], r["value"])
        return Scoring(years, sorted(rows.values(), key=lambda row: _rank(row.measure, MEASURE_ORDER)))

    def habitat(self, catchment: dict[str, Any]) -> list[dict[str, Any]]:
        """The catchment's habitat rows, each with its share of the catchment's area (%)."""
        habitat = self.location.dataset("habitat_land_use")
        if not habitat:
            return []
        area = catchment["area_ha"]
        return [{**row, "share": 100 * row["area_ha"] / area if area else None} for row in habitat.rows_for(catchment["id"])]


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.lower()


def _rank(name: str, order: list[str]) -> tuple[int, str]:
    """Sorts names by their place in order, then any others alphabetically."""
    lowered = [o.lower() for o in order]
    key = name.strip().lower()
    return (lowered.index(key), "") if key in lowered else (len(order), key)
