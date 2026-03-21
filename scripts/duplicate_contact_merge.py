#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
זיהוי ואיחוד כפילויות: אותו תחום + מספרים שונים + שם מנורמל זהה או קידומת/subsequence (כמו list_duplicate_contacts_same_field).

מיוצא לשימוש:
  - whatsapp_to_recommendations (אחרי בניית הרשימה)
  - merge_duplicate_contacts_into_entries
  - list_duplicate_contacts_same_field (דוח בלבד)
"""
from __future__ import annotations

import re
from collections import defaultdict

# שם מנורמל = תיאור מקצוע כללי בלבד — לא מאחדים עם אחרים
GENERIC_ONLY_NAMES_NORM: frozenset[str] = frozenset(
    {
        "ניקוי ספות",
    }
)


def norm_name_base(s: str) -> str:
    if not s:
        return ""
    s = str(s).replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_aggressive(name: str) -> str:
    s = norm_name_base(name)
    for ch in '-–—.,;:!?"\'״׳()[]{}|/\\':
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


def is_generic_only_name(name: str) -> bool:
    n = norm_aggressive(name)
    return bool(n) and n in GENERIC_ONLY_NAMES_NORM


def _strip_leading_l_token(t: str) -> str:
    t = t.casefold()
    if t.startswith("ל") and len(t) >= 2:
        return t[1:]
    return t


def _tokens_for_subsequence(norm: str) -> list[str]:
    return [_strip_leading_l_token(x) for x in norm.split() if x]


def shorter_is_ordered_subsequence_tokens(short_norm: str, long_norm: str) -> bool:
    if short_norm == long_norm:
        return False
    ts = _tokens_for_subsequence(short_norm)
    tl = _tokens_for_subsequence(long_norm)
    if len(ts) < 3 or len(tl) <= len(ts):
        return False
    i = 0
    for t in ts:
        while i < len(tl) and tl[i] != t:
            i += 1
        if i >= len(tl):
            return False
        i += 1
    return True


def names_related_extended(name_a: str, name_b: str) -> bool:
    if is_generic_only_name(name_a) or is_generic_only_name(name_b):
        return False
    na, nb = norm_aggressive(name_a), norm_aggressive(name_b)
    if not na or not nb or na == nb:
        return False
    if len(na) > len(nb):
        na, nb = nb, na
    short_s, long_s = na, nb
    if len(short_s.split()) < 2:
        return False
    if long_s.startswith(short_s + " "):
        return True
    if len(long_s) > len(short_s) and shorter_is_ordered_subsequence_tokens(short_s, long_s):
        return True
    return False


class UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _entry_stub(r: dict) -> dict:
    note = r.get("note") or ""
    return {
        "name": r.get("name"),
        "phone": r.get("phone"),
        "field": r.get("field") or "",
        "from_moshav": r.get("from_moshav"),
        "note_preview": (note[:200] + "…") if len(note) > 200 else note,
    }


def phone_sort_key(p: str) -> tuple:
    d = re.sub(r"\D", "", p or "")
    if d.startswith("05") and len(d) >= 9:
        return (0, d)
    if d.startswith("0"):
        return (1, d)
    return (2, d)


def merge_group_members(members: list[dict]) -> dict:
    phones = sorted(
        {m.get("phone") or "" for m in members if m.get("phone")},
        key=phone_sort_key,
    )
    primary = phones[0] if phones else ""

    name = max((m.get("name") or "" for m in members), key=len)
    field = next((m.get("field") or "" for m in members if (m.get("field") or "").strip()), "")
    from_moshav = any(m.get("from_moshav") for m in members)

    notes: list[str] = []
    seen_n = set()
    for m in members:
        n = (m.get("note") or "").strip()
        if n and n not in seen_n:
            seen_n.add(n)
            notes.append(n)
    note = " | ".join(notes)

    extras = [(m.get("extra_info") or "").strip() for m in members if (m.get("extra_info") or "").strip()]
    extra_info = max(extras, key=len) if extras else ""

    return {
        "name": name,
        "phone": primary,
        "phones": phones,
        "field": field,
        "from_moshav": from_moshav,
        "note": note,
        "extra_info": extra_info,
    }


def collect_merge_groups(entries: list[dict]) -> list[list[dict]]:
    """קבוצות של רשומות מלאות לאיחוד (ללא כפילות בין קבוצות)."""
    merge_groups: list[list[dict]] = []

    # --- exact ---
    groups_map: dict[tuple[str, str], list] = defaultdict(list)
    for e in entries:
        nm = norm_aggressive(e.get("name") or "")
        if not nm:
            continue
        field = (e.get("field") or "").strip()
        groups_map[(nm, field)].append(e)

    for (nm, field), rows in groups_map.items():
        if nm in GENERIC_ONLY_NAMES_NORM:
            continue
        phones = {r.get("phone") or "" for r in rows}
        phones.discard("")
        if len(phones) < 2:
            continue
        merge_groups.append(rows)

    # --- extended ---
    by_field: dict[str, list] = defaultdict(list)
    for e in entries:
        nm = norm_aggressive(e.get("name") or "")
        if not nm:
            continue
        field = (e.get("field") or "").strip()
        by_field[field].append(e)

    seen_extended_fingerprints: set[frozenset[tuple[str, str]]] = set()

    for field, rows in by_field.items():
        n = len(rows)
        if n < 2:
            continue
        uf = UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                pi, pj = rows[i].get("phone") or "", rows[j].get("phone") or ""
                if not pi or not pj or pi == pj:
                    continue
                ni, nj = rows[i].get("name") or "", rows[j].get("name") or ""
                if names_related_extended(ni, nj):
                    uf.union(i, j)

        comp: dict[int, list] = defaultdict(list)
        for i in range(n):
            comp[uf.find(i)].append(rows[i])

        for _root, members in comp.items():
            phones = {r.get("phone") or "" for r in members}
            phones.discard("")
            if len(phones) < 2:
                continue
            norms = {norm_aggressive(r.get("name") or "") for r in members}
            norms.discard("")
            if len(norms) < 2:
                continue

            fp = frozenset((r.get("phone") or "", norm_aggressive(r.get("name") or "")) for r in members)
            if fp in seen_extended_fingerprints:
                continue
            seen_extended_fingerprints.add(fp)
            merge_groups.append(members)

    return merge_groups


def apply_duplicate_merge_to_entries(entries: list[dict]) -> tuple[list[dict], int]:
    """
    מחזיר רשימה חדשה עם כפילויות מאוחדות (שדה phones).
    מחזיר גם מספר קבוצות שאוחדו.
    """
    groups = collect_merge_groups(entries)
    if not groups:
        return list(entries), 0

    phone_to_merged: dict[str, dict] = {}
    for members in groups:
        ph_set = {m.get("phone") or "" for m in members}
        ph_set.discard("")
        if len(ph_set) < 2:
            continue
        merged = merge_group_members(members)
        for p in ph_set:
            phone_to_merged[p] = merged

    seen_merged_id: set[int] = set()
    out: list[dict] = []
    for e in entries:
        p = e.get("phone") or ""
        if p not in phone_to_merged:
            out.append(e)
            continue
        m = phone_to_merged[p]
        mid = id(m)
        if mid in seen_merged_id:
            continue
        seen_merged_id.add(mid)
        out.append(m)

    return out, len(groups)


def build_duplicate_report_payload(data: list[dict]) -> dict:
    """מבנה ל-duplicate_contacts_same_field.json (דוח בלבד, בלי לשנות נתונים)."""
    groups_exact = []
    groups_map: dict[tuple[str, str], list] = defaultdict(list)
    for e in data:
        nm = norm_aggressive(e.get("name") or "")
        if not nm:
            continue
        field = (e.get("field") or "").strip()
        groups_map[(nm, field)].append(e)

    for (nm, field), rows in groups_map.items():
        if nm in GENERIC_ONLY_NAMES_NORM:
            continue
        phones = {r.get("phone") or "" for r in rows}
        phones.discard("")
        if len(phones) < 2:
            continue
        groups_exact.append(
            {
                "match_kind": "exact_name",
                "normalized_name": nm,
                "field": field,
                "distinct_phones": sorted(phones),
                "count_entries": len(rows),
                "entries": [_entry_stub(r) for r in rows],
            }
        )

    groups_exact.sort(key=lambda g: (-len(g["distinct_phones"]), g["field"], g["normalized_name"]))

    by_field: dict[str, list] = defaultdict(list)
    for e in data:
        nm = norm_aggressive(e.get("name") or "")
        if not nm:
            continue
        field = (e.get("field") or "").strip()
        by_field[field].append(e)

    groups_extended = []
    seen_extended_fingerprints: set[frozenset[tuple[str, str]]] = set()

    for field, rows in by_field.items():
        n = len(rows)
        if n < 2:
            continue
        uf = UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                pi, pj = rows[i].get("phone") or "", rows[j].get("phone") or ""
                if not pi or not pj or pi == pj:
                    continue
                ni, nj = rows[i].get("name") or "", rows[j].get("name") or ""
                if names_related_extended(ni, nj):
                    uf.union(i, j)

        comp: dict[int, list] = defaultdict(list)
        for i in range(n):
            comp[uf.find(i)].append(rows[i])

        for _root, members in comp.items():
            phones = {r.get("phone") or "" for r in members}
            phones.discard("")
            if len(phones) < 2:
                continue
            norms = {norm_aggressive(r.get("name") or "") for r in members}
            norms.discard("")
            if len(norms) < 2:
                continue

            fp = frozenset((r.get("phone") or "", norm_aggressive(r.get("name") or "")) for r in members)
            if fp in seen_extended_fingerprints:
                continue
            seen_extended_fingerprints.add(fp)

            label = " | ".join(sorted(norms)[:4])
            if len(norms) > 4:
                label += " | …"
            groups_extended.append(
                {
                    "match_kind": "extended_prefix_or_subsequence",
                    "label": label,
                    "field": field,
                    "distinct_phones": sorted(phones),
                    "count_entries": len(members),
                    "normalized_names": sorted(norms),
                    "entries": [_entry_stub(r) for r in members],
                }
            )

    groups_extended.sort(
        key=lambda g: (-len(g["distinct_phones"]), g["field"], g.get("label") or "")
    )

    return {
        "criteria": {
            "exact": "אותו שם מנורמל + אותו תחום + לפחות 2 מספרים",
            "extended": "אותו תחום + 2 מספרים + שמות שונים: קידומת מחרוזת אחרי רווח, או מילות השם הקצר מופיעות בתוך הארוך בסדר (נרמול ל- ראש מילה)",
            "excluded_generic_names": sorted(GENERIC_ONLY_NAMES_NORM),
            "excluded_generic_note": "שמות כלליים בלבד — לא נכללים באיחוד מול שום רשומה",
        },
        "total_groups_exact": len(groups_exact),
        "total_groups_extended": len(groups_extended),
        "groups_exact": groups_exact,
        "groups_extended": groups_extended,
    }
