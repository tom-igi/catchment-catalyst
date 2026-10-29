"""Write a location's dashboard as plain web pages, from the data collect.py gathered.

The pages follow the tabs of the original dashboard (Reference/ReferenceImages).
Each location gets its own folder, which has everything its pages need, so it
can be served at its own address:

    <location>/index.html                      the Overview tab
    <location>/<tab>/index.html                another tab, before a catchment is chosen
    <location>/<tab>/<catchment ID>/index.html  that tab for one catchment
    <location>/catchments.geojson               the outlines, rivers and ecological statuses, for the maps
    <location>/assets/                          styles, scripts and the map library

where <tab> is river-status, ea-data, land-use or sewerage. Clicking the map
picks a catchment and stays on the same tab, as in the original.

The folder is built next to the old one and swapped in at the end, so a
half-written dashboard is never served.
"""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .collect import Location
from .figures import Figures

HERE = Path(__file__).parent
ASSETS = HERE / "static"
# Folder name -> the tab's name. Each has a template of the same name.
TABS = {
    "river-status": "River Status",
    "ea-data": "EA Data",
    "land-use": "Land Use Data",
    "sewerage": "Sewerage Data",
}


def write_location(location: Location, out_dir: Path) -> Path:
    """Write the location's folder in out_dir, replacing any earlier version. Returns the folder."""
    final = out_dir / location.slug
    building = out_dir / f".building-{location.slug}"
    old = out_dir / f".old-{location.slug}"
    for leftover in (building, old):
        shutil.rmtree(leftover, ignore_errors=True)

    figures = Figures(location)
    shutil.copytree(ASSETS, building / "assets")
    (building / "catchments.geojson").write_text(json.dumps(_map(location, figures), separators=(",", ":")), encoding="utf-8")
    env = _environment()
    shared = {"location": location, "figures": figures, "tabs": TABS, "published": _today()}
    _write(building / "index.html", env.get_template("overview.html").render(
        **shared, tab="", catchment=None, root="",
    ))
    for tab in TABS:
        template = env.get_template(f"{tab}.html")
        _write(building / tab / "index.html", template.render(**shared, tab=tab, catchment=None, root="../"))
        for catchment in location.catchments:
            _write(building / tab / catchment["id"] / "index.html", template.render(
                **shared, tab=tab, catchment=catchment, root="../../",
            ))

    if final.exists():
        final.rename(old)
    building.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    return final


def write_index(names: list[str], slugs: list[str], out_dir: Path) -> Path:
    """A page listing every location, for looking at them before they each get their own address."""
    path = out_dir / "index.html"
    _write(path, _environment().get_template("index.html").render(locations=list(zip(names, slugs)), root=""))
    return path


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
    env.filters.update(show=_show, sort_value=_sort_value, number=_number, status_class=_status_class)
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


def _status_class(status: str | None) -> str:
    """The CSS class that colours a status, e.g. 'Supports Good' -> 'status-supports-good'."""
    return "status-" + "-".join(status.lower().split()) if status else "status-none"


def _today() -> str:
    today = datetime.date.today()
    return f"{today.day} {today:%B %Y}"
