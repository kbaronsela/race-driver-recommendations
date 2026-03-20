#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'אופטיקה' for all contacts related to optics (optometry, glasses, eye exams).
Uses same priority as main script: name > note > context; does not override when name implies another field."""
import json
import sys
from pathlib import Path

# Use same field inference as whatsapp_to_recommendations (priority: name, then note, then context)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from whatsapp_to_recommendations import infer_field_from_text

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "אופטיקה"
# Optics only (not eye doctors — those go to רפואה)
OPTICS_KEYWORDS = (
    "אופטיקה",
    "אופטיקאי",
    "אופטיקאית",
    "אופטימטריסט",
    "אופטומטריסט",
    "אופטומטריסטית",
    "משקפיים",
    "חנות משקפיים",
    "בדיקת ראייה",
    "עדשות מגע",
    "מולטיפוקל",
)


def is_optics_related(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s for kw in OPTICS_KEYWORDS)


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
        if not (is_optics_related(name) or is_optics_related(field) or is_optics_related(note)):
            continue
        # Same priority as main script: name first — don't override if name implies another field
        field_from_name = infer_field_from_text(name)
        if field_from_name and field_from_name != TARGET:
            continue
        if field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to optics", flush=True)


if __name__ == "__main__":
    main()
