"""The data map: a plain-English web page of every table in the database.

Optional and self-contained. See README.md (including how to remove it).
"""

from .build import SITE_DIR, build

__all__ = ["SITE_DIR", "build"]
