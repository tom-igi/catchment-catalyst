"""What the dashboard works out from a location's data: each catchment's
ecological status, the counts on the Overview, the EA scoring grid, the
failing elements and reasons, each habitat's share of its catchment, the storm
overflow spills and the points on the small maps.

Like collect.py, this knows nothing about web pages. Each figure copes with its
table not existing (it's simply empty), so the dashboard shows an empty panel
until the table is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .collect import Location

CLASSIFICATIONS = "ea_classifications"
RNAGS = "ea_rnags"
OVERFLOWS = "storm_overflows"
OBSTACLES = "river_obstacles"
OVERFLOW_YEARS = 5  # years of storm overflow spills shown
ECOLOGICAL = "Ecological"  # the classification item the maps are coloured by
CLASSIFICATION_YEARS = 3  # years shown in the "EA Ecological Classification" panel
SCORING_YEARS = 4  # years shown on the EA Data page, besides "Latest"

# The classification items on the EA Data page, in the EA's order (as on the
# original dashboard). The EA classifies many more, mostly single chemicals:
# they aren't shown.
SCORING_ITEMS = [
    "Ecological",
    "Biological quality elements",
    "Fish",
    "Invertebrates",
    "Macrophytes and Phytobenthos Combined",
    "Macrophytes Sub Element",
    "Phytobenthos Sub Element",
    "Physico-chemical quality elements",
    "Ammonia (Phys-Chem)",
    "Dissolved oxygen",
    "Phosphate",
    "Temperature",
    "pH",
    "Acid Neutralising Capacity",
    "Hydromorphological Supporting Elements",
    "Hydrological Regime",
    "Morphology",
    "Specific pollutants",
    "Chemical",
]
# Best first. Statuses not listed are counted after these.
STATUS_ORDER = ["High", "Good", "Moderate", "Poor", "Bad"]

# Failing elements: elements (and sub elements) below Good in the catchment's
# latest classification year. "Fail" is left out: it's the chemicals' status,
# which the original dashboard doesn't list. When a sub element is failing, the
# combined element above it is left out, as on the original.
BELOW_GOOD = {"Moderate", "Moderate or less", "Poor", "Bad", "Does Not Support Good"}
FAILING_LEVELS = {"Element", "Sub Element"}
COMBINED = "Macrophytes and Phytobenthos Combined"
NO_REASON = "Not applicable"  # an RNAG activity that says nothing, so isn't shown


@dataclass
class ScoringRow:
    item: str
    by_year: dict[int, str] = field(default_factory=dict)  # year -> status

    @property
    def latest(self) -> str | None:
        return self.by_year[max(self.by_year)] if self.by_year else None


@dataclass
class Discharges:
    """The Sewerage Data page's table: the hours each storm overflow spilled, each year."""
    years: list[int]  # oldest first
    sites: list[tuple[str, dict[int, float]]]  # (overflow, year -> hours), for those with any hours
    company: str | None  # the water company, if there's only one

    def year_total(self, year: int) -> float:
        return sum(by_year.get(year, 0) for _, by_year in self.sites)

    def total(self) -> float:
        return sum(sum(by_year.values()) for _, by_year in self.sites)


@dataclass
class Scoring:
    """The EA Data page's grid: a row per classification item, a column per year."""
    years: list[int]  # newest first
    rows: list[ScoringRow]


class Figures:
    def __init__(self, location: Location):
        self.location = location
        # Catchment ID -> (item, year) -> its classification. Where a year was
        # classified in more than one cycle, the latest cycle's is kept.
        self.results: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
        classifications = location.dataset(CLASSIFICATIONS)
        for catchment_id, rows in (classifications.rows if classifications else {}).items():
            results = self.results.setdefault(catchment_id, {})
            for row in rows:
                key = (row["item"], row["year"])
                if row["status"] and (key not in results or row["cycle"] > results[key]["cycle"]):
                    results[key] = row
        # Catchment ID -> year -> ecological status
        self.ecological: dict[str, dict[int, str]] = {}
        for catchment_id, results in self.results.items():
            by_year = {year: row["status"] for (item, year), row in results.items() if item == ECOLOGICAL}
            if by_year:
                self.ecological[catchment_id] = by_year
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
        years = sorted({year for results in self.results.values() for _, year in results}, reverse=True)
        rows: dict[str, ScoringRow] = {}
        for (item, year), row in self.results.get(catchment_id, {}).items():
            if item in SCORING_ITEMS:
                rows.setdefault(item, ScoringRow(item)).by_year[year] = row["status"]
        return Scoring(years[:SCORING_YEARS], sorted(rows.values(), key=lambda row: SCORING_ITEMS.index(row.item)))

    def failing_elements(self, catchment_id: str) -> list[str]:
        if catchment_id not in self.ecological:
            return []
        year = max(self.ecological[catchment_id])
        failing = {
            item: row for (item, y), row in self.results[catchment_id].items()
            if y == year and row["level"] in FAILING_LEVELS and row["status"] in BELOW_GOOD
        }
        if any(row["level"] == "Sub Element" for row in failing.values()):
            failing.pop(COMBINED, None)
        return sorted(failing, key=str.lower)

    def reasons(self, catchment_id: str) -> list[str]:
        """The activities the EA gives as reasons for not achieving good, in its latest cycle."""
        rnags = self.location.dataset(RNAGS)
        rows = rnags.rows_for(catchment_id) if rnags else []
        if not rows:
            return []
        cycle = max(row["cycle"] or 0 for row in rows)
        found = {row["activity"] for row in rows if (row["cycle"] or 0) == cycle and row["activity"] not in (None, NO_REASON)}
        return sorted(found, key=str.lower)

    def discharges(self, catchment_id: str) -> Discharges:
        overflows = self.location.dataset(OVERFLOWS)
        if not overflows:
            return Discharges([], [], None)
        everywhere = [row for rows in overflows.rows.values() for row in rows]
        years = sorted({row["year"] for row in everywhere})[-OVERFLOW_YEARS:]
        companies = {row["company"] for row in everywhere if row["company"]}
        sites: dict[str, dict[int, float]] = {}
        for row in overflows.rows_for(catchment_id):
            # Blank hours mean no figure (e.g. no monitor yet): such overflows are left out, as on the original.
            if row["year"] in years and row["spill_hours"] is not None:
                by_year = sites.setdefault(row["site_name"] or "", {})
                by_year[row["year"]] = by_year.get(row["year"], 0) + row["spill_hours"]
        return Discharges(years, sorted(sites.items()), companies.pop() if len(companies) == 1 else None)

    def outlets(self, catchment_id: str) -> list[tuple[float, float, str]]:
        """Where the overflows in the discharges table are, from their latest year: (latitude, longitude, name)."""
        overflows = self.location.dataset(OVERFLOWS)
        shown = {site for site, _ in self.discharges(catchment_id).sites}
        latest: dict[str, dict[str, Any]] = {}
        for row in overflows.rows_for(catchment_id) if overflows else []:
            if row["site_name"] in shown and row["latitude"] is not None:
                if row["site_name"] not in latest or row["year"] > latest[row["site_name"]]["year"]:
                    latest[row["site_name"]] = row
        return [(row["latitude"], row["longitude"], site) for site, row in sorted(latest.items())]

    def obstacles(self, catchment_id: str) -> list[dict[str, Any]]:
        obstacles = self.location.dataset(OBSTACLES)
        rows = obstacles.rows_for(catchment_id) if obstacles else []
        return sorted(rows, key=lambda row: (row["ea_id"] is None, row["ea_id"] or 0))

    def obstacle_points(self, catchment_id: str) -> list[tuple[float, float, str]]:
        """Where the obstacles are: (latitude, longitude, e.g. 'culvert, EA ID 39245')."""
        return [
            (o["latitude"], o["longitude"], ", ".join(str(part) for part in (o["obstacle_type"], o["ea_id"] and f"EA ID {o['ea_id']}") if part))
            for o in self.obstacles(catchment_id)
        ]

    def habitat(self, catchment: dict[str, Any]) -> list[dict[str, Any]]:
        """The catchment's habitat rows, each with its share of the catchment's area (%)."""
        habitat = self.location.dataset("habitat_land_use")
        if not habitat:
            return []
        area = catchment["area_ha"]
        return [{**row, "share": 100 * row["area_ha"] / area if area else None} for row in habitat.rows_for(catchment["id"])]


def _rank(name: str, order: list[str]) -> tuple[int, str]:
    """Sorts names by their place in order, then any others alphabetically."""
    lowered = [o.lower() for o in order]
    key = name.strip().lower()
    return (lowered.index(key), "") if key in lowered else (len(order), key)
