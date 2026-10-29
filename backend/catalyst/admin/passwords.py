"""Who can log in: one name and password per person, from the ADMIN_USERS setting.

    ADMIN_USERS=tom:scrypt.<salt>.<hash>,alex:scrypt.<salt>.<hash>

Only a hash of each password is kept, never the password itself. To make
someone's entry (it asks for their password):

    docker compose run --rm admin hash-password <name>
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
HASH_RE = re.compile(r"^scrypt\.[0-9a-f]{32}\.[0-9a-f]{64}$")
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSWORD_LENGTH = 12
ENTRY_HELP = "Make an entry with: docker compose run --rm admin hash-password <name>"

# Checked when the name isn't known, so a wrong name takes as long as a wrong password.
_NOBODY = "scrypt." + "0" * 32 + "." + "0" * 64


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt.{salt.hex()}.{_scrypt(password, salt).hex()}"


def check_password(password: str, stored: str) -> bool:
    _, salt, digest = stored.split(".")
    return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)), bytes.fromhex(digest))


def log_in(users: dict[str, str], name: str, password: str) -> str | None:
    """The person's name if the password is theirs, otherwise None."""
    name = name.strip().lower()
    right = check_password(password, users.get(name, _NOBODY))
    return name if right and name in users else None


def parse_users(text: str) -> dict[str, str]:
    """Read ADMIN_USERS into {name: password hash}. Raises ValueError if it's wrong."""
    users: dict[str, str] = {}
    for number, entry in enumerate((e.strip() for e in text.split(",") if e.strip()), start=1):
        name, _, stored = entry.partition(":")
        name = name.strip().lower()
        if not NAME_RE.match(name) or not HASH_RE.match(stored.strip()):
            # Don't repeat the entry itself: it could hold a password typed by mistake.
            raise ValueError(f"ADMIN_USERS: entry {number} should look like name:scrypt.<salt>.<hash>. {ENTRY_HELP}")
        if name in users:
            raise ValueError(f"ADMIN_USERS lists {name} more than once.")
        users[name] = stored.strip()
    if not users:
        raise ValueError(f"ADMIN_USERS doesn't list anyone. {ENTRY_HELP}")
    return users


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)
