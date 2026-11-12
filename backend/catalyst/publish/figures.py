"""What the dashboard works out from a location's data: each catchment's
ecological status, the counts on the Overview, the EA scoring grid (with its
values and thresholds), the failing elements and reasons, each habitat's share
of its catchment, livestock densities, the phosphate sources, the storm
overflow spills, the points on the small maps, the Catchment Dashboard's
totals for the whole location or one of its operational catchments, and
Intervention Management's summary totals and lists of waterbodies.

Like collect.py, this knows nothing about web pages. Each figure copes with its
table not existing (it's simply empty), so the dashboard shows an empty panel
until the table is added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .collect import Location, slug

CLASSIFICATIONS = "ea_classifications"
RNAGS = "ea_rnags"
OVERFLOWS = "storm_overflows"
OBSTACLES = "river_obstacles"
SCORES = "ea_scores"
THRESHOLDS = "ea_thresholds"
HABITAT = "habitat_land_use"
RIVER_TEXT = "river_status_text"
RISKS = "risk_levels"
RANKINGS = "catchment_rankings"
FARMS = "farms"
LIVESTOCK = "livestock"
PHOSPHATE = "phosphate_sources"
PROPERTIES = "sewerage_properties"
IMPROVEMENTS = "sewerage_improvements"
LOCATION_TEXT = "location_text"
INTERVENTION_TYPES = "intervention_types"
INTERVENTION_WATERBODIES = "intervention_waterbodies"
UNIT_COSTS = "intervention_unit_costs"
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
# The measured values (in EA Scores, with their thresholds in EA Thresholds)
# shown with each classification item, as on the original dashboard. An item
# with one measure shows it in its own row (e.g. "Fish (EQR)" instead of
# "Fish"); one with several keeps its row of statuses, with a row for each
# measure below it. Measures not listed here go at the bottom.
MEASURES = {
    "Fish": ["Fish (EQR)"],
    "Invertebrates": ["Inverts NTAXA (EQR)", "Inverts ASPT (EQR)"],
    "Macrophytes Sub Element": ["Macrophytes Sub Element (EQR)"],
    "Phytobenthos Sub Element": ["Phytobenthos Sub Element (EQR)"],
    "Ammonia (Phys-Chem)": ["Ammonia (mg/l)"],
    "Dissolved oxygen": ["Dissolved Oxygen (%)"],
    "Phosphate": ["Phosphate (mg/l)"],
    "Temperature": ["Temperature (C)"],
    "pH": ["pH Lower", "pH Upper"],
}
# Best first. Statuses not listed are counted after these.
STATUS_ORDER = ["High", "Good", "Moderate", "Poor", "Bad"]

# The Risk Levels tiles: the column in Risk Levels -> the tile's name.
RISK_NAMES = {
    "untreated_sewage": "Untreated Sewage",
    "sewage_private": "Sewage (Private)",
    "livestock": "Livestock",
    "runoff": "Runoff",
    "modification": "Modification",
    "invasive_species": "Invasive Species",
    "overheating": "Overheating",
    "running_dry": "Running Dry",
}
# The Sewerage Data page's Source of Phosphate groups, in order.
DISCHARGES = ["Continuous", "Diffuse"]

# Failing elements: elements (and sub elements) below Good in the catchment's
# latest classification year. "Fail" is left out: it's the chemicals' status,
# which the original dashboard doesn't list. When a sub element is failing, the
# combined element above it is left out, as on the original.
BELOW_GOOD = {"Moderate", "Moderate or less", "Poor", "Bad", "Does Not Support Good"}
FAILING_LEVELS = {"Element", "Sub Element"}
COMBINED = "Macrophytes and Phytobenthos Combined"
NO_REASON = "Not applicable"  # an RNAG activity that says nothing, so isn't shown


@dataclass
class Cell:
    """A cell of the EA scoring grid: a status (e.g. Moderate) or a measured value (e.g. 0.36), and the status that colours it."""
    text: str
    status: str | None


@dataclass
class ScoringRow:
    item: str  # the row's name: a classification item (e.g. Fish) or a measure (e.g. Fish (EQR))
    by_year: dict[int, Cell] = field(default_factory=dict)
    thresholds: dict[str, Any] | None = None  # poor, moderate, good, high, for a measure

    @property
    def latest(self) -> Cell | None:
        return self.by_year[max(self.by_year)] if self.by_year else None


@dataclass
class Area:
    """A part of the location on the Catchment Dashboard: a management or operational catchment."""
    kind: str  # "management" or "operational"
    ea_id: int | None
    name: str
    slug: str  # its folder in catchment-dashboard/, or "" for a management catchment that's the whole location
    catchment_ids: list[str]
    parent: str | None = None  # an operational catchment's management catchment


@dataclass
class Total:
    """A figure added up over several catchments, and how many of them had a figure."""
    value: float | None
    known: int  # catchments with a figure
    of: int  # catchments

    @property
    def partial(self) -> bool:
        return self.value is not None and self.known < self.of


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
class SummaryPart:
    """A part of Intervention Management's summary table (e.g. Secondary interventions), with its total."""
    name: str
    rows: list[dict[str, Any]]  # its intervention types, by number

    @property
    def cost(self) -> float:
        return sum(row["summary_cost"] or 0 for row in self.rows)

    @property
    def available(self) -> float:
        """The cost that funding is available for: each type's cost times its % available."""
        return sum((row["summary_cost"] or 0) * (row["percent_available"] or 0) / 100 for row in self.rows)

    @property
    def to_find(self) -> float:
        return self.cost - self.available


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
        """The EA Data page's grid: the EA's statuses for each item, with the measured values and thresholds where there are any."""
        scores = self.location.dataset(SCORES)
        everywhere = [row for rows in (scores.rows.values() if scores else []) for row in rows]
        years = sorted(
            {year for results in self.results.values() for _, year in results} | {row["year"] for row in everywhere},
            reverse=True,
        )[:SCORING_YEARS]

        statuses: dict[str, dict[int, str]] = {}  # item -> year -> the EA's status
        for (item, year), row in self.results.get(catchment_id, {}).items():
            if item in SCORING_ITEMS and year in years:
                statuses.setdefault(item, {})[year] = row["status"]
        values: dict[str, dict[int, dict[str, Any]]] = {}  # measure -> year -> its row in EA Scores
        for row in scores.rows_for(catchment_id) if scores else []:
            if row["year"] in years and (row["value"] is not None or row["status"]):
                values.setdefault(row["measure"], {})[row["year"]] = row
        thresholds = self.location.dataset(THRESHOLDS)
        limits = {row["measure"]: row for row in (thresholds.rows_for(catchment_id) if thresholds else [])}

        def measure_row(measure: str, item_statuses: dict[int, str], prefer_item: bool) -> ScoringRow:
            cells = {}
            for year in set(values.get(measure, {})) | (set(item_statuses) if prefer_item else set()):
                row = values.get(measure, {}).get(year)
                own = row["status"] if row else None
                status = (item_statuses.get(year) or own) if prefer_item else (own or item_statuses.get(year))
                text = measured(row["value"]) if row and row["value"] is not None else (status or "")
                cells[year] = Cell(text, status)
            return ScoringRow(measure, cells, limits.get(measure))

        rows: list[ScoringRow] = []
        placed: set[str] = set()
        for item in SCORING_ITEMS:
            item_statuses = statuses.get(item, {})
            measures = [m for m in MEASURES.get(item, []) if m in values or m in limits]
            placed.update(measures)
            if len(MEASURES.get(item, [])) == 1 and measures:
                # One measure: its values in the item's row, coloured by the EA's status, as on the original.
                rows.append(measure_row(measures[0], item_statuses, prefer_item=True))
                continue
            if item_statuses:
                rows.append(ScoringRow(item, {year: Cell(status, status) for year, status in item_statuses.items()}))
            rows.extend(measure_row(m, item_statuses, prefer_item=False) for m in measures)
        for measure in sorted((set(values) | set(limits)) - placed, key=str.lower):
            rows.append(measure_row(measure, {}, prefer_item=False))
        return Scoring(years, rows)

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
        habitat = self.location.dataset(HABITAT)
        if not habitat:
            return []
        area = catchment["area_ha"]
        return [{**row, "share": 100 * row["area_ha"] / area if area else None} for row in habitat.rows_for(catchment["id"])]

    # -------------------------------------------------------------------------
    #  The hand-written analysis (River Status page)
    # -------------------------------------------------------------------------

    def river_text(self, catchment_id: str) -> dict[str, Any]:
        """The catchment's row in River Status Text, or an empty one."""
        return self._one(RIVER_TEXT, catchment_id)

    def ranking(self, catchment_id: str) -> int | None:
        return self._one(RANKINGS, catchment_id).get("ranking")

    def risks(self, catchment_id: str, columns: list[str]) -> list[tuple[str, str | None]]:
        """The Risk Levels tiles: (name, level) for each of the columns, in that order."""
        row = self._one(RISKS, catchment_id)
        return [(RISK_NAMES[column], row.get(column)) for column in columns]

    def interventions(self, catchment_id: str) -> list[tuple[str, list[dict[str, Any]]]]:
        """The River Status page's interventions: the catchment's rows in Intervention Waterbodies, each with its
        type's name, in the parts of the Intervention Summary table (e.g. Priority interventions), by number."""
        dataset = self.location.dataset(INTERVENTION_WATERBODIES)
        kinds = {row["number"]: row for row in self.intervention_types()}
        groups: dict[str, list[dict[str, Any]]] = {part.name: [] for part in self.intervention_summary()}
        for row in sorted(dataset.rows_for(catchment_id) if dataset else [], key=lambda row: row["intervention"]):
            kind = kinds.get(row["intervention"], {})
            groups.setdefault((kind.get("summary_group") or "").strip(), []).append(
                {**row, "name": kind.get("name") or f"Intervention {row['intervention']}"}
            )
        return [(name, rows) for name, rows in groups.items() if rows]

    # -------------------------------------------------------------------------
    #  Land use and sewerage (Land Use Data and Sewerage Data pages)
    # -------------------------------------------------------------------------

    def farms(self, catchment_id: str) -> int | None:
        return self._one(FARMS, catchment_id).get("number_of_farms")

    def livestock(self, catchment: dict[str, Any]) -> list[dict[str, Any]]:
        """The catchment's livestock, each with its density per square kilometre (100 ha)."""
        dataset = self.location.dataset(LIVESTOCK)
        area = catchment["area_ha"]
        return [
            {**row, "density": row["number"] / (area / 100) if area else None}
            for row in (dataset.rows_for(catchment["id"]) if dataset else [])
        ]

    def phosphate(self, catchment_id: str) -> tuple[list[int], list[tuple[str, dict[int, float]]]]:
        """The years, and each source's share of the phosphate in each year (%), by source."""
        dataset = self.location.dataset(PHOSPHATE)
        rows = dataset.rows_for(catchment_id) if dataset else []
        sources: dict[str, dict[int, float]] = {}
        for row in rows:
            sources.setdefault(row["source"], {})[row["year"]] = row["percent"]
        return sorted({row["year"] for row in rows}), sorted(sources.items(), key=lambda item: item[0].lower())

    def phosphate_discharges(self, catchment_id: str) -> tuple[list[int], list[tuple[str, dict[int, float]]]]:
        """The phosphate sources added up into Continuous and Diffuse, for the Sewerage Data page."""
        dataset = self.location.dataset(PHOSPHATE)
        rows = dataset.rows_for(catchment_id) if dataset else []
        groups: dict[str, dict[int, float]] = {}
        for row in rows:
            if row["discharge"] and row["discharge"].strip():
                by_year = groups.setdefault(row["discharge"].strip().capitalize(), {})
                by_year[row["year"]] = by_year.get(row["year"], 0) + row["percent"]
        years = sorted({year for by_year in groups.values() for year in by_year})
        return years, sorted(groups.items(), key=lambda group: _rank(group[0], DISCHARGES))

    def properties(self, catchment: dict[str, Any]) -> dict[str, Any]:
        """Properties on public and private sewerage, and private sewerage per hectare of the catchment."""
        row = self._one(PROPERTIES, catchment["id"])
        private = row.get("private_sewerage_properties")
        area = catchment["area_ha"]
        return {
            "public": row.get("public_sewerage_properties"),
            "private": private,
            "private_per_ha": private / area if private is not None and area else None,
        }

    def improvements(self, catchment_id: str) -> list[dict[str, Any]]:
        dataset = self.location.dataset(IMPROVEMENTS)
        return sorted(dataset.rows_for(catchment_id) if dataset else [], key=lambda row: row["site_name"].lower())

    def company(self) -> str | None:
        """The water company, if the location's storm overflows all belong to one."""
        overflows = self.location.dataset(OVERFLOWS)
        companies = {row["company"] for rows in (overflows.rows.values() if overflows else []) for row in rows if row["company"]}
        return companies.pop() if len(companies) == 1 else None

    # -------------------------------------------------------------------------
    #  About the whole location
    # -------------------------------------------------------------------------

    def location_text(self) -> dict[str, Any]:
        """The location's row in Location Text, or an empty one."""
        return self._one(LOCATION_TEXT, self.location.id)

    def areas(self) -> list[Area]:
        """The location's management catchments, each followed by its operational catchments, by name.

        A management catchment that covers the whole location is the Catchment
        Dashboard's front page, so it has no folder of its own.
        """
        groups: dict[tuple[str, str], tuple[int | None, list[str], str | None]] = {}
        for c in self.location.catchments:
            for kind, name, ea_id, parent in (
                ("management", c["management_catchment"], c["management_catchment_id"], None),
                ("operational", c["operational_catchment"], c["operational_catchment_id"], c["management_catchment"]),
            ):
                if name:
                    groups.setdefault((kind, name), (ea_id, [], parent))[1].append(c["id"])
        everything = {c["id"] for c in self.location.catchments}
        areas = [
            Area(kind, ea_id, name, slug(name), ids, parent)
            for (kind, name), (ea_id, ids, parent) in groups.items()
        ]
        for area in areas:
            if area.kind == "management" and set(area.catchment_ids) == everything:
                area.slug = ""
        # Two areas with the same name (e.g. a management and an operational
        # catchment) get the EA's ID added to their folders, so each has its own.
        clashes = [area for area in areas if area.slug and sum(a.slug == area.slug for a in areas) > 1]
        for area in clashes:
            area.slug = f"{area.slug}-{area.ea_id}"
        management = sorted((a for a in areas if a.kind == "management"), key=lambda a: a.name.lower())
        ordered = []
        for top in management:
            ordered.append(top)
            ordered.extend(sorted((a for a in areas if a.kind == "operational" and a.parent == top.name), key=lambda a: a.name.lower()))
        return ordered

    def latest_year(self) -> int | None:
        return self.years[0] if self.years else None

    def class_counts(self, ids: list[str]) -> list[tuple[str, int | None]]:
        """How many of these catchments have each ecological status in the latest year: every status, best first (None for none)."""
        counts: dict[str, int] = {}
        year = self.latest_year()
        for catchment_id in ids:
            status = self.ecological.get(catchment_id, {}).get(year)
            if status:
                counts[status] = counts.get(status, 0) + 1
        statuses = STATUS_ORDER + sorted((s for s in counts if s not in STATUS_ORDER), key=lambda s: _rank(s, STATUS_ORDER))
        return [(status, counts.get(status)) for status in statuses]

    def total(self, table: str, column: str, ids: list[str]) -> Total:
        """A column added up over these catchments."""
        dataset = self.location.dataset(table)
        known = [row[column] for i in ids for row in (dataset.rows_for(i)[:1] if dataset else []) if row[column] is not None]
        return Total(sum(known) if known else None, len(known), len(ids))

    def overflow_count(self, ids: list[str]) -> int | None:
        """How many storm overflows discharge into these catchments, in the latest year of the returns."""
        overflows = self.location.dataset(OVERFLOWS)
        if not overflows or not overflows.rows:
            return None
        latest = max(row["year"] for rows in overflows.rows.values() for row in rows)
        return len({(i, row["site_name"]) for i in ids for row in overflows.rows_for(i) if row["year"] == latest})

    def habitat_totals(self, ids: list[str]) -> tuple[list[dict[str, Any]], Total]:
        """Each habitat's area over these catchments, and its share of the area of the catchments that have habitat figures."""
        habitat = self.location.dataset(HABITAT)
        areas = {c["id"]: c["area_ha"] or 0 for c in self.location.catchments}
        covered = [i for i in ids if habitat and habitat.rows_for(i)]
        totals: dict[str, float] = {}
        for i in covered:
            for row in habitat.rows_for(i):
                totals[row["habitat"]] = totals.get(row["habitat"], 0) + row["area_ha"]
        whole = sum(areas.get(i, 0) for i in covered)
        rows = [{"habitat": name, "area_ha": area, "share": 100 * area / whole if whole else None} for name, area in totals.items()]
        return sorted(rows, key=lambda row: row["habitat"].lower()), Total(whole or None, len(covered), len(ids))

    # -------------------------------------------------------------------------
    #  Intervention Management
    # -------------------------------------------------------------------------

    def intervention_types(self) -> list[dict[str, Any]]:
        """The location's types of intervention, by number."""
        return self._numbered(INTERVENTION_TYPES)

    def unit_costs(self) -> list[dict[str, Any]]:
        """The cost of each type of intervention, by number."""
        return self._numbered(UNIT_COSTS)

    def intervention_summary(self) -> list[SummaryPart]:
        """The summary table's parts (e.g. Priority interventions), in the order of their lowest numbers."""
        parts: dict[str, list[dict[str, Any]]] = {}
        for row in self.intervention_types():
            parts.setdefault(row["summary_group"].strip(), []).append(row)
        return [SummaryPart(name, rows) for name, rows in parts.items()]

    def intervention_total(self) -> SummaryPart:
        """Every type of intervention, for the summary table's overall total."""
        return SummaryPart("Overall total", self.intervention_types())

    def intervention_waterbodies(self, number: int) -> list[tuple[str, list[dict[str, Any]]]]:
        """The waterbodies that need intervention type `number`, in its groups: (heading, rows), each by
        waterbody name. A group's heading is its line in the type's `groups` (empty if there's no such line)."""
        dataset = self.location.dataset(INTERVENTION_WATERBODIES)
        kind = next((row for row in self.intervention_types() if row["number"] == number), {})
        headings = [line.strip() for line in (kind.get("groups") or "").splitlines() if line.strip()]
        groups: dict[int, list[dict[str, Any]]] = {}
        for catchment in self.location.catchments:  # by name
            for row in dataset.rows_for(catchment["id"]) if dataset else []:
                if row["intervention"] == number:
                    groups.setdefault(row["group_number"], []).append({**row, "catchment_id": catchment["id"], "name": catchment["name"]})
        return [
            (headings[group - 1] if 0 < group <= len(headings) else "", rows)
            for group, rows in sorted(groups.items())
        ]

    def _numbered(self, table: str) -> list[dict[str, Any]]:
        """A location's rows in a table numbered 1, 2, 3, ..., in number order."""
        dataset = self.location.dataset(table)
        return sorted(dataset.rows_for(self.location.id) if dataset else [], key=lambda row: row["number"])

    def _one(self, table: str, key: Any) -> dict[str, Any]:
        """The row for a catchment (or the location) in a table with one row each, or an empty one."""
        dataset = self.location.dataset(table)
        rows = dataset.rows_for(key) if dataset else []
        return rows[0] if rows else {}


def measured(value: float | None) -> str:
    """A measured value or threshold as on the original's EA Data page: at least 2 decimal places (0.36, 89.69,
    100.00), more if given (0.057)."""
    if value is None:
        return ""
    text = f"{value:.2f}"
    return text if float(text) == value else re.sub(r"0+$", "", f"{value:.6f}")


def _rank(name: str, order: list[str]) -> tuple[int, str]:
    """Sorts names by their place in order, then any others alphabetically."""
    lowered = [o.lower() for o in order]
    key = name.strip().lower()
    return (lowered.index(key), "") if key in lowered else (len(order), key)
