#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract restaurant recommendations from WhatsApp export.
1) Structured block >>> מסעדות ומוצרי מזון (עסקים בעוטף).
2) סריקת כל הצ'אט (היוריסטית) — restaurant_chat_scan.
3) רשימה ידנית CURATED (גוברת על כפילויות בשם זהה).

Pipeline for data/restaurants.json:
  raw entries → איחוד כפולים (מפתח merge + מיקום: אותו מיקום או לפחות אחד ללא מיקום)
  → מילוי website מ־restaurant_websites → (אופציונלי) אימות נוכחות ברשת → כתיבה ל־JSON → build_view_restaurants.py

אימות רשת (אופציונלי): ``--web-verify`` או ``RESTAURANT_WEB_VERIFY=1`` — דורש
``GOOGLE_CSE_API_KEY`` ו-``GOOGLE_CSE_CX`` (Google Programmable Search + Custom Search API).
נשארות רק מסעדות עם אתר (https) או עם אזכור תואם בתוצאות חיפוש. מטמון: data/restaurant_web_presence_cache.json

Output fields: id, name, restaurant_type, location, note, extra_info, website.
בקובץ: ``note`` = שורת מקור/תאריך; ``extra_info`` = טקסט ההמלצה (החלפה יחסית לסכימה הראשונית של הפרויקט).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from restaurant_chat_scan import expand_location_abbreviations, extract_restaurants_from_chat_scan
from restaurant_name_plausible import is_plausible_restaurant_name
from restaurant_web_presence import filter_by_web_presence, web_verify_configured
from restaurant_websites import assign_websites

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "whatsapp_extract" / "WhatsApp Chat with נהגת מרוצים.txt"
OUT = ROOT / "data" / "restaurants.json"


def slug_id(s: str) -> str:
    return "r-" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def strip_trailing_paren(name: str) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip()).strip()
    while s.endswith("*"):
        s = s[:-1].rstrip()
    return s.strip()


# שם ראשון לפני " — " שמאחד למסעדה אחת (למשל בן זגר)
_EM_DASH_CANONICAL_PREFIXES = frozenset({"בן זגר"})
# שם ראשון לפני " / " שמאחד (למשל ג'וז ודניאל / גלריה אלמוג)
_SLASH_CANONICAL_PREFIXES = frozenset({"ג'וז ודניאל"})


def restaurant_merge_key(name: str) -> str:
    """מפתח איחוד לאותה מסעדה (אדמה ≈ אדמה (זיכרון), פלאפל נייד ≈ פלאפל נייד (דוכנים))."""
    n = (name or "").strip()
    if not n:
        return ""
    if " — " in n:
        first, _ = n.split(" — ", 1)
        first = first.strip()
        if first in _EM_DASH_CANONICAL_PREFIXES:
            return first.lower()
    if " / " in n:
        first, _ = n.split(" / ", 1)
        first = first.strip()
        if first in _SLASH_CANONICAL_PREFIXES:
            return first.lower()
    # קפה אוגוסט / אוגוסט … — אותו מותג (סריקה vs שם קצר / סניף)
    if n.startswith("קפה אוגוסט"):
        return "אוגוסט"
    if n.startswith("אוגוסט"):
        return "אוגוסט"
    # האחים (אבן גבירול) / האחים באבן גבירול / האחים — אותה מסעדה
    if n.startswith("האחים"):
        return "האחים"
    # נומי בכפר מונש (חילוץ מטקסט) ≈ נומי
    if n.startswith("נומי "):
        return "נומי"
    # מלצ'ט / מלצ׳ט (גרש ASCII או עברי) — אותו בית קפה
    if re.match(r"^מלצ['\u05f3]ט", n):
        return "מלצט"
    # גן סיפור / גן סיפור הוד"ש / … — אותו קפה (סימון עריכה וסיומות אזור בצ'אט)
    if n.startswith("גן סיפור"):
        return "גן סיפור"
    # גראציה בקיבוץ העוגן / גראציה — אותה מסעדה
    if n.startswith("גראציה"):
        return "גראציה"
    return strip_trailing_paren(n).lower()


def _display_name_score(n: str) -> tuple:
    """נמוך = עדיף לשם התצוגה המאוחד."""
    n = n or ""
    pen = 0
    if re.search(r"\([^)]+\)\s*$", n.strip()):
        pen += 10
    if " — " in n:
        pen += 5
    return (pen, len(n), n)


def _uniq_join(parts: list[str], sep: str = " | ") -> str:
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return sep.join(out)


def _norm_loc(s: str) -> str:
    return normalize_spaces(s or "").casefold()


def _location_merge_compatible(loc_a: str, loc_b: str) -> bool:
    """איחוד רשומות עם אותו שם: אותו מיקום, או שאחד מהמיקומים ריק."""
    a = (loc_a or "").strip()
    b = (loc_b or "").strip()
    if _norm_loc(a) == _norm_loc(b):
        return True
    if not a or not b:
        return True
    return False


def _partition_by_location_rules(grp: list[dict]) -> list[list[dict]]:
    """חלוקת רשומות עם אותו מפתח שם לרכיבים קשירים לפי כללי מיקום."""
    n = len(grp)
    if n <= 1:
        return [grp]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    for i in range(n):
        for j in range(i + 1, n):
            if _location_merge_compatible(grp[i].get("location"), grp[j].get("location")):
                union(i, j)
    buckets: dict[int, list[dict]] = {}
    for i in range(n):
        r = find(i)
        buckets.setdefault(r, []).append(grp[i])
    return list(buckets.values())


def _merge_subgroup(k: str, grp: list[dict]) -> dict:
    names = [g["name"] for g in grp]
    display = min(names, key=lambda n: _display_name_score(n))
    types = _uniq_join([g.get("restaurant_type") or "" for g in grp])
    locs = _uniq_join([g.get("location") or "" for g in grp])
    notes = _uniq_join([g.get("note") or "" for g in grp])
    extras = _uniq_join([g.get("extra_info") or "" for g in grp])
    return {
        "id": slug_id("merged:" + k + display + locs[:40]),
        "name": display,
        "restaurant_type": types[:200] if len(types) > 200 else types,
        "location": locs[:250] if len(locs) > 250 else locs,
        "note": notes[:400] + ("..." if len(notes) > 400 else ""),
        "extra_info": extras[:600] + ("..." if len(extras) > 600 else ""),
    }


def merge_restaurant_entries(entries: list[dict]) -> list[dict]:
    """
    איחוד לפי restaurant_merge_key; בתוך אותו מפתח — רק רשומות שאפשר לחבר לפי מיקום:
    מיקום זהה (אחרי נרמול), או שאחת לפחות ללא מיקום (ריק).
    """
    groups: dict[str, list[dict]] = {}
    for e in entries:
        k = restaurant_merge_key(e.get("name", ""))
        if not k:
            k = (e.get("name") or "").strip().lower()
        groups.setdefault(k, []).append(e)

    merged: list[dict] = []
    for k, grp in groups.items():
        for sub in _partition_by_location_rules(grp):
            if len(sub) == 1:
                merged.append(dict(sub[0]))
            else:
                merged.append(_merge_subgroup(k, sub))
    return merged


def dedupe_merge_and_assign_websites(entries: list[dict]) -> list[dict]:
    """
    איחוד כפולים: לפי restaurant_merge_key וכללי מיקום (אותו מיקום או לפחות אחד ריק).
    ללא דה-דופ בשם מדויק שמוחק סניפים שונים לפני האיחוד.
    """
    n0 = len(entries)
    entries = [e for e in entries if is_plausible_restaurant_name(e.get("name") or "")]
    dropped = n0 - len(entries)
    if dropped:
        print(f"Name filter: dropped {dropped} implausible rows (before dedupe)")
    entries = [
        {**e, "location": expand_location_abbreviations(e.get("location") or "")}
        for e in entries
    ]
    merged = merge_restaurant_entries(entries)
    for e in merged:
        e["restaurant_type"] = strip_kashrut_from_restaurant_type(e.get("restaurant_type") or "")
    assign_websites(merged, log_hints=True)
    return merged


def normalize_spaces(s: str) -> str:
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    return re.sub(r"\s+", " ", s).strip()


def strip_kashrut_from_restaurant_type(t: str) -> str:
    """מסיר אזכורי כשרות מ־restaurant_type — נשאר סוג המטבח/העסק בלבד."""
    s = normalize_spaces(t or "")
    if not s:
        return ""
    parts = re.split(r"\s*[/|]\s*", s)
    out: list[str] = []
    for part in parts:
        p = part.strip()
        if not p:
            continue
        p = re.sub(r"\s*לא\s+כשרה?\s*", " ", p)
        p = re.sub(r"\s*לא\s+כשר\s*", " ", p)
        p = re.sub(r"\s*כשרות\s*", " ", p)
        p = re.sub(r"\s*כשרה\s*", " ", p)
        p = re.sub(r"^\s*כשר\s+|\s+כשר\s*$|\s+כשר\s+", " ", p)
        p = normalize_spaces(p).strip(" /|,-")
        if p:
            out.append(p)
    s = " / ".join(out)
    return s[:200] if len(s) > 200 else s


def extract_gaza_food_block(text: str) -> list[dict]:
    """Parse forwarded roundup of food businesses near Gaza envelope."""
    items = []
    start = text.find(">>> מסעדות ומוצרי מזון:")
    end = text.find(">>> תיירות", start)
    if start < 0 or end < 0:
        return items
    block = text[start:end]
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith(">>>"):
            continue
        # מפריד ראשון בלבד — אחרת מספרי טלפון עם מקף (052-xxx) שוברים את השורה
        if " – " in line:
            left, rest = line.split(" – ", 1)
        elif " - " in line:
            left, rest = line.split(" - ", 1)
        else:
            continue
        name = normalize_spaces(left.strip(' "\'"״'))
        rest = normalize_spaces(rest)
        phone_m = re.search(r"(0\d{1,2}[-\d\s]{6,}|05\d[-\d\s]{7,}|08-\d{4}-\d{3,})$", rest)
        phone = normalize_spaces(phone_m.group(1)) if phone_m else ""
        body = rest[: phone_m.start()].strip().rstrip(",").strip() if phone_m else rest
        parts = [p.strip() for p in body.split(",") if p.strip()]
        loc = ""
        rtype = body
        if len(parts) >= 2:
            rtype = parts[0]
            loc = ", ".join(parts[1:])
        elif len(parts) == 1:
            rtype = parts[0]
        blob = f"{name} {rtype} {loc}"
        foodish = (
            "מסעד",
            "סושי",
            "פלאפל",
            "פסטה",
            "דגים",
            "ברזיל",
            "דוכני",
            "בר אקטיבי",
            "ארוחות גורמה",
            "בירה נגבית",
            "יקב וגלריה",
            "מזנון",
        )
        if not any(k in blob for k in foodish):
            continue
        items.append(
            {
                "id": slug_id("otef:" + name + loc),
                "name": name[:120],
                "restaurant_type": rtype[:150],
                "location": loc[:200],
                "note": (f"טלפון בפרסום: {phone}" if phone else "")[:250],
                "extra_info": "רשימת עסקי מזון מהעוטף שהופצה בקבוצה (יולי 2018).",
            }
        )
    return items


# המלצות מזוהות בשרשורים (שם, סוג, מיקום, טקסט המלצה → extra_info, שורת מקור → note)
CURATED = [
    ("מל ומישל", "איטלקית", "תל אביב", "רומנטית, איטלקית וטעימה — הומלצה להצעת נישואין (לא כשר).", "מירי יעקובי · 24/05/2016"),
    ("גלריה הביתית (שף פרטי)", "אירוח פרטי / מטבח שף", "גבעתיים", "שף פרטי בגבעתיים; פרטים בפרטי לפי עינת שיין.", "עינת שיין · 24/05/2016"),
    ("ביסטרו דה כרמל", "ביסטרו / חלבי", "זכרון יעקב", "ארוחת בוקר עסקית חלבית כשרה צפונה מהמושב.", "+972 52-773-0585 · 24/08/2016"),
    ("אדמה", "מסעדה", "זכרון יעקב", "הומלצה יחד עם ביסטרו דה כרמל וקפה נילי לארוחות בזכרון.", "+972 52-773-0585 · 24/08/2016"),
    ("קפה נילי", "בית קפה", "זכרון יעקב", "באותו שרשור המלצות לזכרון.", "+972 52-773-0585 · 24/08/2016"),
    ("ג'וז ודניאל", "מסעדה", "תל יצחק (ליד צופית)", "מסעדה מעולה, יפה וכייפית; מומלץ להזמין מקום מראש.", "דיקלה אלמגור, איילה בר · 24/08/2016"),
    ("נונו", "מסעדה", "הוד השרון", "הומלצה לעומת ג'וז ודניאל.", "עינת שיין · 24/08/2016"),
    ("עליזה — קוסקוס", "קוסקוס ביתי / הזמנה", "לפי אתר", "קוסקוס לשישי; לינק לתפריט בהודעה.", "הילה רבינוביץ אוקונסקי · 24/08/2016 · alizascouscous.com"),
    ("אושי אושי", "סושי", "קניון הירוקה, כפר סבא", "סושי טעים; כשר, סגור בשבת.", "ציפי שקד · 27/08/2016"),
    ("ריבר", "סושי / אוכל אסייתי", "שכונה B, הירוקה כפר סבא", "סושי טעים; פתוח בשבת, לא כשר.", "ציפי שקד · 27/08/2016"),
    ("מיתוס", "מסעדה / דוכן", "תל אביב; דוכן רמת החייל (שישי)", "אוכל כשר טרי; דוכן בשישי ברמת החייל.", "דנה הראל · 18/01/2017"),
    ("האחים", "מסעדה", "תל אביב", "בראנץ' בשישי (הוזכר ליד משייה במלון מנדליי).", "דנה הראל · 19/01/2017"),
    ("בנדיקט", "ארוחת בוקר", "תל אביב", "פופולרי; חלק מהחברות מציינות עומס/מיושן.", "מאיה אהרוני, דנה הראל · 19/01/2017"),
    ("גמני", "בית קפה / בראנץ'", "רחוב רוטשילד, תל אביב", "המלצה לארוחת בוקר.", "אורנה ורכובסקי · 19/01/2017"),
    ("משייה (מלון מנדליי)", "מסעדה", "רוטשילד 12, תל אביב", "ארוחות בוקר.", "דנה הראל · 19/01/2017"),
    ("מלון מונטיפיורי", "מלון / מסעדה", "תל אביב", "ארוחת בוקר שווה לדעת אורנה.", "אורנה ורכובסקי · 19/01/2017"),
    ("נורמן", "בית קפה / בראנץ'", "רחוב מונטיפיורי, תל אביב", "הומלץ על ידי מירי יעקובי וחלי.", "חלי סלוצקי לוינטל · 19/01/2017"),
    ("דלאל", "מסעדה / בראנץ'", "נווה צדק, תל אביב", "בין ההמלצות החזקות לארוחת בוקר.", "חלי סלוצקי לוינטל · 19/01/2017"),
    ("מנטה ריי", "מסעדה", "על הים (תל אביב–יפו)", "הוזכר בהקשר ארוחת בוקר.", "דנה הראל · 19/01/2017"),
    ("פועה", "מסעדה", "שוק הפשפשים, תל אביב", "ארוחת בוקר.", "+972 52-633-3776 · 19/01/2017"),
    ("בוקה", "מסעדה", "אחד העם, תל אביב", "מעולה לדעת דנה.", "אסנת פלג, דנה הראל · 19/01/2017"),
    ("אורנה ואלה / רביבה וסיליה", "בית קפה", "שינקין / האזור", "הוזכרו בהקשר ארוחת בוקר.", "+1 (415) 867-4079 · 19/01/2017"),
    ("סיאטרה / סאן", "מסעדה", "בי אנד סאן, תל אביב", "מאיה גולי ממליצה.", "מאיה גולי · 19/01/2017"),
    ("קפה נואר", "בית קפה", "נחמני, תל אביב", "אין ארוחות בוקר — פותחים בצהריים (תיקון לדנה הראל).", "דנה הראל · 19/01/2017"),
    ("גוהר", "פרסית", "אזור התעשייה כפר סבא", "טעים מאוד; להזמין מראש. טלפון בצ'אט: 09-7664533.", "סיגל ראב · 05/04/2017"),
    ("גומבה", "איטלקית", "רעננה", "מסעדה איטלקית; הומלצה בקבוצה — טעים, טרי ובמחיר סביר. הוזכרה גם בהקשר משלוחים (כפר סבא).", "איילה בר · 23/03/2020 · אזכורים נוספים בקבוצה 2025–2026"),
    ("פסטה לוקו", "איטלקית", "חדרה", "פסטה לוקו בחדרה; מסעדה איטלקית קטנה וחמודה.", "דורין ליבר · 10/12/2023, 13:54"),
    ("Timo", "איטלקית", "טירה", "היינו ב-TIMO בטירה; מסעדה איטלקית ממש משפחתית נחמדה וטעימה. מומלץ.", "חן ארזי מרקו · 24/12/2022, 16:30"),
    ("צבעים בקפה", "בית קפה", "בפארק כפס", "צבעים בקפה בפארק כפס. ליד האיצטדיון", "עדנה גל קידר · 18/06/2025, 14:49"),
    ("אל דנטה", "איטלקית", "אושיסקין, ירושלים", "מסעדה איטלקית קטנה וחמודה עם כשרות (אל דנטה).", "מירי מרגולין · 10/08/2025, 12:50"),
    ("פונדק עין כרם", "פונדק / מסעדה", "עין כרם, ירושלים", "ליד המעיין; באותה הודעה עם ״אדום״ בתחנת הרכבת הישנה ושאר המלצות ירושלים.", "ריס פריבר · 10/08/2025, 14:33"),
    ("ברסרי בעין כרם", "בראסרי", "עין כרם, ירושלים", "בצ'אט נכתב ״בראסרי בעין כרם״; נהדרת תמיד — ציטוט מהמלצת ריס פריבר.", "ריס פריבר · 10/08/2025, 14:33"),
    ("טלביה", "בית תה", "מתחת לתיאטרון ירושלים", "לשעבר ״בית התה של יאן״; היום נקרא טלביה; באותה רשימת המלצות ירושלים.", "ריס פריבר · 10/08/2025, 14:33"),
    ("פוקאצ'ה בר", "מסעדה", "ירושלים", "נהדרת תמיד; באותה הודעה עם אדום, פונדק עין כרם, ברסרי בעין כרם וטלביה.", "ריס פריבר · 10/08/2025, 14:33"),
    ("נומי", "בית קפה", "כפר מונש", "קפה נומי בכפר מונש; באותה הודעה עם קפה מלצ'ט בתל מונד.", "+972 54-663-3531 · 24/08/2023, 19:52"),
    ("אדמה (זיכרון)", "מסעדה", "זכרון יעקב", "הוצעה למסעדה פתוחה בשבת למשפחה גדולה.", "מיכל סטפק · 09/08/2017"),
    ("אנגוס", "מסעדת בשרים", "חיפה", "הוצע ליד ניר דוד / אזור הצפון.", "איילה בר · 09/08/2017"),
    ("צל תמר", "מסעדה", "אגדות יעקב / אשדות יעקב", "מעולה לילדים ואוכל; לבדוק שעות שבת לפי שרשור.", "תמי בנארצי · 09/08/2017"),
    ("דג דגן (dagdagan)", "מסעדת דגים", "קיבוץ חפציבה", "דגים מעולה, אזור משחקים; פתוח בשבת לפי ציפי.", "ציפי שקד · 09/08/2017 · dagdagan.co.il"),
    ("אלבית (Albait)", "מסעדה", "בית שאן–אזור", "לינק הופץ בשרשור מסעדות ליד ניר דוד.", "+972 54-223-0180 · 09/08/2017"),
    ("מסעדת הארזים", "לבנונית", "ליד נהריה", "מזרחית עממית; ליד נהריה.", "תמי בנארצי · 06/10/2017"),
    ("מסעדה טבעונית (ויצמן)", "טבעונית", "כפר סבא — רחוב ויצמן מול העירייה", "מקסימה בחוץ עם עציצים, אוכל מעולה.", "ליאת ריקליס אורן · 24/10/2017"),
    ("קזן", "מסעדה", "רעננה", "כמעט כל המסעדות ברעננה כשרות; קזן חדשה וטובה.", "רותה לאור · 02/11/2017"),
    ("אלבמה", "מסעדת בשרים מעושנים", "נתניה", "קשה להזמין; הופיעה הזמנה להעברת מקום בקבוצה.", "הודעה מועברת · לפי שרשור 2018"),
    ("מוריס", "מסעדת בשרים", "שוק מחנה יהודה, ירושלים", "אותנטי בשוק.", "+972 52-487-5558 · 28/08/2017"),
    ("עזורה / פתיליות", "מסעדה", "שוק מחנה יהודה", "טעים וזול לדעת דנה הראל.", "דנה הראל · 28/08/2017"),
    ("מסעדת מחנה יהודה / מחניודה", "מסעדה", "ירושלים / השוק", "מצוינת לדעת חברות; קשור לאסף גרניט.", "מירב ערן · 21/03/2019"),
    ("הדסון", "סטייקים / בשרים", "רחוב הברזל, תל אביב", "פתוחה בשבת; סטייקים.", "אריאלה איטקיס · 02/06/2018"),
    ("האחים (אבן גבירול)", "מסעדה", "אבן גבירול, תל אביב", "מיוחדת לדעת עליזה ולטר.", "עליזה ולטר · 02/06/2018"),
    ("מיט בר", "בשרים", "הרצליה", "טעים בטירוף; אווירה נעימה בערב.", "מורן חן · 11/06/2018"),
    ("המקדש", "בשרים", "אושילנד", "מסעדת בשרים חדשה; מקורות חברות.", "אסנת ורדי · 11/06/2018"),
    ("אבו חסן (טירה)", "חומוס / מזרח תיכוני", "טירה", "הוזכר בהקשר מסעדה מקומית.", "דנה אידו · 17/06/2018"),
    ("באגסי", "בראנץ'", "פלורנטין, תל אביב", "ארגון בראנץ' לקבוצה; דברו בפרטי.", "חני דינור · 09/04/2018"),
    ("קיסו", "אסייתית", "קרית אונו", "שווה לדעת אביבית.", "אביבית וינברג · 01/07/2018"),
    ("טאטי", "מסעדה", "יהוד", "המלצה לאזור יהוד.", "מרים בן יעקב · 01/07/2018"),
    ("Zink", "מסעדה", "יהוד", "נחמד באזור.", "יהודית אשל · 01/07/2018"),
    ("מסעדת אסתר", "מסעדה", "יהוד", "מקסימה וטעימה.", "שירלי רייכמן · 01/07/2018"),
    ("הלב הרחב", "מזרחי / ביסטרו", "אילת, מול הקניון", "עיצוב ביסטרו; יש לבדוק אם נפתח מחדש אחרי שרפה (צוין בצ'אט).", "חלי סלוצקי לוינטל, עינת שיין · 01/07/2018"),
    ("PE PE", "מעדנייה", "קניון הירוקה", "לכבד עוף / מעדנייה.", "גילי דואר · 21/04/2016"),
    ("שוק העיר (מגדל B)", "שוק / אוכל", "תל אביב", "פחות עמוס, הרבה אוכל.", "שרון גולן · 21/04/2016"),
    ("בני ציון", "מכולת / מעדנייה", "אזור השרון", "כבדי עוף ומעדניות.", "מיה דקל · 21/04/2016"),
    ("בר אסייתי", "אסייתית", "רחוב הבנים, הוד השרון", "נהדרת לדעת אביבית.", "אביבית וינברג · 26/09/2018"),
    ("איוטאיה", "תאילנדית", "הוד השרון", "מסעדה תאילנדית מעולה.", "שני פולק · 24/05/2018"),
    ("גלידה יונק", "מסעדה רומנית", "קבוץ גלויות 29, חיפה (ליד שוק הפשפשים)", "מומלצת לחיפה מול המושבה/נמל.", "שרה בוגן · 14/12/2018"),
    ("ג'וז ודניאל / גלריה אלמוג", "מסעדה + בית קפה", "תל יצחק", "קפה וארוחות בוקר; לבוא רעבים לדעת הממליצה.", "+972 50-555-9156 · 23/12/2018"),
    ("נישי", "אסייתית", "מלון ווסט, נתניה", "מדהימה לדעת שרה בוגן.", "שרה בוגן · 26/03/2019"),
    ("קוביה", "אוכל ערבי / אסלית", "יפו העתיקה", "טובה לאורחים מחו״ל.", "ריקי הורן · 27/07/2019"),
    ("מנסורה", "שף / מטבח ערבי", "יפו", "שף מצוין, יוצאי השילה.", "+972 54-447-0034 · 27/07/2019"),
    ("מונטיפיורי (יקב)", "יקב ומסעדה", "יקב מונטיפיורי", "יקב; המסעדה הוזכרה כ״מטרפת״.", "+972 54-450-7710 · 17/04/2018"),
    ("חומוס מלול ובלאדי", "חומוס", "אבו חסן יפו — ליד מאפייה", "לא במסעדה עצמה; אחרי הכיכר השנייה ימינה.", "ציפי שקד · 18/09/2016"),
    ("bibo vino", "יין ואוכל", "לא צוין", "הוזכר בשאלה לקבוצה; לבדוק עדכונים.", "סיגל ראב · 28/03/2017"),
    ("תיאו", "מסעדה", "רעננה", "נשאלה חוות דעת בקבוצה.", "דיאנה אידלמן · 29/05/2017"),
    ("שוק מחנה יהודה (מוריס ועוד)", "שוק ומסעדות", "ירושלים", "מסעדות אותנטיות בשוק.", "ענבל יבין פרטל · 28/08/2017"),
    ("לחם יין", "מסעדה / בר", "יהוד", "בין המסעדות שצוינו ליד אסתר וזינק.", "יהודית אשל · 01/10/2018"),
    ("קפה אוגוסט (לשעבר ג'ו)", "בית קפה + משלוחים", "צופית / סביבה", "משלוחי מנות בבית בתקופת קורונה; מומלץ בקבוצה.", "הודעות 2020"),
    ("פיאנו / זיגי", "פיצה", "משלוחים למושב", "הוזכרו בהקשר פיצה למושב.", "שרון גולן · 2020"),
    ("בופה (אזור תעשייה כפר סבא)", "אוכל מוכן / עמותה", "כפר סבא", "אוכל טעים; תורמים שאריות — לבדוק שעות לפני חג.", "+972 52-892-9144 · 05/04/2017"),
    ("שגב (הרצליה)", "מסעדה", "הרצליה", "מסעדה מעולה — ציטוט מתוך שיחה בקבוצה.", "שרשור · 05/2018"),
    ("סושימוטו", "סושי", "ניר עם (עוטף)", "מתוך רשימת העוטף בצ'אט.", "טלפון בפרסום: 050-6722297 · 07/2018"),
    ("מידס", "ברזילאית", "ברור חיל (עוטף)", "מתוך רשימת העוטף.", "טלפון בפרסום: 054-6744197 · 07/2018"),
    ("פסטה וזהו", "פסטה / מסעדה", "יכיני (עוטף)", "מתוך רשימת העוטף.", "טלפון בפרסום: 054-3136321 · 07/2018"),
    ("פטגוניה", "מסעדה", "אור הנר (עוטף)", "מתוך רשימת העוטף.", "טלפון בפרסום: 050-6846728 · 07/2018"),
    ("Sins", "דגים ופירות ים", "כפר עזה (עוטף)", "מתוך רשימת העוטף.", "טלפון בפרסום: 052-2765312 · 07/2018"),
    ("פלאפל נייד (דוכנים)", "פלאפל לאירועים", "ברור חיל (עוטף)", "דוכני פלאפל לאירועים.", "טלפון בפרסום: 052-6510506 · 07/2018"),
    ("בן זגר — בר אקטיבי", "בר לאירועים", "מפלסים (עוטף)", "אירועי בר.", "טלפון בפרסום: 052-2768663 · 07/2018"),
    ("בית ליבנה", "ארוחות גורמה כפריות", "עין הבשור (עוטף)", "ארוחות בבית כפרי.", "טלפון בפרסום: 052-8284-152 · 07/2018"),
    ("הניסים של השף", "שף פרטי / ארוחות", "צוחר (עוטף)", "ארוחות גורמה בבית פרטי.", "טלפון בפרסום: 052-4329-599 · 07/2018"),
    ("אצל פפו בכרם", "יקב וגלריה", "אור הנר (עוטף)", "לא מסעדה קלאסית — יקב עם אירוח.", "טלפון בפרסום: 050-7200426 · 07/2018"),
]


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_year_from_curated_note(note: str) -> int | None:
    """השנה הראשונה שנמצאת ב-note (למשל «· 24/05/2016»)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", note or "")
    return int(m.group(3)) if m else None


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser(description="חילוץ מסעדות מייצוא WhatsApp ל-data/restaurants.json")
    vg = ap.add_mutually_exclusive_group()
    vg.add_argument(
        "--web-verify",
        action="store_true",
        help="סנן מסעדות לפי נוכחות ברשת (אתר או אזכור בחיפוש Google CSE; דורש GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX)",
    )
    vg.add_argument(
        "--no-web-verify",
        action="store_true",
        help="בטל אימות רשת (ברירת מחדל; עוקף גם RESTAURANT_WEB_VERIFY)",
    )
    ap.add_argument(
        "--since-year",
        type=int,
        metavar="YEAR",
        default=None,
        help="לסרוק רק הודעות משנת YEAR והלאה (מבוסס תאריך בייצוא); בלוק «עוטף» יושמט; CURATED מסונן לפי תאריך ב-note",
    )
    args = ap.parse_args(argv)

    if args.web_verify:
        web_verify = True
    elif args.no_web_verify:
        web_verify = False
    else:
        web_verify = _env_truthy("RESTAURANT_WEB_VERIFY")

    if not CHAT.exists():
        print("Chat not found:", CHAT)
        return 1
    text = CHAT.read_text(encoding="utf-8", errors="replace")
    min_year = args.since_year
    entries: list[dict] = []
    if min_year is None:
        entries.extend(extract_gaza_food_block(text))
    else:
        print(f"Skipping Gaza envelope block (no per-message dates; use full export without --since-year to include).")
    scanned = extract_restaurants_from_chat_scan(text, slug_id=slug_id, min_year=min_year)
    entries.extend(scanned)
    print(f"Chat scan: {len(scanned)} raw rows (before merge)" + (f" (messages from {min_year}+ only)" if min_year else ""))
    for name, rtype, loc, recommendation, source_line in CURATED:
        if min_year is not None:
            cy = _parse_year_from_curated_note(source_line)
            if cy is None or cy < min_year:
                continue
        entries.append(
            {
                "id": slug_id("curated:" + name + loc),
                "name": name,
                "restaurant_type": rtype,
                "location": loc,
                "note": source_line,
                "extra_info": recommendation,
            }
        )
    uniq = dedupe_merge_and_assign_websites(entries)

    if web_verify:
        if not web_verify_configured():
            print(
                "אימות רשת מופעל (--web-verify או RESTAURANT_WEB_VERIFY=1) אבל חסרים משתני סביבה.\n"
                "הגדירו GOOGLE_CSE_API_KEY ו-GOOGLE_CSE_CX (Google Custom Search API + מנוע חיפוש מתוכנת),\n"
                "או הריצו עם --no-web-verify.",
                file=sys.stderr,
            )
            return 1
        try:
            uniq, wstats = filter_by_web_presence(uniq, root=ROOT)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(
            f"Web verify: kept {wstats['kept']}, dropped {wstats['dropped']}, "
            f"cache hits {wstats['cached_hits']}, API calls {wstats['api_calls']}"
        )

    uniq.sort(key=lambda x: (x["name"] or "").lower())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    filled = sum(1 for r in uniq if (r.get("website") or "").strip())
    print(f"Wrote {len(uniq)} entries to {OUT} ({filled} with website)")
    build_script = ROOT / "scripts" / "build_view_restaurants.py"
    if build_script.exists():
        r = subprocess.run([sys.executable, str(build_script)], cwd=str(ROOT))
        if r.returncode != 0:
            print("Warning: build_view_restaurants.py failed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
