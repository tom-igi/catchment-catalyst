"""Publish every location's dashboard at once, and record it in the publishes table.

Used by the publish command (__main__.py) and the admin page's Publish button,
so both do exactly the same thing.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from catalyst.db import Schema

from . import collect, site
from .collect import Location, PublishProblem

# Only one publish runs at a time, whether from the admin page or the command,
# because two at once would write the same folders. Each publish holds this
# PostgreSQL lock (any fixed number will do) until it ends; a second one waits
# for it, then publishes again.
LOCK = 7_316_001


def publish_all(engine: sa.Engine, schema: Schema, out_dir: Path, published_by: str | None = None) -> list[Location]:
    """Write every location's dashboard into out_dir, and record the publish. Returns the locations.

    Everything is collected before anything is written, so a problem with any
    location (a PublishProblem, or a database error) leaves every dashboard as
    it was, and nothing is recorded. published_by is the admin login of whoever
    pressed Publish, or None for the publish command.
    """
    with engine.begin() as conn:
        conn.execute(sa.select(sa.func.pg_advisory_xact_lock(LOCK)))
        locations = [collect.collect(conn, schema, row) for row in collect.locations(conn, schema)]
        if not locations:
            raise PublishProblem("There are no locations to publish yet. Add one first: see README.md, 'Publishing the dashboard'.")
        # Recorded before any page is written, so a database problem stops the publish first. If
        # writing the pages fails, the record is undone with the rest of the transaction.
        publishes = schema.metadata.tables["publishes"]
        conn.execute(publishes.insert().values(published_by=published_by))
        out_dir.mkdir(parents=True, exist_ok=True)
        for location in locations:
            site.write_location(location, out_dir)
        site.write_index([l.name for l in locations], [l.slug for l in locations], out_dir)
    return locations


def last_publish(conn: sa.Connection, schema: Schema) -> sa.Row | None:
    """The most recent publish, or None if there hasn't been one since publishes were first recorded."""
    publishes = schema.metadata.tables["publishes"]
    return conn.execute(sa.select(publishes).order_by(publishes.c.published_at.desc(), publishes.c.id.desc()).limit(1)).one_or_none()
