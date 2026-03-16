#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'ביטוח' where name or field is related to insurance."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "ביטוח"
BITUCH_KEYWORDS = ("ביטוח", "ביטוחים", "סוכן ביטוח", "סוכנות ביטוח", "סןכן ביטוח")


def is_bituch_related(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s.strip() for kw in BITUCH_KEYWORDS)


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
        if (is_bituch_related(name) or is_bituch_related(field)) and field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field 'Bituch'")


if __name__ == "__main__":
    main()
