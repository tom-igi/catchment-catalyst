"""The data map: a plain-English web page of every table in the database.

Shown in the admin page at /admin/data-map. Optional and self-contained: see
README.md (including how to remove it).
"""

from .build import model, render

__all__ = ["model", "render"]
