#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
איחוד כפילויות ב-entries.json (אותה לוגיקה כמו ב-whatsapp_to_recommendations אחרי ייצור JSON).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"

from duplicate_contact_merge import apply_duplicate_merge_to_entries  # noqa: E402


def main() -> int:
    if not ENTRIES_PATH.exists():
        print(f"Missing {ENTRIES_PATH}")
        return 1
    data = json.loads(ENTRIES_PATH.read_text(encoding="utf-8"))
    out, n_groups = apply_duplicate_merge_to_entries(data)
    ENTRIES_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {ENTRIES_PATH}")
    print(f"  Merge groups applied: {n_groups}, rows: {len(data)} -> {len(out)} (delta: {len(out) - len(data):+d})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
