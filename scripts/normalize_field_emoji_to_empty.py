#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set field to empty wherever the field contains only emojis (and/or whitespace)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

# Remove common emoji ranges (UCS-4)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "]+",
    flags=re.UNICODE,
)


def is_only_emojis_or_empty(s):
    if s is None:
        return True
    if not isinstance(s, str):
        return False
    cleaned = EMOJI_PATTERN.sub("", s).strip()
    return len(cleaned) == 0


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
        if field is not None and is_only_emojis_or_empty(field):
            e["field"] = ""
            updated += 1
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print("Updated", updated, "entries: field was only emojis, set to empty")


if __name__ == "__main__":
    main()
