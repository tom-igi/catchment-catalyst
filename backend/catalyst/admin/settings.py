"""The admin page's settings, from environment variables (set in docker-compose*.yml and .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .passwords import parse_users

REQUIRED = ("DATABASE_URL", "ADMIN_USERS", "ADMIN_SECRET_KEY")


class SettingsError(Exception):
    """A setting is missing or wrong."""


@dataclass
class Settings:
    database_url: str
    users: dict[str, str]  # name -> password hash
    secret_key: str  # signs the login cookie
    raw_files_dir: Path  # where uploaded files are kept
    https_only: bool = False  # send the login cookie over HTTPS only

    @classmethod
    def from_environment(cls) -> Settings:
        env = os.environ
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise SettingsError(f"Not set: {', '.join(missing)}. See .env.example, or .env.prod.example on the live server.")
        try:
            users = parse_users(env["ADMIN_USERS"])
        except ValueError as e:
            raise SettingsError(str(e)) from None
        return cls(
            database_url=env["DATABASE_URL"],
            users=users,
            secret_key=env["ADMIN_SECRET_KEY"],
            raw_files_dir=Path(env.get("RAW_FILES_DIR", "imports/raw")),
            https_only=env.get("ADMIN_HTTPS_ONLY", "").lower() == "true",
        )
