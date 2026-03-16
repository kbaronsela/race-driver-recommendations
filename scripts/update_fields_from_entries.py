#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update data/fields.json to contain only field values that exist in entries.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"
FIELDS_PATH = ROOT / "data" / "fields.json"


def main():
    with open(ENTRIES_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        print("Invalid entries format", file=sys.stderr)
        sys.exit(1)
    raw = set(
        (e.get("field") or "").strip()
        for e in entries
        if isinstance(e, dict) and (e.get("field") or "").strip()
    )
    rest = sorted(raw)
    other_opt = "אחר (הזן ידנית)"
    out_list = rest if other_opt in rest else rest + [other_opt]
    with open(FIELDS_PATH, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)
    print("Updated fields.json with", len(out_list), "items")


if __name__ == "__main__":
    main()
