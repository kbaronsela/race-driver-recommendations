#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create or update config.json with a login user and password.
Run: python set_password.py <username> <password>
Example: python set_password.py admin mysecret123
"""
import hashlib
import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def main():
    if len(sys.argv) != 3:
        print("Usage: python set_password.py <username> <password>")
        print("Example: python set_password.py admin mysecret123")
        sys.exit(1)
    user = sys.argv[1].strip()
    password = sys.argv[2].strip()
    if not user or not password:
        print("Username and password must be non-empty.")
        sys.exit(1)
    h = hashlib.sha256(f"{user}:{password}".encode()).hexdigest()
    config = {"user": user, "password_hash": h}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"Updated {CONFIG_PATH} with user: {user}")
    print("Restart the server if it is running, then log in with this username and password.")


if __name__ == "__main__":
    main()
