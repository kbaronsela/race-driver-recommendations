#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Set 'extra_info' on every entry in data/entries.json using infer_additional_info."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from additional_info import infer_additional_info  # noqa: E402

ENTRIES = ROOT / "data" / "entries.json"


def main():
    data = json.loads(ENTRIES.read_text(encoding="utf-8"))
    n = 0
    for e in data:
        # migrate legacy Hebrew key
        if "מידע נוסף" in e and "extra_info" not in e:
            e["extra_info"] = e.pop("מידע נוסף")
        elif "מידע נוסף" in e:
            e.pop("מידע נוסף", None)
        name = e.get("name") or ""
        note = e.get("note") or ""
        field = e.get("field") or ""
        extra = infer_additional_info(name, note, field)
        e["extra_info"] = extra
        if extra:
            n += 1
    ENTRIES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {ENTRIES} — extra_info filled: {n} / {len(data)}")


if __name__ == "__main__":
    main()
