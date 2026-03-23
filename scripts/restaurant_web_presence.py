# -*- coding: utf-8 -*-
"""אימות נוכחות ברשת למסעדות: אתר ידוע או תוצאות חיפוש (Google Custom Search).

דורש משתני סביבה:
  GOOGLE_CSE_API_KEY — מפתח API מ-Google Cloud (מופעל Custom Search API)
  GOOGLE_CSE_CX — מזהה מנוע חיפוש מתוכנת (Programmable Search Engine)

מטמון: data/restaurant_web_presence_cache.json (חוסך קריאות חוזרות).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_CACHE_FILENAME = "restaurant_web_presence_cache.json"

# מילות עצירה קצרות בשאילתה / בהתאמת תוצאות
_STOP_TOKENS = frozenset(
    {
        "מסעדה",
        "מסעדת",
        "המסעדה",
        "בית",
        "קפה",
        "ב",
        "וב",
        "של",
        "ליד",
        "the",
        "and",
        "or",
    }
)

_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _cache_key(name: str, location: str) -> str:
    raw = f"{(name or '').strip()}\n{(location or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _has_real_website(row: dict) -> bool:
    w = (row.get("website") or "").strip().lower()
    return w.startswith("http://") or w.startswith("https://")


def _name_tokens(name: str) -> list[str]:
    s = re.sub(r"\([^)]*\)", " ", name or "")
    s = re.sub(r"[^\w\s\u0590-\u05FF\-]", " ", s, flags=re.UNICODE)
    parts = [p.strip() for p in s.split() if len(p.strip()) >= 2]
    out: list[str] = []
    for p in parts:
        pl = p.casefold()
        if pl in _STOP_TOKENS:
            continue
        out.append(p)
    return out


def _result_matches_name(items: list[dict], name: str) -> bool:
    tokens = _name_tokens(name)
    if not tokens:
        return bool(items)
    blob = ""
    for it in items:
        blob += (it.get("title") or "") + " " + (it.get("snippet") or "") + " "
    b = blob.casefold()
    for t in tokens:
        if t.casefold() in b:
            return True
    return False


def _build_query(name: str, location: str) -> str:
    parts = [(name or "").strip()]
    if (location or "").strip():
        parts.append(location.strip())
    parts.append("מסעדה")
    parts.append("ישראל")
    q = " ".join(p for p in parts if p)
    return q[:240]


def google_cse_search(query: str, *, api_key: str, cx: str, num: int = 5) -> list[dict]:
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": str(min(max(num, 1), 10)),
    }
    url = _GOOGLE_CSE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "race-driver-recommendations/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    return list(payload.get("items") or [])


def filter_by_web_presence(
    rows: list[dict],
    *,
    root: Path,
    delay_sec: float = 0.35,
) -> tuple[list[dict], dict[str, int]]:
    """
    משאיר רק שורות עם אתר (http) או עם אזכור ברשת לפי Google CSE.

    ללא GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX — מעלה RuntimeError (הקורא אמור לבדוק מראש).
    """
    api_key = (os.environ.get("GOOGLE_CSE_API_KEY") or "").strip()
    cx = (os.environ.get("GOOGLE_CSE_CX") or "").strip()
    if not api_key or not cx:
        raise RuntimeError(
            "חסרים GOOGLE_CSE_API_KEY או GOOGLE_CSE_CX בסביבה — לא ניתן לאמת נוכחות ברשת."
        )

    cache_path = root / "data" / _CACHE_FILENAME
    cache = _load_cache(cache_path)
    kept: list[dict] = []
    stats = {"kept": 0, "dropped": 0, "cached_hits": 0, "api_calls": 0}

    for row in rows:
        name = row.get("name") or ""
        loc = row.get("location") or ""

        if _has_real_website(row):
            kept.append(row)
            stats["kept"] += 1
            continue

        ck = _cache_key(name, loc)
        if ck in cache:
            stats["cached_hits"] += 1
            entry = cache[ck]
            if entry.get("ok"):
                kept.append(row)
                stats["kept"] += 1
            else:
                stats["dropped"] += 1
            continue

        query = _build_query(name, loc)
        try:
            time.sleep(delay_sec)
            items = google_cse_search(query, api_key=api_key, cx=cx)
            stats["api_calls"] += 1
            ok = bool(items) and _result_matches_name(items, name)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except OSError:
                pass
            raise RuntimeError(f"Google CSE HTTP {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Google CSE רשת/שגיאה: {e}") from e

        cache[ck] = {
            "ok": ok,
            "query": query,
            "name": name,
            "location": loc,
            "hits": len(items),
        }
        _save_cache(cache_path, cache)

        if ok:
            kept.append(row)
            stats["kept"] += 1
        else:
            stats["dropped"] += 1

    return kept, stats


def web_verify_configured() -> bool:
    return bool((os.environ.get("GOOGLE_CSE_API_KEY") or "").strip()) and bool(
        (os.environ.get("GOOGLE_CSE_CX") or "").strip()
    )
