#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to 'רפואה' where name or field is related to doctors/medicine (excluding dentistry)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

TARGET = "רפואה"
MEDICINE_KEYWORDS = (
    "רופא",
    "רופאה",
    "רפואה",
    "ד\"ר",
    "דוקטור",
    " דר ",  # ד"ר באמצע (לא "הדר")
    "רופא עיניים",
    "רופאת עור",
    "רופא עור",
    "רופא נשים",
    "רופא אף אוזן",
    "מרפאה",
    "מרפא",
    "רפואי",
    "רפואית",
    "אורתופד",
    "אורטופד",
    "אורתופדיה",
    "אנדוקרינולוג",
    "אנדוקרינולוגית",
    "כירורג",
    "כירורגיה",
    "פסיכיאטר",
    "פסיכיאטרית",
    "פסיכוגריאטר",
)

# Exclude dentistry / orthodontics – those get "רפואת שיניים" or "אורתודנטיה"
DENTISTRY_KEYWORDS = (
    "שיניים",
    "רופא שיניים",
    "רופאת שיניים",
    "מרפאת שיניים",
    "שיננית",
    "שינני",
    "אורתודנט",
    "אורתודונט",
    "אורתודנטיה",
)

def is_medicine_related(s):
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if any(kw in s for kw in MEDICINE_KEYWORDS):
        return True
    # ד"ר בתחילת שם (לא "הדר")
    if s.startswith("דר "):
        return True
    return False


def is_dentistry_related(s):
    if not s or not isinstance(s, str):
        return False
    return any(kw in s.strip() for kw in DENTISTRY_KEYWORDS)


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
        if (is_medicine_related(name) or is_medicine_related(field)) and not is_dentistry_related(combined) and field != TARGET:
            e["field"] = TARGET
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries to field Medicine")


if __name__ == "__main__":
    main()
