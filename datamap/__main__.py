"""Rebuild the data map page on its own: python -m datamap"""

from pathlib import Path

from . import build

print(f"Data map updated: {build().relative_to(Path.cwd())}")
