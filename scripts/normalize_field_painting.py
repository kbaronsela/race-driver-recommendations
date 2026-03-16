#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'צבע' where name or field is related to painting (צבעי/צביעה/צבעות)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "צבע"
PAINTING_KEYWORDS = (
    "צבעי",
    "צביעה",
    "צבעות",
    "מצבעה",
    "הצבע",
    "טיח צבע",
)

# Exclude: hair color (hairdresser)
EXCLUDE_KEYWORDS = (
    "צבע לשיער",
)

def is_painting_related(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s.strip() for kw in PAINTING_KEYWORDS)


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
        if (is_painting_related(name) or is_painting_related(field)) and not is_excluded(combined) and field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field Painting")


if __name__ == "__main__":
    main()
