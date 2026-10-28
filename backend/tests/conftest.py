import os
import textwrap
import uuid

import pytest
import sqlalchemy as sa
import yaml

from catalyst.db.schema import Schema, build_schema


def make_schema(text: str) -> Schema:
    return build_schema(yaml.safe_load(textwrap.dedent(text)))


@pytest.fixture
def engine():
    """A brand new, empty database for each test, dropped afterwards."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    server_url = sa.make_url(url)
    admin = sa.create_engine(server_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = sa.create_engine(server_url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
