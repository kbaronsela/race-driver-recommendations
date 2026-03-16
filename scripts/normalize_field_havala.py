#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'הובלה' for all contacts whose field is related to moving/transport."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

HAVALA_KEYWORDS = ("הובלה", "הובלות", "הובלת", "מוביל", "מובילים")


def is_havala_related(field):
    if not field or not isinstance(field, str):
        return False
    f = field.strip()
    return any(kw in f for kw in HAVALA_KEYWORDS)


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
        field = e.get("field", "")
        if is_havala_related(field) and field != "הובלה":
            e["field"] = "הובלה"
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field 'Havala'")


if __name__ == "__main__":
    main()
