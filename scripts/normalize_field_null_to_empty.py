#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to empty string wherever it is null or the string 'null'/'NULL'."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"


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
        field = e.get("field")
        if field is None or (isinstance(field, str) and field.strip().lower() == "null"):
            e["field"] = ""
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries: field set to empty")


if __name__ == "__main__":
    main()
