"""Who can log in: one name and password per person, from the ADMIN_USERS setting.

    ADMIN_USERS=tom:scrypt.<salt>.<hash>,alex:scrypt.<salt>.<hash>

Only a hash of each password is kept, never the password itself. To make
someone's entry (it asks for their password):

    docker compose run --rm admin hash-password <name>
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import threading
import time
from collections import deque

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


class Attempts:
    """Wrong passwords, so someone can't keep guessing: after MAX wrong passwords from one address, or for one
    name, in MINUTES, that address or name has to wait until the first of them is MINUTES old. While it waits,
    even the right password is refused, so a guesser can't tell when they've found it.

    Kept in memory: there's one admin container, and a restart only gives a guesser a fresh start. On the live
    server the address is the visitor's, passed on by the front door (FORWARDED_ALLOW_IPS in
    docker-compose.front-door.yml). Someone guessing at a name also makes its owner wait: a nuisance, but
    better than letting the guessing go on.
    """

    MAX = 5
    MINUTES = 15

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._wrong: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def wait_minutes(self, name: str, address: str) -> int:
        """How many minutes before this name and address can try again: 0 if they can now."""
        now = self._clock()
        with self._lock:
            self._forget_old(now)
            full = [times[0] for key in self._keys(name, address) if len(times := self._wrong.get(key, ())) >= self.MAX]
        return math.ceil((min(full) + self.MINUTES * 60 - now) / 60) if full else 0

    def wrong(self, name: str, address: str) -> None:
        now = self._clock()
        with self._lock:
            self._forget_old(now)
            for key in self._keys(name, address):
                self._wrong.setdefault(key, deque()).append(now)

    def right(self, name: str, address: str) -> None:
        with self._lock:
            for key in self._keys(name, address):
                self._wrong.pop(key, None)

    def _keys(self, name: str, address: str) -> list[tuple[str, str]]:
        return [("name", name.strip().lower()), ("address", address)]

    def _forget_old(self, now: float) -> None:
        for key, times in list(self._wrong.items()):
            while times and times[0] <= now - self.MINUTES * 60:
                times.popleft()
            if not times:
                del self._wrong[key]


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
