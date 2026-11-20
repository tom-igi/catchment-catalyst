"""Input for AI: everything about one waterbody, and the waterbodies just upstream and downstream of it, as one text
file to give an AI chat, so it can write the waterbody's River Status Text (the River Status page's three texts).

The North Devon Biosphere has an AI write those texts, which someone then checks (the original Power BI dashboard had
a "Summary WB data for AI" export for it). This is chosen at the bottom of the admin page, one waterbody at a time
(Tom, 20 November 2026), and only reads the database.

What's in it:
- The waterbodies one step away, from the EA's links in Catchments: those that flow straight into it (upstream) and
  the one it flows straight into (downstream). Not the whole river: the lower Taw would have 30 or more. Further
  downstream is one line of names.
- The waterbody's current River Status Text, so the AI can improve it. The neighbours' are left out, so earlier
  wording isn't copied across.
- For each waterbody, a summary worked out by the dashboard's own code (latest status, failing elements, the EA's
  reasons, the risk tiles, its ranking), so the AI sees what the public sees, then its rows in every data table about
  catchments. A new table is in it with nothing to write here.

Left out: Postcodes (no use to an AI), map shapes, row IDs and coordinates (grid references are kept), and tables about
a whole location (e.g. Location Text), which aren't about the waterbody (Intervention Types only names the
interventions). EA Classifications is a grid, an item per row and a year per column, as it's most of the data
otherwise.

It's plain text laid out in Markdown (headings, tables), which any AI chat reads, pasted in or attached, and which can
be checked in Notepad.
"""

from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from geoalchemy2 import Geometry

from catalyst.db import Schema
from catalyst.db.schema import LOCATION_COLUMN, key_column
from catalyst.publish.collect import Dataset, Location, collect
from catalyst.publish.collect import _label as label
from catalyst.publish.figures import (
    CLASSIFICATIONS, ECOLOGICAL, INTERVENTION_TYPES, INTERVENTION_WATERBODIES, RISK_NAMES, RIVER_TEXT, SCORING_ITEMS,
    Figures,
)

CHOSEN, UPSTREAM, DOWNSTREAM = "chosen", "upstream", "downstream"
POSTCODES = "postcodes"
# The data tables, in the order they're in the file: the EA's statuses first, then the figures behind the risk
# tiles, land use, sewerage, obstacles and interventions. Any other table about catchments goes after them.
ORDER = [
    "waterbody_figures",
    CLASSIFICATIONS, "ea_scores", "ea_thresholds", "ea_rnags",
    "sewage_overflow_pressure", "esme_risk_levels", "livestock_pressure",
    "habitat_land_use", "livestock",
    "storm_overflows", "sewerage_improvements", "phosphate_sources", "phosphate_point_diffuse",
    "river_obstacles", INTERVENTION_WATERBODIES,
]
LEFT_OUT_TABLES = {POSTCODES, RIVER_TEXT}  # River Status Text is the text being written: see "What the text is for"
LEFT_OUT_COLUMNS = {"id", "latitude", "longitude", "easting", "northing"}  # row IDs, and places as coordinates
SORT = {"storm_overflows": ("site_name", "year")}  # otherwise by the table's primary key
# The River Status page's texts: column, and its heading on the page.
TEXTS = [
    ("why_failing", "Why is the river failing?"),
    ("happening_now", "What is happening now?"),
    ("intervention_hypothesis", "Intervention hypothesis"),
]
CONFIDENCE = "hypothesis_confidence"
# The EA's classification levels, broadest first: the grid's rows go in this order.
LEVELS = ["Overall Waterbody", "Ecological, chemical or quantitative status", "Component", "Element", "Sub Element"]
MOST_STEPS = 50  # further downstream: stops after this many, in case the EA's links ever go round in a circle


class NotFound(Exception):
    """There's no waterbody with that ID."""


@dataclass
class Waterbody:
    id: str
    name: str | None  # None if it isn't in the Catchments table (e.g. an estuary that isn't imported)
    role: str  # CHOSEN, UPSTREAM or DOWNSTREAM

    @property
    def called(self) -> str:
        return self.name or self.id


@dataclass
class File:
    name: str  # e.g. "AI input - Lower Little River Dart - 2026-11-20.txt"
    text: str


# --- The admin page's list of waterbodies ---------------------------------------------

def choices(conn: sa.Connection, schema: Schema) -> list[dict[str, str]]:
    """Every waterbody, by name, with what else its file has, e.g. 'Upstream: Hole Water. Downstream: Mole (Taw to
    Bray).'"""
    table = schema.metadata.tables["catchments"]
    rows = conn.execute(
        sa.select(table.c.id, table.c.name, table.c.upstream_ids, table.c.downstream_ids).order_by(table.c.name, table.c.id)
    ).all()
    names = {row.id: row.name for row in rows}

    def named(ids: list[str] | None) -> str:
        return ", ".join(sorted((names.get(i) or f"{i} (no data)" for i in ids or []), key=str.lower)) or "none"

    return [
        {"id": row.id, "name": row.name or row.id,
         "includes": f"Upstream: {named(row.upstream_ids)}. Downstream: {named(row.downstream_ids)}."}
        for row in rows
    ]


# --- The file -------------------------------------------------------------------------------

def write(conn: sa.Connection, schema: Schema, catchment_id: str, now: datetime.datetime) -> File:
    catchments = schema.metadata.tables["catchments"]
    chosen = conn.execute(sa.select(catchments.c.id, catchments.c.upstream_ids, catchments.c.downstream_ids)
                          .where(catchments.c.id == catchment_id)).first()
    if chosen is None:
        raise NotFound(catchment_id)
    ids = [chosen.id, *(chosen.upstream_ids or []), *(chosen.downstream_ids or [])]
    names = dict(conn.execute(sa.select(catchments.c.id, catchments.c.name).where(catchments.c.id.in_(ids))).all())
    waterbodies = (
        [Waterbody(chosen.id, names.get(chosen.id), CHOSEN)]
        + sorted((Waterbody(i, names.get(i), UPSTREAM) for i in chosen.upstream_ids or []), key=lambda w: w.called.lower())
        + [Waterbody(i, names.get(i), DOWNSTREAM) for i in chosen.downstream_ids or []]
    )
    place = _location(conn, schema, catchment_id)
    # The dashboard's own data and figures, for just these waterbodies (and the location's interventions' names).
    data = collect(conn, schema, SimpleNamespace(
        name=place.name if place else "", id=place.id if place else None,
        catchment_ids=[w.id for w in waterbodies if w.name is not None],
    ))
    page = _Page(schema, data, Figures(data), waterbodies, place, _rivers(conn, schema, place))
    text = page.write(now, _further_downstream(conn, schema, chosen.downstream_ids or []))
    return File(f"AI input - {_file_safe(page.chosen.called)} - {now:%Y-%m-%d}.txt", text)


@dataclass
class _Page:
    schema: Schema
    data: Location
    figures: Figures
    waterbodies: list[Waterbody]
    place: Any  # the chosen waterbody's row in Locations, or None
    rivers: int | None  # rivers in the location, for "8 of 92"

    @property
    def chosen(self) -> Waterbody:
        return self.waterbodies[0]

    def write(self, now: datetime.datetime, further: list[str]) -> str:
        parts = [
            f"# Input for AI: {self.chosen.called}",
            *self._about(now),
            *self._waterbodies(further),
            *self._what_to_write(),
            *self._what_the_tables_hold(),
        ]
        for number, waterbody in enumerate(self.waterbodies, 1):
            parts += self._waterbody(number, waterbody)
        return "\n\n".join(parts) + "\n"

    # --- The introduction ---------------------------------------------------------------------

    def _about(self, now: datetime.datetime) -> list[str]:
        where = f" in {self.place.name}" if self.place else ""
        up = sum(w.role == UPSTREAM for w in self.waterbodies)
        down = sum(w.role == DOWNSTREAM for w in self.waterbodies)
        return [
            "## About this file",
            f"This file is the data for one waterbody{where}: **{self.chosen.called}** (the Environment Agency's ID "
            f"{self.chosen.id}). It's for writing that waterbody's River Status Text: see \"What the text is for\" below.",
            f"It also has the data for the waterbodies next to it on the river, for background only: {_count(up, 'waterbody', 'waterbodies')} "
            f"that flow straight into it (upstream) and {_count(down, 'waterbody', 'waterbodies')} it flows straight into (downstream). "
            "Use them to see where its problems may come from, or where they go, but write only about "
            f"{self.chosen.called}.",
            f"Downloaded from the Catchment Catalyst admin page on {now.day} {now:%B %Y} at {now:%H:%M}. Each table "
            "is described under \"What the tables hold\", then each waterbody has a section of its own, "
            f"{self.chosen.called} first. An empty cell means there's no figure.",
        ]

    def _waterbodies(self, further: list[str]) -> list[str]:
        roles = {
            CHOSEN: "The waterbody the text is for",
            UPSTREAM: f"Upstream: flows straight into {self.chosen.called}",
            DOWNSTREAM: f"Downstream: {self.chosen.called} flows straight into it",
        }
        rows = [
            (w.called, w.id, roles[w.role] + ("" if w.name else ". It isn't in Catchment Catalyst, so there's no data for it here"))
            for w in self.waterbodies
        ]
        parts = ["## The waterbodies in this file", _table(["Waterbody", "EA ID", "In this file because"], rows)]
        downstream = [w for w in self.waterbodies if w.role == DOWNSTREAM]
        if further and downstream:
            parts.append(f"After {downstream[0].called}, the river goes on to (names only, not in this file): "
                         f"{' → '.join(further)}.")
        return parts

    def _what_to_write(self) -> list[str]:
        table = self.schema.metadata.tables.get(RIVER_TEXT)
        if table is None:
            return []
        parts = [
            "## What the text is for",
            "Each waterbody's River Status page on the dashboard has these texts:",
            "\n".join(
                [f"- **{heading}**" for column, heading in TEXTS if column in table.c]
                + (["- How confident the hypothesis is, shown after its heading, e.g. Low, Medium, Med-High, High"]
                   if CONFIDENCE in table.c else [])
            ),
            "Each text can have paragraphs (a blank line between them), bullets (a line starting with - ) and "
            "**bold** (two stars each side).",
            f"### The current text for {self.chosen.called}",
        ]
        current = self.figures.river_text(self.chosen.id)
        if not any(current.get(column) for column, _ in TEXTS):
            return parts + ["There's no text for it yet."]
        for column, heading in TEXTS:
            if column in table.c:
                if column == "intervention_hypothesis" and current.get(CONFIDENCE):
                    heading = f"{heading} (confidence: {current[CONFIDENCE]})"
                parts += [f"**{heading}**", _quoted(current.get(column) or "(empty)")]
        return parts

    def _what_the_tables_hold(self) -> list[str]:
        catchments = self.schema.metadata.tables["catchments"]
        parts = [
            "## What the tables hold",
            "### Summary, as on the dashboard",
            "Worked out from the tables below, as the dashboard does: the latest ecological status; the failing elements "
            "(Fish, Invertebrates, Macrophytes, Phytobenthos, Ammonia, Dissolved oxygen, Phosphate, pH, Specific "
            "pollutants or Temperature at Moderate, Poor or Bad in the EA's latest classification); the EA's reasons "
            "for not achieving good, in its latest cycle; the risk tiles (Very Low to Very High); and the ranking.",
            *_info(self.data.dataset("risk_levels"), "The risk tiles"),
            *_info(self.data.dataset("catchment_rankings"), "The ranking"),
            "### Catchment details",
            "The Environment Agency's details of the waterbody and its catchment.",  # not Catchments' description: it's about the database
            _columns([c for c in catchments.columns if c.name in _detail_columns(catchments)]),
        ]
        for dataset in self._datasets():
            table = self.schema.metadata.tables[dataset.table]
            parts += [f"### {dataset.title}", *([table.comment] if table.comment else [])]
            if dataset.table == CLASSIFICATIONS:
                parts.append(
                    "Here as a grid: a row for each item the EA classifies, a column for each classification year, "
                    "each the item's status that year (where a year was classified in more than one cycle, the latest "
                    "cycle's), and the certainty of its latest status."
                )
            parts += _info(dataset, "On the dashboard's \"i\" button")
            parts.append(_columns([table.c[c.name] for c in self._shown(dataset)]))
        return [part for part in parts if part]

    # --- Each waterbody ---------------------------------------------------------------------------

    def _waterbody(self, number: int, waterbody: Waterbody) -> list[str]:
        heading = {
            CHOSEN: "the waterbody the text is for",
            UPSTREAM: f"upstream, flows straight into {self.chosen.called}",
            DOWNSTREAM: f"downstream, {self.chosen.called} flows straight into it",
        }[waterbody.role]
        parts = [f"## {number}. {waterbody.called}: {heading}"]
        if waterbody.name is None:
            return parts + [f"{waterbody.id} isn't in Catchment Catalyst, so there's no data for it here."]
        catchment = next(c for c in self.data.catchments if c["id"] == waterbody.id)
        details = _detail_columns(self.schema.metadata.tables["catchments"])
        parts += [
            "### Summary, as on the dashboard",
            self._summary(waterbody.id),
            "### Catchment details",
            "\n".join(f"- {label(c)}: {_cell(catchment[c])}" for c in details if catchment.get(c) is not None),
        ]
        for dataset in self._datasets():
            parts += [f"### {dataset.title}", self._rows(dataset, waterbody.id)]
        return parts

    def _summary(self, catchment_id: str) -> str:
        figures = self.figures
        by_year = figures.ecological.get(catchment_id, {})
        status = f"{by_year[max(by_year)]} ({max(by_year)})" if by_year else "none"
        ea_years = [year for item, year in figures.results.get(catchment_id, {}) if item == ECOLOGICAL]
        failing = ", ".join(figures.failing_elements(catchment_id)) or "none"
        reasons = "; ".join(figures.reasons(catchment_id)) or "none given"
        risks = "; ".join(f"{name}: {level or 'no figure'}" for name, level in figures.risks(catchment_id, list(RISK_NAMES)))
        ranking = figures.ranking(catchment_id)
        lines = [
            f"- Ecological status: {status}",
            f"- Failing elements ({max(ea_years)}): {failing}" if ea_years else "- Failing elements: no classification from the EA",
            f"- Reasons for not achieving good: {reasons}",
            f"- Risk levels: {risks}",
            (f"- Ranking: {ranking}" + (f" of {self.rivers} rivers" if self.rivers else "")) if ranking else "- Ranking: none",
        ]
        return "\n".join(lines)

    def _rows(self, dataset: Dataset, catchment_id: str) -> str:
        rows = dataset.rows_for(catchment_id)
        if not rows:
            return "None."
        if dataset.table == CLASSIFICATIONS:
            return _classifications(rows)
        columns = self._shown(dataset)
        if dataset.table in SORT:
            rows = sorted(rows, key=lambda row: tuple((row[c] is None, row[c] or "") for c in SORT[dataset.table]))
        names = self._intervention_names() if dataset.table == INTERVENTION_WATERBODIES else {}
        return _table(
            [c.label for c in columns],
            [[f"{row[c.name]} ({names[row[c.name]]})" if c.name == "intervention" and row[c.name] in names else row[c.name]
              for c in columns] for row in rows],
        )

    # --- Which tables and columns -------------------------------------------------------------------

    def _datasets(self) -> list[Dataset]:
        """The data tables about catchments, in ORDER, then any others."""
        found = [
            d for d in self.data.datasets
            if d.table in self.schema.metadata.tables and d.table not in LEFT_OUT_TABLES
            and key_column(self.schema.metadata.tables[d.table]) != LOCATION_COLUMN
        ]
        return sorted(found, key=lambda d: ORDER.index(d.table) if d.table in ORDER else len(ORDER))

    def _shown(self, dataset: Dataset) -> list:
        table = self.schema.metadata.tables[dataset.table]
        if dataset.table == CLASSIFICATIONS:
            return [c for c in dataset.columns if c.name in ("item", "level", "year", "status", "certainty")]
        return [
            c for c in dataset.columns
            if c.name not in LEFT_OUT_COLUMNS and not isinstance(table.c[c.name].type, (Geometry, sa.LargeBinary))
        ]

    def _intervention_names(self) -> dict[int, str]:
        types = self.data.dataset(INTERVENTION_TYPES)
        rows = types.rows_for(self.place.id) if types and self.place else []
        return {row["number"]: row["name"] for row in rows if row.get("name")}


# --- Helpers ------------------------------------------------------------------------------------

def _location(conn: sa.Connection, schema: Schema, catchment_id: str) -> Any:
    """The first location the waterbody is in, or None."""
    table = schema.metadata.tables["locations"]
    return conn.execute(
        sa.select(table).where(table.c.catchment_ids.any(catchment_id)).order_by(table.c.id).limit(1)
    ).first()


def _rivers(conn: sa.Connection, schema: Schema, place: Any) -> int | None:
    """How many rivers the location has, as the dashboard counts them for its ranking (e.g. 68/92)."""
    if place is None:
        return None
    table = schema.metadata.tables["catchments"]
    return conn.scalar(sa.select(sa.func.count()).where(
        table.c.id.in_(list(place.catchment_ids)), table.c.waterbody_type == "River"
    )) or None


def _further_downstream(conn: sa.Connection, schema: Schema, downstream: list[str]) -> list[str]:
    """Where the river goes after the waterbody downstream, by name, each flowing into the next. Stops where a
    waterbody flows into more than one (or none), or at one that isn't imported, shown by its ID."""
    table = schema.metadata.tables["catchments"]
    route: list[str] = []
    seen = set(downstream)
    current = downstream[0] if len(downstream) == 1 else None
    while current and len(route) < MOST_STEPS:
        row = conn.execute(sa.select(table.c.downstream_ids).where(table.c.id == current)).first()
        following = (row.downstream_ids or []) if row else []
        if len(following) != 1 or following[0] in seen:
            break
        current = following[0]
        seen.add(current)
        name = conn.scalar(sa.select(table.c.name).where(table.c.id == current))
        route.append(name or f"{current} (not in Catchment Catalyst)")
    return route


def _detail_columns(table: sa.Table) -> list[str]:
    """Catchments' columns in Catchment details: not its ID and name (in the heading), shapes, links up and
    downstream (in the waterbodies table) or when it was imported."""
    return [
        c.name for c in table.columns
        if c.name not in ("id", "name", "upstream_ids", "downstream_ids", "imported_at") and not isinstance(c.type, Geometry)
    ]


def _info(dataset: Dataset | None, lead: str) -> list[str]:
    """A table's or panel's "i" button text, if it has one."""
    text = (dataset.info or {}).get("info_text") if dataset else None
    return [f"{lead}: {' '.join(text.split())}"] if text and text.strip() else []


def _columns(columns: list[sa.Column]) -> str:
    """Each column's name and what it holds."""
    lines = [f"- {label(c.name)}" + (f": {' '.join(c.comment.split())}" if c.comment else "") for c in columns]
    return "Columns:\n" + "\n".join(lines) if lines else ""


def _classifications(rows: list[dict[str, Any]]) -> str:
    """EA Classifications as a grid: a row per item, a column per year, each the latest cycle's status."""
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["item"], row["year"])
        if row["status"] and (key not in latest or (row["cycle"] or 0) > (latest[key]["cycle"] or 0)):
            latest[key] = row
    years = sorted({year for _, year in latest})
    items: dict[str, dict[int, dict[str, Any]]] = {}
    for (item, year), row in latest.items():
        items.setdefault(item, {})[year] = row

    def order(item: str) -> tuple:
        level = next(iter(items[item].values()))["level"]
        return (
            LEVELS.index(level) if level in LEVELS else len(LEVELS),
            SCORING_ITEMS.index(item) if item in SCORING_ITEMS else len(SCORING_ITEMS),
            item.lower(),
        )

    table = []
    for item in sorted(items, key=order):
        by_year = items[item]
        newest = by_year[max(by_year)]
        table.append([item, newest["level"], *(by_year[y]["status"] if y in by_year else None for y in years), newest["certainty"]])
    return _table(["Item", "Level", *map(str, years), "Certainty (latest)"], table)


def _table(headings: list[str], rows: list) -> str:
    lines = [
        "| " + " | ".join(_escape(h) for h in headings) + " |",
        "|" + "---|" * len(headings),
    ]
    lines += ["| " + " | ".join(_escape(_cell(value)) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_cell(v) for v in value)
    if isinstance(value, datetime.datetime):
        return f"{value:%Y-%m-%d %H:%M}"
    if isinstance(value, datetime.date):
        return f"{value:%Y-%m-%d}"
    return str(value)


def _number(value: float) -> str:
    """A number rounded for reading: 2 decimal places from 10 up (7414.54), 3 significant figures below (9.6,
    0.0491), no trailing zeros."""
    if not math.isfinite(value):
        return ""
    if value == int(value):
        return str(int(value))
    places = 2 if abs(value) >= 10 else max(2, 2 - math.floor(math.log10(abs(value))))
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def _escape(text: str) -> str:
    """A table cell's text on one line: lines joined with ' / ', and | escaped."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " / ".join(lines).replace("|", "\\|")


def _quoted(text: str) -> str:
    """Hand-written text exactly as it is, fenced so its own headings and bullets can't be mistaken for the file's."""
    fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{fence}text\n{text.strip()}\n{fence}"


def _count(number: int, one: str, many: str) -> str:
    return f"{'no' if number == 0 else number} {one if number == 1 else many}"


def _file_safe(name: str) -> str:
    """A name that can be part of a file name on Windows: no \\ / : * ? \" < > |."""
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "waterbody"
