#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
דוח כפילויות (ללא שינוי entries.json). הלוגיקה ב-duplicate_contact_merge.py.

Writes:
  data/duplicate_contacts_same_field.json
  data/duplicate_contacts_same_field.txt
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_PATH = ROOT / "data" / "entries.json"
OUT_JSON = ROOT / "data" / "duplicate_contacts_same_field.json"
OUT_TXT = ROOT / "data" / "duplicate_contacts_same_field.txt"

from duplicate_contact_merge import build_duplicate_report_payload  # noqa: E402


def main() -> int:
    if not ENTRIES_PATH.exists():
        print(f"Missing {ENTRIES_PATH}")
        return 1
    data = json.loads(ENTRIES_PATH.read_text(encoding="utf-8"))
    payload = build_duplicate_report_payload(data)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    groups_exact = payload["groups_exact"]
    groups_extended = payload["groups_extended"]
    lines = [
        "# כפילויות: אותו תחום + מספרי טלפון שונים",
        "",
        f"## חלק א — שם מנורמל זהה לחלוטין ({len(groups_exact)} קבוצות)",
        "",
    ]
    for i, g in enumerate(groups_exact, 1):
        lines.append(f"### א-{i}. {g['normalized_name']}")
        lines.append(f"    תחום: {g['field']!r}")
        lines.append(f"    מספרים: {', '.join(g['distinct_phones'])}")
        for j, ent in enumerate(g["entries"], 1):
            lines.append(f"    {j}) {ent['name']} — {ent['phone']}")
        lines.append("")

    lines.append(f"## חלק ב — הרחבה: קידומת / רצף מילים ({len(groups_extended)} קבוצות)")
    lines.append("")
    for i, g in enumerate(groups_extended, 1):
        lines.append(f"### ב-{i}. {g.get('label', '')[:100]}{'…' if len(g.get('label', '')) > 100 else ''}")
        lines.append(f"    תחום: {g['field']!r}")
        lines.append(f"    מספרים: {', '.join(g['distinct_phones'])}")
        for j, ent in enumerate(g["entries"], 1):
            lines.append(f"    {j}) {ent['name']} — {ent['phone']}")
        lines.append("")

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_TXT}")
    print(f"Exact groups: {len(groups_exact)}, extended groups: {len(groups_extended)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
