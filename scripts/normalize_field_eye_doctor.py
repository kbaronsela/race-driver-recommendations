#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'רפואה' for eye doctors (רופא/רופאת עיניים)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "רפואה"
EYE_DOCTOR_KEYWORDS = (
    "רופא עיניים",
    "רופאת עיניים",
)


def is_eye_doctor_related(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s for kw in EYE_DOCTOR_KEYWORDS)


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
        note = e.get("note") or ""
        if not (is_eye_doctor_related(name) or is_eye_doctor_related(field) or is_eye_doctor_related(note)):
            continue
        if field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field: eye doctors (medicine)", flush=True)


if __name__ == "__main__":
    main()
