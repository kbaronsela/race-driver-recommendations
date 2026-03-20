#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze entries with empty field: extract phrases from name+note that might map to a field."""
import json
import re
from pathlib import Path
from collections import Counter

path = Path(__file__).resolve().parent.parent / "data" / "whatsapp_recommendations.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
no_field = [e for e in data if not (e.get("field") or "").strip()]

# Common profession/request patterns in Hebrew (substrings to look for and suggested field)
PATTERNS = [
    (r"מורה\s+ל(?:שון|לשון)", "מורים פרטיים"),
    (r"לשון", "מורים פרטיים"),
    (r"מורה\s+ל(?:אנגלית|עברית)", "מורים פרטיים"),
    (r"פסיכולוג", "פסיכולוגיה"),
    (r"מאבחן\s+דידקטי", "מורים פרטיים"),
    (r"הוראה מתקנת", "מורים פרטיים"),
    (r"רופא שיניים|רופאת שיניים|שיננית|אורטודנט", "רפואת שיניים"),
    (r"חשמלאי|חשמל", "חשמל"),
    (r"אינסטלטור|אינסטלציה", "אינסטלציה"),
    (r"נגר|נגרות", "נגרות"),
    (r"צבע|צבעי|צביעה", "צבע"),
    (r"מזגן|מיזוג|מזגנים", "מיזוג"),
    (r"מונית|נהג מונית", "מוניות"),
    (r"מספרה|ספר לשיער", "מספרה"),
    (r"מנעולן", "מנעולן"),
    (r"הדברה|מדביר", "הדברה"),
    (r"ניקיון|נקיון|מנקה|עוזרת בית", "ניקיון"),
    (r"תפירה|תופרת", "תפירה"),
    (r"קייטרינג", "קייטרינג"),
    (r"אילוף כלבים|מאלף כלבים", "אילוף כלבים"),
    (r"מחשבים|טכנאי מחשבים", "טכנאי מחשבים"),
    (r"טכנאי מכשירי חשמל|מדיח|תנורים|מכונת כביסה", "טכנאי מכשירי חשמל"),
    (r"תריסים", "תריסים"),
    (r"אלומיניום", "אלומיניום"),
    (r"אזעקה", "אזעקה"),
    (r"הובלה|מוביל", "הובלות"),
    (r"עיסוי|מסאג|מעסה|רפלקסולוג", "עיסוי"),
    (r"וטרינר", "רפואה"),
    (r"רופא|רופאה|מרפאה", "רפואה"),
    (r"בר מצווה|ברית", "מורים פרטיים"),  # מורה לבר מצווה
    (r"גננת|סייעת גן", "גני ילדים"),
    (r"פיזיותרפיסט|פיזיותרפיה", "רפואה"),
    (r"קוסמטיקאית|מניקור|פדיקור|לק גל", "קוסמטיקה"),
    (r"מדריך טיולים|מדריכת טיולים", "תיירות"),
    (r"שחיה|שחייה|בריכה", "שחייה"),
    (r"ספרית|ספרות", "מספרה"),
    (r"ביטוח", "ביטוח"),
    (r"עורך דין|עורכת דין", "משפטים"),
    (r"רואה חשבון|רואת חשבון", "ראיית חשבון"),
    (r"גז", "גז"),
    (r"זגג|זגגות", "זגגות"),
    (r"איטום", "איטום"),
    (r"פרגולה|פרגולות", "נגרות"),
    (r"דודים|דוד שמש", "דודים"),
    (r"עובש|טיפול בעובש", "איטום"),
]

def find_suggestions():
    suggested = []  # (phrase_from_text, suggested_field)
    for e in no_field:
        name = e.get("name", "") or ""
        note = e.get("note", "") or ""
        text = name + " " + note
        for pattern, field in PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                phrase = m.group(0).strip()
                suggested.append((phrase[:50], field))
                break  # one suggestion per entry
    return suggested

suggestions = find_suggestions()
# Count (phrase, field) to see which keywords would help most
counts = Counter((p, f) for p, f in suggestions)
# Also collect unique phrases we're missing
missing_phrases = Counter()
for e in no_field:
    name = (e.get("name") or "").strip()
    note = (e.get("note") or "").strip()[:200]
    if not name and not note:
        continue
    # If name looks like "X - profession" or "X profession"
    if "מורה" in name or "מורה" in note:
        if "לשון" in name or "לשון" in note or "לשון" in name:
            missing_phrases["מורה ללשון / לשון"] += 1
    if "מנקה" in name or "מנקה" in note or "עוזרת" in name or "עוזרת" in note:
        missing_phrases["מנקה/עוזרת"] += 1
    if "ספר" in name and "מספרה" not in name:
        if "שיער" in name or "גברים" in note or "ספר" in note:
            missing_phrases["ספר/מספרה"] += 1
    if "יוגה" in name or "יוגה" in note:
        missing_phrases["יוגה"] += 1
    if "גננת" in name or "גננת" in note:
        missing_phrases["גננת"] += 1
    if "ביטוח" in name or "ביטוח" in note:
        missing_phrases["ביטוח"] += 1
    if "פיזיותרפיה" in name or "פיזיותרפיה" in note or "פיזיותרפיסט" in name:
        missing_phrases["פיזיותרפיה"] += 1
    if "קוסמטיק" in name or "קוסמטיק" in note or "מניקור" in note or "לק גל" in note:
        missing_phrases["קוסמטיקה"] += 1
    if "שחיה" in name or "שחייה" in name or "שחיה" in note:
        missing_phrases["שחייה"] += 1
    if "טיולים" in name or "מדריך טיולים" in note or "מדריכת טיולים" in note:
        missing_phrases["מדריך טיולים"] += 1
    if "רואה חשבון" in name or "רואה חשבון" in note or "מנהל חשבונות" in note:
        missing_phrases["רואה חשבון"] += 1
    if "עורך דין" in name or "עורך דין" in note:
        missing_phrases["עורך דין"] += 1
    if "זגג" in name or "זגג" in note or "זגגות" in note:
        missing_phrases["זגג"] += 1
    if "גז" in name or "טכנאי גז" in note:
        missing_phrases["גז"] += 1
    if "דודים" in name or "דוד שמש" in note:
        missing_phrases["דודים"] += 1
    if "איטום" in name or "איטום" in note or "עובש" in note:
        missing_phrases["איטום"] += 1
    if "פרגול" in name or "פרגולה" in note:
        missing_phrases["פרגולה"] += 1

# Output: suggested new keywords
out_path = Path(__file__).resolve().parent.parent / "data" / "suggested_keywords.txt"
with open(out_path, "w", encoding="utf-8") as out:
    out.write("Matches from regex (phrase -> field):\n")
    for (p, f), c in counts.most_common(80):
        out.write(f"  {c:4d}  {p!r} -> {f}\n")
    out.write("\n\nMissing phrase counts (from name/note):\n")
    for phrase, c in missing_phrases.most_common(40):
        out.write(f"  {c:4d}  {phrase}\n")
print("Wrote", out_path)
print("Total no-field:", len(no_field))
print("Matched by pattern:", len(suggestions))
