"""Run the admin page, or make a login for it.

    python -m catalyst.admin serve                 start the admin page
    python -m catalyst.admin hash-password <name>  make someone's ADMIN_USERS entry

The settings come from environment variables: see settings.py.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import passwords
from .settings import Settings, SettingsError

PORT = 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admin", description="The admin page.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="start the admin page")
    serve_parser.add_argument("--reload", action="store_true", help="restart when the code changes (for development)")
    hash_parser = commands.add_parser("hash-password", help="make someone's entry for ADMIN_USERS")
    hash_parser.add_argument("name", help="their login name, e.g. tom")
    args = parser.parse_args(argv)

    if args.command == "hash-password":
        return _hash_password(args.name)

    try:
        Settings.from_environment()  # stop here with a clear message if a setting is wrong
    except SettingsError as e:
        print(f"The admin page can't start. {e}", file=sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(
        "catalyst.admin.app:create_app", factory=True, host="0.0.0.0", port=PORT,
        reload=args.reload, reload_dirs=["catalyst"], reload_includes=["*.py", "*.yaml"],
    )
    return 0


def _hash_password(name: str) -> int:
    name = name.strip().lower()
    if not passwords.NAME_RE.match(name):
        print("Use a short name of lower-case letters and numbers, e.g. tom", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("No terminal to type the password in.", file=sys.stderr)
        return 2
    password = getpass.getpass(f"Password for {name}: ")
    if len(password) < passwords.MIN_PASSWORD_LENGTH:
        print(
            f"Use at least {passwords.MIN_PASSWORD_LENGTH} characters. A long random one is best, "
            "e.g. from a password manager or `openssl rand -base64 18`.",
            file=sys.stderr,
        )
        return 2
    if getpass.getpass("Type it again: ") != password:
        print("The two passwords don't match.", file=sys.stderr)
        return 2
    print(
        f"\nAdd this to ADMIN_USERS in .env (separate people with commas):\n\n"
        f"{name}:{passwords.hash_password(password)}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
