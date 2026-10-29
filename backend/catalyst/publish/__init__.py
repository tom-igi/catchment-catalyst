"""The publish step: turn the database into each location's dashboard.

The dashboard is plain web pages, written once by this step, so visitors never
reach the database. Running it again after the data changes updates the pages.

- collect.py   gathers a location's data from the database (no web pages)
- figures.py   works out what the pages show from it, e.g. ecological statuses (no web pages)
- site.py      writes that data out as pages, one per tab and catchment
- templates/   the pages' HTML
- static/      styles, scripts (the map and sortable tables) and the map library
"""
