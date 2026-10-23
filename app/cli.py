"""Command-line utilities.

    python -m app.cli create-admin --email admin@example.com --name "Admin"

The password is read from the ``ADMIN_PASSWORD`` environment variable or prompted
for (never passed on the command line, so it does not land in shell history).
"""
import argparse
import getpass
import os
import sys

from app.database import SessionLocal
from app.services import user_service
from app.utils.errors import AppError


def create_admin(args: argparse.Namespace) -> int:
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    db = SessionLocal()
    try:
        user = user_service.create_admin(db, args.name, args.email, args.phone, password)
        print(f"Admin created: id={user.id} email={user.email}")
        return 0
    except AppError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Create the first (or another) Admin account")
    p.add_argument("--name", default="Administrator")
    p.add_argument("--email", required=True)
    p.add_argument("--phone", default="9000000000", help="10-digit phone number")
    p.set_defaults(func=create_admin)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
