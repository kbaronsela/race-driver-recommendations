#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'נגרות' where name or field is related to carpentry (נגרות)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "נגרות"

# Exact phrases
CARPENTRY_PHRASES = (
    "נגרות",
    "נגריה",
    "הנגר",
)

def is_carpentry_related(s):
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if any(phrase in s for phrase in CARPENTRY_PHRASES):
        return True
    # Word "נגר" (carpenter) - avoid matching names like זינגר, הרלינגר
    if " נגר" in (" " + s) or s.startswith("נגר ") or s == "נגר":
        return True
    return False


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
        if (is_carpentry_related(name) or is_carpentry_related(field)) and field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field Carpentry")


if __name__ == "__main__":
    main()
