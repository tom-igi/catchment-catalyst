"""Write a location's dashboard as plain web pages, from the data collect.py gathered.

The pages follow the original (Reference/ReferenceImages): four views, chosen
with the cards across the top of every page (VIEWS). The Waterbody Dashboard
has a tab per page and a page per catchment; the Catchment Dashboard shows the
whole location, or one of its operational catchments; Intervention Management
and Catchment Insights are placeholders for now. Each location gets its own
folder, which has everything its pages need, so it can be served at its own
address:

    <location>/index.html                       the front page: the Overview tab (switched off for now:
                                                see SHOW_OVERVIEW), or River Status before a catchment is chosen
    <location>/<tab>/index.html                 a Waterbody Dashboard tab, before a catchment is chosen
    <location>/<tab>/<catchment ID>/index.html  that tab for one catchment
    <location>/catchment-dashboard/index.html   the Catchment Dashboard, for the whole location
    <location>/catchment-dashboard/<area>/      ... for one operational (or management) catchment
    <location>/intervention-management/         Intervention Management
    <location>/catchment-insights/              Catchment Insights
    <location>/catchments.geojson               the outlines, rivers and ecological statuses, for the maps
    <location>/assets/                          styles, scripts, pictures and the map library

where <tab> is river-status, ea-data, land-use or sewerage. Clicking the map
picks a catchment and stays on the same tab, as in the original.

The folder is built next to the old one and swapped in at the end, so a
half-written dashboard is never served.

Every link to a file in assets/ (and to catchments.geojson) ends with
?v=<version>, a fingerprint of those files. Browsers keep copies of such
files, so without it a visitor could be shown an old stylesheet or map after a
publish. The version only changes when one of the files does, so browsers can
still keep them between publishes.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .collect import Location, PublishProblem
from .figures import Figures, measured
from .text import boxes, formatted

HERE = Path(__file__).parent
ASSETS = HERE / "static"
# Text kept in files rather than the database, for now: a folder per location (by its web address, e.g. north-devon).
CONTENT = HERE / "content"
# The Overview tab is switched off for now (29 October 2026): the front page is
# River Status instead. Set this to True to bring it back.
SHOW_OVERVIEW = False
# The Waterbody Dashboard's tabs: folder name -> the tab's name. Each has a template of the same name.
TABS = {
    "river-status": "River Status",
    "ea-data": "EA Data",
    "land-use": "Land Use Data",
    "sewerage": "Sewerage Data",
}
# The four views, as the cards across the top of every page: (folder, name, what it's for, picture in assets/cards/).
VIEWS = [
    ("river-status", "Waterbody Dashboard",
     "Explore the evidence and analysis for individual river water bodies within this catchment.", "waterbody.jpg"),
    ("catchment-dashboard", "Catchment Dashboard",
     "Understand ecological condition, environmental pressures and recovery priorities across this catchment.", "catchment.jpg"),
    ("intervention-management", "Intervention Management",
     "Identify and track the programmes, projects and investments needed to improve river health.", "interventions.jpg"),
    ("catchment-insights", "Catchment Insights",
     "Explore key questions about agriculture, wastewater, fish and river recovery for the catchment.", "insights.jpg"),
]
# The focus areas on Intervention Management and Catchment Insights, as their buttons. Catchment Insights'
# are "under development" for now.
INTERVENTION_AREAS = [
    "Critical Path", "Unit Cost of Interventions", "Intervention Summary", "Interventions Detail", "Community Action",
]
INSIGHT_AREAS = [
    "State of the Catchment", "Agriculture", "Wastewater", "Fish",
    "Intervention Strategy", "Funding & Delivery", "Community Involvement", "Other",
]


def write_location(location: Location, out_dir: Path) -> Path:
    """Write the location's folder in out_dir, replacing any earlier version. Returns the folder."""
    final = out_dir / location.slug
    building = out_dir / f".building-{location.slug}"
    old = out_dir / f".old-{location.slug}"
    for leftover in (building, old):
        shutil.rmtree(leftover, ignore_errors=True)

    insights = catchment_insights(location.slug)  # before anything is written, as a mistake in it stops the publish
    figures = Figures(location)
    shutil.copytree(ASSETS, building / "assets")
    (building / "catchments.geojson").write_text(json.dumps(_map(location, figures), separators=(",", ":")), encoding="utf-8")
    env = _environment()
    shared = {
        "location": location, "figures": figures, "text": figures.location_text(), "tabs": TABS, "views": VIEWS,
        "show_overview": SHOW_OVERVIEW, "published": _today(), "version": version(building),
    }
    waterbody = {**shared, "view": "river-status"}
    front, tab = ("overview.html", "") if SHOW_OVERVIEW else ("river-status.html", "river-status")
    _write(building / "index.html", env.get_template(front).render(**waterbody, tab=tab, catchment=None, root=""))
    for tab in TABS:
        template = env.get_template(f"{tab}.html")
        _write(building / tab / "index.html", template.render(**waterbody, tab=tab, catchment=None, root="../"))
        for catchment in location.catchments:
            _write(building / tab / catchment["id"] / "index.html", template.render(
                **waterbody, tab=tab, catchment=catchment, root="../../",
            ))

    # The Catchment Dashboard: the whole location, then each of its areas.
    template = env.get_template("catchment-dashboard.html")
    areas = figures.areas()
    everything = [c["id"] for c in location.catchments]
    whole = next((a for a in areas if not a.slug), None)
    _write(building / "catchment-dashboard" / "index.html", template.render(
        **shared, view="catchment-dashboard", tab="", catchment=None, root="../",
        areas=areas, area=whole, ids=everything,
    ))
    for area in areas:
        if area.slug:
            _write(building / "catchment-dashboard" / area.slug / "index.html", template.render(
                **shared, view="catchment-dashboard", tab="", catchment=None, root="../../",
                areas=areas, area=area, ids=area.catchment_ids,
            ))

    for view, focus_areas in (("intervention-management", INTERVENTION_AREAS), ("catchment-insights", INSIGHT_AREAS)):
        _write(building / view / "index.html", env.get_template(f"{view}.html").render(
            **shared, view=view, tab="", catchment=None, root="../", focus_areas=focus_areas, insights=insights,
        ))

    if final.exists():
        final.rename(old)
    building.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    return final


def catchment_insights(location_slug: str) -> dict[str, dict]:
    """A location's Catchment Insights, from content/<its web address>/catchment-insights.yaml: each focus
    area's title and groups of questions, by the focus area's name. Empty if the location has no such file."""
    path = CONTENT / location_slug / "catchment-insights.yaml"
    if not path.is_file():
        return {}
    where = path.relative_to(HERE) if path.is_relative_to(HERE) else path
    try:
        areas = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise PublishProblem(f"{where} isn't valid YAML: {e}") from None
    unknown = [name for name in areas if name not in INSIGHT_AREAS]
    if unknown:
        raise PublishProblem(
            f"{where} has focus areas that aren't on Catchment Insights: {', '.join(map(str, unknown))}. "
            f"They're named as on the buttons: {', '.join(INSIGHT_AREAS)}."
        )
    for name, area in areas.items():
        for group in (area or {}).get("groups") or []:
            if not all(isinstance(item, dict) and item.get("question") for item in group.get("questions") or []):
                raise PublishProblem(f"{where}: every question in {name} needs a 'question:' line.")
    return areas


def write_index(names: list[str], slugs: list[str], out_dir: Path) -> Path:
    """A page listing every location, for looking at them before they each get their own address."""
    path = out_dir / "index.html"
    _write(path, _environment().get_template("index.html").render(locations=list(zip(names, slugs)), root=""))
    return path


def version(folder: Path) -> str:
    """A fingerprint of a location folder's assets and map file, added to their links so browsers fetch them again when they change."""
    digest = hashlib.sha256()
    files = sorted(p for p in (folder / "assets").rglob("*") if p.is_file()) + [folder / "catchments.geojson"]
    for path in files:
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:10]


def _map(location: Location, figures: Figures) -> dict:
    """The location's map, with each catchment's ecological status for colouring it."""
    features = [
        {**f, "properties": {**f["properties"], "status": figures.status(f["properties"]["id"])}}
        for f in location.map["features"]
    ]
    return {**location.map, "features": features}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,  # a typo in a template stops the publish rather than leaving a gap
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        show=_show, sort_value=_sort_value, number=_number, hours=_hours, status_class=_status_class,
        formatted=formatted, risk_class=_risk_class, anchor=_anchor, measured=measured,
        boxes=boxes, pounds=_pounds, about_pounds=_about_pounds,
    )
    return env


def _show(value: Any) -> str:
    """A value as shown in a table."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, datetime.datetime):
        return f"{value:%d %b %Y}"
    if isinstance(value, datetime.date):
        return f"{value.day} {value:%b %Y}"
    return str(value)


def _sort_value(value: Any) -> str:
    """What the table-sorting script sorts a cell by."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def _number(value: float | int | None, decimals: int | None = None) -> str:
    if value is None:
        return ""
    if decimals is not None:
        return f"{value:,.{decimals}f}"
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


def _pounds(value: float | None) -> str:
    """An amount of money as on Intervention Management: millions as £120m or £2.04m, less as £54,000."""
    if value is None:
        return ""
    if abs(value) >= 1_000_000:
        return "£" + f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "m"
    return f"£{value:,.0f}"


def _about_pounds(value: float) -> str:
    """A total on Intervention Management, in millions to one decimal place: c.£384.7m."""
    return f"c.£{value / 1_000_000:.1f}m"


def _hours(value: float | None) -> str:
    """Hours as a whole number, with halves rounded up as on the original (1462.5 -> 1463)."""
    if value is None:
        return ""
    return str(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _status_class(status: str | None) -> str:
    """The CSS class that colours a status, e.g. 'Supports Good' -> 'status-supports-good'."""
    return "status-" + "-".join(status.lower().split()) if status else "status-none"


def _risk_class(level: str | None) -> str:
    """The CSS class that colours a risk level, e.g. 'Very High' -> 'risk-very-high'."""
    return "risk-" + "-".join(level.lower().split()) if level and level.strip() else "risk-none"


def _anchor(text: str) -> str:
    """A name as a link within a page, e.g. 'Funding & Delivery' -> 'funding-delivery'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _today() -> str:
    today = datetime.date.today()
    return f"{today.day} {today:%B %Y}"
