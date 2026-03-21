#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-apply curated websites to data/restaurants.json (same map as extract pipeline)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "restaurants.json"

from restaurant_websites import assign_websites  # noqa: E402


def main() -> int:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    filled = assign_websites(rows, log_hints=True)
    DATA.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {DATA} — {filled}/{len(rows)} with non-empty website")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
