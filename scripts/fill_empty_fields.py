#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-infer field for entries with empty field (name first, then note)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from whatsapp_to_recommendations import infer_field_from_text, infer_field_from_note  # noqa: E402

ENTRIES = ROOT / "data" / "entries.json"


def main():
    data = json.loads(ENTRIES.read_text(encoding="utf-8"))
    filled = 0
    for e in data:
        if (e.get("field") or "").strip():
            continue
        name = e.get("name") or ""
        note = e.get("note") or ""
        f = infer_field_from_text(name)
        if not f:
            f = infer_field_from_note(note)
        if f:
            e["field"] = f
            filled += 1
    ENTRIES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    empty = sum(1 for e in data if not (e.get("field") or "").strip())
    print(f"Filled {filled} entries. Still empty: {empty}.")


if __name__ == "__main__":
    main()
