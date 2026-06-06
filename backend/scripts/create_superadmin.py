"""Provision the break-glass superadmin account.

Run once from the backend/ directory:

    python -m scripts.create_superadmin

What it does
────────────
  1. Connects to the DB via the current DATABASE_URL (from .env / env var).
  2. Refuses if a superadmin account already exists (one account max).
  3. Prompts for email + password (password not echoed).
  4. Hashes the password with bcrypt.
  5. Generates a TOTP secret (base32).
  6. Inserts the row with totp_enabled=False.
  7. Prints the provisioning URI — scan this into Google Authenticator,
     Authy, or any TOTP app.
  8. The account is NOT active until TOTP is confirmed: on first login at
     /superadmin/login the app redirects to /superadmin/setup where you enter
     the code from your authenticator app to activate 2FA.

Resetting a forgotten password or TOTP
───────────────────────────────────────
  psql <DATABASE_URL> -c "DELETE FROM superadmin;"
  Then re-run this script.
"""
import getpass
import sys

import bcrypt
import pyotp
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Ensure we can import app modules when run as `python -m scripts.create_superadmin`
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import config
from app.core.db import init_db, get_session
from app.core.models import SuperAdmin


def main() -> None:
    print("DEPT® Academy — superadmin provisioning")
    print(f"Database: {config.DATABASE_URL[:40]}…")
    print()

    init_db()

    with get_session() as s:
        count = s.query(SuperAdmin).count()

    if count > 0:
        print("ERROR: a superadmin account already exists.")
        print("To reset it: DELETE FROM superadmin; then re-run this script.")
        sys.exit(1)

    email = input("Superadmin email: ").strip()
    if not email or "@" not in email:
        print("ERROR: invalid email.")
        sys.exit(1)

    password = getpass.getpass("Password (not echoed): ")
    if len(password) < 12:
        print("ERROR: password must be at least 12 characters.")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("ERROR: passwords do not match.")
        sys.exit(1)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    totp_secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=email, issuer_name="DEPT Academy Superadmin"
    )

    with get_session() as s:
        s.add(SuperAdmin(
            email=email,
            password_hash=password_hash,
            totp_secret=totp_secret,
            totp_enabled=False,
        ))
        s.commit()

    print()
    print("─" * 60)
    print("Superadmin account created. 2FA is NOT yet active.")
    print()
    print("PROVISIONING URI (paste into your authenticator app):")
    print()
    print(f"  {uri}")
    print()
    print("RAW SECRET (for manual entry):")
    print()
    print(f"  {totp_secret}")
    print()
    print("─" * 60)
    print("Next steps:")
    print("  1. Scan the URI (or enter the raw secret) into Google")
    print("     Authenticator, Authy, or any TOTP app.")
    print("  2. Start the app and go to /superadmin/login")
    print("  3. Enter your email + password → you will be redirected")
    print("     to /superadmin/setup to confirm a 6-digit code.")
    print("  4. Once confirmed, 2FA is active and required on every login.")
    print()


if __name__ == "__main__":
    main()
