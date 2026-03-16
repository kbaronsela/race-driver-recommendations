#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'מספרה' where name or field is related to hair salon / barber (מספרה, שיער)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "מספרה"
BARBER_KEYWORDS = (
    "מספרה",
    "מספרי",
    "ספרית",
    "תספורת",
    "החלקת שיער",
    "צבע לשיער",
    "הספר",
    " ספר ",
)

# Exclude: literature (ספרות)
EXCLUDE_KEYWORDS = (
    "לספרות",
    "מורה לספרות",
)

def is_barber_related(s):
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if any(kw in s for kw in BARBER_KEYWORDS):
        return True
    # "ספר" at start (e.g. "שחר ספר") or "ספר " 
    if s.startswith("ספר ") or s.endswith(" ספר"):
        return True
    return False


def is_excluded(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s.strip() for kw in EXCLUDE_KEYWORDS)


def main():
    with open(ENTRIES_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        print("Invalid format", file=sys.stderr)
        sys.exit(1)
    updated = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = e.get("name") or ""
        field = e.get("field") or ""
        combined = (name + " " + field).strip()
        if (is_barber_related(name) or is_barber_related(field)) and not is_excluded(combined) and field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field Barber")


if __name__ == "__main__":
    main()
