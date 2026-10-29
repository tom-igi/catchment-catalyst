"""Write a location's dashboard as plain web pages, from the data collect.py gathered.

Each location gets its own folder, which has everything its pages need, so it
can be served at its own address:

    <location>/index.html                the location: a map and list of its catchments
    <location>/<catchment ID>/index.html  a catchment: its details and a table per dataset
    <location>/catchments.geojson         the outlines and rivers, for the maps
    <location>/assets/                    styles, scripts and the map library

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

HERE = Path(__file__).parent
ASSETS = HERE / "static"


def write_location(location: Location, out_dir: Path) -> Path:
    """Write the location's folder in out_dir, replacing any earlier version. Returns the folder."""
    final = out_dir / location.slug
    building = out_dir / f".building-{location.slug}"
    old = out_dir / f".old-{location.slug}"
    for leftover in (building, old):
        shutil.rmtree(leftover, ignore_errors=True)

    shutil.copytree(ASSETS, building / "assets")
    (building / "catchments.geojson").write_text(json.dumps(location.map, separators=(",", ":")), encoding="utf-8")
    env = _environment()
    published = _today()
    _write(building / "index.html", env.get_template("location.html").render(
        location=location, root="", published=published,
    ))
    for catchment in location.catchments:
        _write(building / catchment["id"] / "index.html", env.get_template("catchment.html").render(
            location=location, catchment=catchment, root="../", published=published,
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
    env.filters.update(show=_show, sort_value=_sort_value, number=_number)
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


def _today() -> str:
    today = datetime.date.today()
    return f"{today.day} {today:%B %Y}"
