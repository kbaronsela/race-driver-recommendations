#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "data" / "whatsapp_recommendations.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
no_field = [e for e in data if not (e.get("field") or "").strip()]
out_path = Path(__file__).resolve().parent.parent / "data" / "empty_field_list.txt"
with open(out_path, "w", encoding="utf-8") as out:
    out.write(f"{len(no_field)} without field\n\n")
    for e in no_field:
        name = e.get("name", "")
        note = (e.get("note") or "")[:350]
        out.write("---\n")
        out.write(f"NAME: {name}\n")
        out.write(f"NOTE: {note}\n\n")
print("Wrote", out_path, "with", len(no_field), "entries")
