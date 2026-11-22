#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הגדרת שם משתמש וסיסמה למנהל/ת האתר. נשמר בקובץ config.json שאינו נשלח לגיט.

הרצה:  python mishelanu/set_password.py
"""
import getpass
import hashlib
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def main():
    user = input("Admin username: ").strip()
    while not user:
        user = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ")
    while len(password) < 6:
        password = getpass.getpass("Too short (6+ characters). Admin password: ")
    again = getpass.getpass("Repeat password: ")
    if password != again:
        print("Passwords do not match - nothing was saved.")
        return 1
    password_hash = hashlib.sha256(f"{user}:{password}".encode()).hexdigest()
    CONFIG_PATH.write_text(
        json.dumps({"user": user, "password_hash": password_hash}, indent=2),
        encoding="utf-8",
    )
    print("Saved. Admin login is now enabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
