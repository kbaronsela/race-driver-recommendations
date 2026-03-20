#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract recommended contacts from a WhatsApp export ZIP (Hebrew chat + VCF attachments only).
Produces JSON: name, phone, field, from_moshav, note, extra_info. Phone numbers in plain text are ignored.
Contact names are trimmed of leading non-letter/non-digit junk (e.g. leading '.', symbols, marks).

Usage:
  python scripts/whatsapp_to_recommendations.py [path_to.zip] [--output path.json]

Default ZIP: G:\\My Drive\\ai\\whatsapp test bck.zip
Default output: data/entries.json
"""
import re
import json
import zipfile
import argparse
import unicodedata
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = r"G:\My Drive\ai\whatsapp test bck.zip"
DEFAULT_OUT = ROOT / "data" / "entries.json"

from additional_info import infer_additional_info  # noqa: E402

# WhatsApp chat line: 18/06/2015, 16:33 - ‎‫סיגל ראב‬‎: message
CHAT_LINE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*(.+?):\s*(.*)$",
    re.UNICODE,
)
# continuation line (no date) - part of previous message
# Attachment in chat: "אורית חשבון.vcf (file attached)" or "something.vcf (file attached)"
VCF_ATTACHED_RE = re.compile(r"(.+?\.vcf)\s*\(file attached\)", re.UNICODE | re.IGNORECASE)

# Israeli phone: strip +, -, spaces; 972... -> 0...; output digits only (05x...)
def normalize_phone(s):
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if digits.startswith("972"):
        digits = "0" + digits[3:]
    if digits.startswith("0") and len(digits) == 10:
        return digits
    if len(digits) == 9 and digits[0] in "23456789":
        return "0" + digits
    return digits


def clean_contact_name_start(s):
    """
    Strip leading characters that are not Unicode letters (L*) or numbers (N*).
    Removes leading '.', '-', emoji, RTL marks, spaces, etc. Keeps names like '054 נועה'.
    """
    if not s or not str(s).strip():
        return ""
    original = str(s).strip()
    i = 0
    while i < len(original):
        cat = unicodedata.category(original[i])
        if cat[0] in ("L", "N"):
            break
        i += 1
    out = original[i:].strip()
    return out if out else original


def parse_vcard(content):
    """Parse one VCF content. Return (name, phone) or (None, None)."""
    name = None
    phone = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("FN:"):
            name = line[3:].strip()
        elif "TEL" in line.upper():
            # item1.TEL;waid=...:+972 54-490-9706  or TEL;TYPE=CELL:050-1234567
            m = re.search(r"[\d\-\+\s]{9,}", line)
            if m:
                phone = normalize_phone(m.group(0))
        if name and phone:
            break
    if not name and "N:" in content:
        # N:;Family;Given;;;
        for line in content.splitlines():
            if line.startswith("N:"):
                parts = line[2:].split(";")
                if len(parts) >= 2:
                    name = (parts[2] + " " + parts[1]).strip() or parts[1]
                break
    name = clean_contact_name_start(name or "")
    return (name, phone or "")


def load_vcf_from_zip(zip_path):
    """Return dict: normalized_phone -> {name, vcf_filename}, and vcf_filename_lower -> (name, phone)."""
    by_phone = {}
    by_filename = {}
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".vcf"):
                continue
            try:
                with z.open(info) as f:
                    raw = f.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            name, phone = parse_vcard(raw)
            if not phone:
                continue
            base = Path(info.filename).name
            stem = base.replace(".vcf", "")
            display = clean_contact_name_start(name) if name else clean_contact_name_start(stem)
            if not display:
                display = stem
            by_phone[phone] = {"name": display, "vcf_filename": base}
            by_filename[base.lower()] = (display, phone)
            # also map without .vcf for flexible matching
            by_filename[stem.lower()] = (display, phone)
    return by_phone, by_filename


def parse_chat_messages(zip_path):
    """Yield (datetime_str, sender, message_text) for each message. Multi-line messages merged."""
    chat_name = None
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if not info.filename.endswith(".txt"):
                continue
            chat_name = info.filename
            break
    if not chat_name:
        return
    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(chat_name) as f:
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    current_date = current_sender = None
    current_parts = []
    for line in lines:
        m = CHAT_LINE_RE.match(line)
        if m:
            if current_parts:
                text = "\n".join(current_parts).strip()
                if text:
                    yield (current_date, current_sender, text)
            current_date = m.group(1) + " " + m.group(2)
            current_sender = m.group(3).strip()
            current_parts = [m.group(4)]
        else:
            if current_parts is not None and line.strip():
                current_parts.append(line.strip())
    if current_parts:
        text = "\n".join(current_parts).strip()
        if text:
            yield (current_date, current_sender, text)


def find_vcf_mentions_and_context(zip_path, by_filename, window_before=5):
    """For each message that attaches a VCF, yield (vcf_filename, sender, message_text, context_messages)."""
    messages = list(parse_chat_messages(zip_path))
    for i, (dt, sender, text) in enumerate(messages):
        for m in VCF_ATTACHED_RE.finditer(text):
            vcf_name = m.group(1).strip()
            context = []
            for j in range(max(0, i - window_before), i):
                context.append(messages[j])
            yield (vcf_name, sender, text, context)


def normalize_infer_text(s):
    """Collapse weird spaces / direction marks so 'דר ' etc. match VCF/chat exports."""
    if not s:
        return ""
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Simple keyword -> field mapping (Hebrew). First match wins. More specific first.
FIELD_KEYWORDS = [
    ("טכנאי תנורים", "טכנאי מכשירי חשמל"),
    ("תנורי אפיה", "טכנאי מכשירי חשמל"),
    ("תנורי אפייה", "טכנאי מכשירי חשמל"),
    ("מתקן תנורים", "טכנאי מכשירי חשמל"),
    ("תנורים", "טכנאי מכשירי חשמל"),
    ("תריסים חשמליים", "תריסים"),
    ("תריסים", "תריסים"),
    ("שיעורי נגינה", "נגינה"),
    ("מורה לנגינה", "נגינה"),
    ("מורים לנגינה", "נגינה"),
    ("מורה לתופים", "נגינה"),
    ("מורה לפסנתר", "נגינה"),
    ("מורה לגיטרה", "נגינה"),
    ("מורה לחליל", "נגינה"),
    ("גיטרה", "נגינה"),
    ("תופים", "נגינה"),
    ("כלי נגינה", "נגינה"),
    ("נגינה", "נגינה"),
    ("מורה להוראה מתקנת", "מורים פרטיים"),
    ("הוראה מתקנת", "מורים פרטיים"),
    ("מורה פרטי", "מורים פרטיים"),
    ("מורה למתמטיקה", "מורים פרטיים"),
    ("מורה ללשון", "מורים פרטיים"),
    ("מורה לאנגלית", "מורים פרטיים"),
    ("מורה לפיזיקה", "מורים פרטיים"),
    ("פיזיקה", "מורים פרטיים"),
    ("מורה לנהיגה", "נהיגה"),
    ("מורה נהיגה", "נהיגה"),
    ("מורה לבר מצווה", "מורים פרטיים"),
    ("מאבחן דידקטי", "אבחון"),
    ("מאבחנת דידקטית", "אבחון"),
    ("מאבחנת פסיכודידקטית", "אבחון"),
    ("מאבחנת", "אבחון"),
    ("מאבחן", "אבחון"),
    ("מתמטיקה", "מורים פרטיים"),
    ("חשבון", "מורים פרטיים"),
    ("לשון", "מורים פרטיים"),
    ("רופא שיניים", "רפואת שיניים"),
    ("רופאת שיניים", "רפואת שיניים"),
    ("מרפאת שיניים", "רפואת שיניים"),
    ("מרכז שיניים", "רפואת שיניים"),
    ("מכון שיניים", "רפואת שיניים"),
    ("מכבי דנט", "רפואת שיניים"),
    ("דנט", "רפואת שיניים"),
    ("שיניים", "רפואת שיניים"),
    ("שיננית", "רפואת שיניים"),
    ("אורטודנט", "רפואת שיניים"),
    ("אורתודנט", "רפואת שיניים"),
    ("אורתודנטית", "רפואת שיניים"),
    ("רופא אף אוזן גרון", "רפואה"),
    ("רופאת אף אוזן גרון", "רפואה"),
    ("אף אוזן גרון", "רפואה"),
    ("א.א.ג", "רפואה"),
    ("ד\"ר", "רפואה"),
    ("ד״ר", "רפואה"),  # Hebrew gershayim U+05F4
    ("דר'", "רפואה"),
    ("דר׳", "רפואה"),  # Hebrew geresh U+05F3
    ("דר.", "רפואה"),
    ("דר ", "רפואה"),
    ("רופא", "רפואה"),
    ("רופאה", "רפואה"),
    ("מרפאה", "רפואה"),
    ("נוירולוג", "רפואה"),
    ("קרדיולוגית", "רפואה"),
    ("קרדיולוג", "רפואה"),
    ("אורולוגית", "רפואה"),
    ("אורולוג", "רפואה"),
    ("גסטרולוג", "רפואה"),
    ("גסטרולוגית", "רפואה"),
    ("גסטרו", "רפואה"),
    ("שניידר", "רפואה"),
    ("פסיכולוג", "פסיכולוגיה"),
    ("פסיכולוגית", "פסיכולוגיה"),
    ("פסכולוגית", "פסיכולוגיה"),
    ("פסכולוג", "פסיכולוגיה"),
    ("CBT", "פסיכולוגיה"),
    ("Cbt", "פסיכולוגיה"),
    ("cbt", "פסיכולוגיה"),
    ("וטרינר", "רפואה"),
    ("טכנאי מזגנים", "מיזוג"),
    ("איש מזגנים", "מיזוג"),
    ("מתקן מזגנים", "מיזוג"),
    ("מזגנים", "מיזוג"),
    ("מזגן", "מיזוג"),
    ("מיזוג", "מיזוג"),
    ("הדפסת חולצות", "דפוס"),
    ("מדפיס חולצות", "דפוס"),
    ("הדפסה על חולצות", "דפוס"),
    ("בית דפוס", "דפוס"),
    ("גרפיקאית", "דפוס"),
    ("גרפיקה", "דפוס"),
    ("דפוס", "דפוס"),
    ("חולצות", "דפוס"),
    ("חשמלאי רכב", "מוסך"),
    ("טכנאי רכב", "מוסך"),
    ("מוסך", "מוסך"),
    ("חשמלאי", "חשמל"),
    ("חשמל", "חשמל"),
    ("הנדימן", "הנדימן"),
    ("אינסטלטור", "אינסטלציה"),
    ("אינסטלציה", "אינסטלציה"),
    ("ביובית", "אינסטלציה"),
    ("ביוב", "אינסטלציה"),
    ("נגר", "נגרות"),
    ("נגרות", "נגרות"),
    ("צבע", "צבע"),
    ("צבעי", "צבע"),
    ("נהג מונית", "מוניות"),
    ("מונית", "מוניות"),
    ("קלינאות תקשורת", "פארא-רפואה"),
    ("קלינאית תקשורת", "פארא-רפואה"),
    ("קלינאי תקשורת", "פארא-רפואה"),
    ("ריפוי בעיסוק", "פארא-רפואה"),
    ("מרפא בעיסוק", "פארא-רפואה"),
    ("מרפאה בעיסוק", "פארא-רפואה"),
    ("דיאטנית", "פארא-רפואה"),
    ("דיאטן", "פארא-רפואה"),
    ("תזונאי", "פארא-רפואה"),
    ("תזונה", "פארא-רפואה"),
    ("דיאטה", "פארא-רפואה"),
    ("פיזיותרפיה", "פארא-רפואה"),
    ("פיזיותרפיסט", "פארא-רפואה"),
    ("פיזיותרפיסטית", "פארא-רפואה"),
    ("רוקחות", "פארא-רפואה"),
    ("רוקח", "פארא-רפואה"),
    ("רוקחת", "פארא-רפואה"),
    ("מאמנת כושר", "כושר"),
    ("מאמן כושר", "כושר"),
    ("אימון כושר", "כושר"),
    ("אימונים אישיים", "כושר"),
    ("כושר", "כושר"),
    ("חוג רקמה", "חוגים"),
    ("רקמת עמים", "חוגים"),
    ("מלמדת רקמה", "חוגים"),
    ("חוגים", "חוגים"),
    ("חוג ", "חוגים"),
    ("הובלה", "הובלות"),
    ("הובלות", "הובלות"),
    ("מובילים", "הובלות"),
    ("מוביל", "הובלות"),
    ("ספר לקטנים", "מספרה"),
    ("ספר גברים", "מספרה"),
    ("ספרית", "מספרה"),
    ("ספר לכלבים", "מספרה"),
    ("מספרת כלבים", "מספרה"),
    ("ספרית כלבים", "מספרה"),
    ("מספרה", "מספרה"),
    # לא "מספר" לבד — מופיע כ"מספר טלפון" וכו' בהערות
    ("ספר החלקת שיער", "מספרה"),
    ("החלקת שיער", "מספרה"),
    ("ספר רעננה", "מספרה"),
    # לא "ספר" לבד — מתאים גם ל"הספר" (ספר קריאה) בהערות ממוזגות
    ("פן", "מספרה"),
    ("מנעולן", "מנעולן"),
    ("הדברה", "הדברה"),
    ("מדביר", "הדברה"),
    ("עוזרת בית", "ניקיון"),
    ("ניקוי שטיחים", "ניקיון"),
    ("ניקוי ספות", "ניקיון"),
    ("מנקה ספות", "ניקיון"),
    ("שטיחים", "ניקיון"),
    ("ניקיון", "ניקיון"),
    ("נקיון", "ניקיון"),  # תעתיק שגוי נפוץ — מאוחד ל"ניקיון"
    ("מנקה", "ניקיון"),
    ("תפירה", "תפירה"),
    ("תופרת", "תפירה"),
    ("קייטרינג", "קייטרינג"),
    ("פיצריה", "פיצה"),
    ("פיצר", "פיצה"),
    ("פיצה", "פיצה"),
    ("אקדמיה לכלבים", "אילוף כלבים"),
    ("אילוף כלבים", "אילוף כלבים"),
    ("מאלף כלבים", "אילוף כלבים"),
    ("מאלפת", "אילוף כלבים"),
    ("מאלף", "אילוף כלבים"),
    ("גננת", "גני ילדים"),
    ("סייעת", "גני ילדים"),
    ("מתקן מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("מכונת כביסה", "טכנאי מכשירי חשמל"),
    ("מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("טכנאי מדיח", "טכנאי מכשירי חשמל"),
    ("טכנאי מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("טכנאי מייבש", "טכנאי מכשירי חשמל"),
    ("רשתות מחשבים", "טכנאי מחשבים"),
    ("רשת מחשבים", "טכנאי מחשבים"),
    ("איש סיסטם", "טכנאי מחשבים"),
    ("סיסטם", "טכנאי מחשבים"),
    ("טכנאי רשת", "טכנאי מחשבים"),
    ("מחשבים", "טכנאי מחשבים"),
    ("Computers", "טכנאי מחשבים"),
    ("טכנאי מחשבים", "טכנאי מחשבים"),
    ("תיקון טלפונים", "תיקון טלפונים"),
    ("תיקון טלפון", "תיקון טלפונים"),
    ("תיקון פלאפונים", "תיקון טלפונים"),
    ("תיקון פלאפון", "תיקון טלפונים"),
    ("תיקון אייפון", "תיקון טלפונים"),
    ("מתקן טלפונים", "תיקון טלפונים"),
    ("מתקן אייפונים", "תיקון טלפונים"),
    ("טכנאי טלפון", "תיקון טלפונים"),
    ("טכנאי פלאפון", "תיקון טלפונים"),
    ("טכנאי סלולר", "תיקון טלפונים"),
    ("סלולר", "תיקון טלפונים"),
    ("טכנאי מכשירי חשמל", "טכנאי מכשירי חשמל"),
    ("מקרר", "טכנאי מכשירי חשמל"),
    ("אלומיניום", "אלומיניום"),
    ("צלמת", "צילום"),
    ("צלם", "צילום"),
    ("צילומי משפחה", "צילום"),
    ("צילום", "צילום"),
    ("איש אזעקות", "אזעקה"),
    ("אזעקות", "אזעקה"),
    ("אזעקה", "אזעקה"),
    ("אוכל לחיות", "אוכל לחיות"),
    ("מזון לחיות", "אוכל לחיות"),
    ("אוכל לכלבים", "אוכל לחיות"),
    ("אוכל לחתולים", "אוכל לחיות"),
    ("מזון לכלבים", "אוכל לחיות"),
    ("מזון לחתולים", "אוכל לחיות"),
    ("חנות לחיות", "אוכל לחיות"),
    ("פרקטים, טפטים, וילונות", "פרקטים, טפטים, וילונות"),
    ("פרקטים", "פרקטים, טפטים, וילונות"),
    ("פרקט", "פרקטים, טפטים, וילונות"),
    ("טפטים", "פרקטים, טפטים, וילונות"),
    ("טפט", "פרקטים, טפטים, וילונות"),
    ("וילונות", "פרקטים, טפטים, וילונות"),
    ("וילון", "פרקטים, טפטים, וילונות"),
    ("התקנת פרקט", "פרקטים, טפטים, וילונות"),
    ("הדבקת טפט", "פרקטים, טפטים, וילונות"),
    ("נטורופתית", "רפואה משלימה"),
    ("נטורופת", "רפואה משלימה"),
    ("נטורופתיה", "רפואה משלימה"),
    ("כירופרקטית", "רפואה משלימה"),
    ("כירופרקט", "רפואה משלימה"),
    ("כירופרכט", "רפואה משלימה"),
    ("דיקור סיני", "רפואה משלימה"),
    ("דיקור יבש", "רפואה משלימה"),
    ("מדקר", "רפואה משלימה"),
    ("דיקור", "רפואה משלימה"),
    ("שיאצו", "רפואה משלימה"),
    ("שמנים", "רפואה משלימה"),
    ("מסאג'", "עיסוי"),
    ("מסאז'", "עיסוי"),
    ("מסג'יסטית", "עיסוי"),
    ("מסג'יסט", "עיסוי"),
    ("מסאג'יסטית", "עיסוי"),
    ("מסאג'יסט", "עיסוי"),
    ("מעסה", "עיסוי"),
    ("רפלקסולוג", "רפואה משלימה"),
    ("יוגה", "רפואה משלימה"),
    ("קוסמטיקאית", "קוסמטיקה"),
    ("קוסמטיקה", "קוסמטיקה"),
    ("מניקור", "קוסמטיקה"),
    ("פדיקור", "קוסמטיקה"),
    ("לק גל", "קוסמטיקה"),
    ("ג'ל ציפורניים", "קוסמטיקה"),
    ("שחיה", "שחייה"),
    ("שחייה", "שחייה"),
    ("בריכה", "שחייה"),
    ("סוכנת נסיעות", "תיירות"),
    ("סוכן נסיעות", "תיירות"),
    ("סוכנות נסיעות", "תיירות"),
    ("טורס", "תיירות"),
    ("מדריך טיולים", "תיירות"),
    ("מדריכת טיולים", "תיירות"),
    ("רואה חשבון", "ראיית חשבון"),
    ("רואת חשבון", "ראיית חשבון"),
    ("מנהל חשבונות", "ראיית חשבון"),
    ("עו\"ד", "עריכת דין"),
    ("עו״ד", "עריכת דין"),  # Hebrew gershayim U+05F4
    ("עורך דין", "עריכת דין"),
    ("עורכת דין", "עריכת דין"),
    ("זגג", "זגגות"),
    ("זגגות", "זגגות"),
    ("גגן", "גגות"),
    ("מתקן גגות", "גגות"),
    ("גגות", "גגות"),
    ("מרזבים", "גגות"),
    ("מרזב", "גגות"),
    ("עיצוב גינות", "גינון וגיזום"),
    ("גנן גינות", "גינון וגיזום"),
    ("גינון", "גינון וגיזום"),
    ("גנן", "גינון וגיזום"),
    ("גינות", "גינון וגיזום"),
    ("גיזום עצים", "גינון וגיזום"),
    ("גיזום גינות", "גינון וגיזום"),
    ("גוזם", "גינון וגיזום"),
    ("גיזום", "גינון וגיזום"),
    ("אגרונום", "אגרונומיה"),
    ("אגרונומיה", "אגרונומיה"),
    ("יועץ אגרונומי", "אגרונומיה"),
    ("כירורגית", "רפואה"),
    ("כירורג", "רפואה"),
    ("כירורגיה", "רפואה"),
    ("כירוגיה", "רפואה"),  # typo
    ("כירורג שד", "רפואה"),
    ("כירורגית שד", "רפואה"),
    ("פלסטיקאית", "רפואה"),
    ("פלסטיקאי", "רפואה"),
    ("כרורגית", "רפואה"),
    ("כרורג", "רפואה"),
    ("אורתופד", "רפואה"),
    ("אורטופד", "רפואה"),
    ("ראומטולוג", "רפואה"),
    ("ראמוטולג", "רפואה"),
    ("טכנאי גז", "גז, דלק, נפט"),
    ("בלוני גז", "גז"),
    ("מתקין גז", "גז, דלק, נפט"),
    ("גז", "גז, דלק, נפט"),
    ("דלק", "גז, דלק, נפט"),
    ("נפט", "גז, דלק, נפט"),
    ("ממלא גז", "גז, דלק, נפט"),
    ("הספקת דלק", "גז, דלק, נפט"),
    ("קבלן שיפוצים", "שיפוצים"),
    ("שיפוצניק", "שיפוצים"),
    ("שיפוצים", "שיפוצים"),
    ("מרחיק יונים", "הדברה"),
    ("בעיית יונים", "הדברה"),
    ("יונים", "הדברה"),
    ("דודי שמש", "דודים"),
    ("דוד שמש", "דודים"),
    ("דודים", "דודים"),
    ("איטום", "איטום"),
    ("עובש", "איטום"),
    ("פרגולה", "נגרות"),
    ("פרגולות", "נגרות"),
    ("מצברים", "מצברים"),
    ("מצבר", "מצברים"),
    ("החלפת מצבר", "מצברים"),
    ("טכנאי אופניים", "אופניים"),
    ("תיקון אופניים", "אופניים"),
    ("מתקן אופניים", "אופניים"),
    ("אופניים חשמליים", "אופניים"),
    ("חנות אופניים", "אופניים"),
    ("אופניים", "אופניים"),
    ("ביטוח", "ביטוח"),
    ("השכרת ציוד", "השכרת ציוד"),
    ("ציוד ארועים", "השכרת ציוד"),
    ("שולחנות משחק", "השכרת ציוד"),
    ("השכרת משחקים", "השכרת ציוד"),
    ("השכרת כלים", "השכרת ציוד"),
    ("השכרת מכשירים", "השכרת ציוד"),
    ("ציוד להשכרה", "השכרת ציוד"),
    ("השכרה", "השכרת ציוד"),
    ("שף", "קייטרינג"),
    ("שף פרטי", "קייטרינג"),
    ("רפד", "ריפוד"),
    ("צורף", "צורפות"),
    ("תכשיטים", "צורפות"),
    ("תכשיט", "צורפות"),
    ("מסגרות לתמונות", "מיסגור תמונות"),
    ("תמונות מיסגור", "מיסגור תמונות"),
    ("מיסגור תמונות", "מיסגור תמונות"),
    ("ממסגר תמונות", "מיסגור תמונות"),
    ("מסגור תמונות", "מיסגור תמונות"),
    ("מיסגור", "מיסגור תמונות"),
    ("מרצף", "ריצוף"),
    ("ריצוף", "ריצוף"),
    ("רצף", "ריצוף"),
    ("מסגר", "מסגר"),
    ("רופא עיניים", "רפואה"),
    ("רופאת עיניים", "רפואה"),
    ("רופא נשים", "רפואה"),
    ("רופאת נשים", "רפואה"),
    ("גינקולוגית", "רפואה"),
    ("גינקולוג", "רפואה"),
    ("אנדוקרינולוגית", "רפואה"),
    ("אנדוקרינולוג", "רפואה"),
    ("פרופ'", "רפואה"),
    ("פרופ׳", "רפואה"),  # Hebrew geresh U+05F3
    ("פרופ", "רפואה"),
    ("מתקין מקלחונים", "מקלחונים"),
    ("איש מקלחונים", "מקלחונים"),
    ("מקלחונים", "מקלחונים"),
    ("מקלחון", "מקלחונים"),
    ("אופטימטריסט", "אופטיקה"),
    ("אופטומטריסט", "אופטיקה"),
    ("אופטיקאי", "אופטיקה"),
    ("אופטיקה", "אופטיקה"),
    ("חנות משקפיים", "אופטיקה"),
    ("משקפיים", "אופטיקה"),
    ("בדיקת ראייה", "אופטיקה"),
    ("בדיקת עיניים", "אופטיקה"),
    ("מתרגם", "תרגום"),
    ("נוטריון", "עריכת דין"),
    ("דיאטנית", "רפואה"),
    ("מרפאה בעיסוק", "מרפאה בעיסוק"),
    ("פסיכיאטר", "רפואה"),
    ("פסיכוגראטר", "רפואה"),
    ("פסיכוגריאטר", "רפואה"),
    ("פסיכוגריאטריה", "רפואה"),
    ("גרנטולוג", "רפואה"),
    ("גרונטולוג", "רפואה"),
    ("גריאטר", "רפואה"),
    ("מזגנים ", "מיזוג"),
    ("מתנפחים", "השכרת מתנפחים"),
    ("מצנחי רחיפה", "ספורט"),
    ("פנסיון כלבים", "אילוף כלבים"),
    ("כלבים", "אילוף כלבים"),
    ("מתקין דלתות", "נגרות"),
    ("דלתות", "נגרות"),
    ("בייבי סיטר", "בייביסיטר"),
    ("בייביסיטר", "בייביסיטר"),
    ("ביביסיטר", "בייביסיטר"),
    ("בישול", "קייטרינג"),
    ("סדנת שוקולד", "קייטרינג"),
    ("מכולת", "מכולת"),
    ("צרכניה", "מכולת"),
    ("הצרכניה", "מכולת"),
    ("צימר", "תיירות"),
    ("צימרים", "תיירות"),
    ("מודד", "שמאות"),
    ("שמאי", "שמאות"),
    ("שמאית", "שמאות"),
    ("שמאות", "שמאות"),
    ("פקח", "שמירת טבע"),
    ("רשות הטבע", "שמירת טבע"),
    ("שמירת טבע", "שמירת טבע"),
    ("טוחן אשפה", "אינסטלציה"),
    ("תרנגולות", "חקלאות"),
    ("חקלאי", "חקלאות"),
    ("חקלאות", "חקלאות"),
    ("מאפייה", "קייטרינג"),
    ("עוגות", "קייטרינג"),
    ("דף סוכר", "קייטרינג"),
    ("צמיגים", "מוסך"),
    ("צמיג", "מוסך"),
    ("Tires", "מוסך"),
    ("מדפסת", "דפוס"),
    ("תיקון מדפסת", "דפוס"),
    ("Cleaning", "ניקיון"),
    ("cleaning", "ניקיון"),
    ("סוסים", "רכיבה"),
    ("רכיבה", "רכיבה"),
    ("אילוף", "אילוף כלבים"),
    ("מהנדס", "הנדסה"),
    ("הנדסה", "הנדסה"),
    ("ליטוש", "ניקיון"),
    ("ליטוש אבן", "ניקיון"),
    ("גיהוץ", "כביסה"),
    ("מכבסה", "כביסה"),
    ("מורה לנהיגה", "נהיגה"),
]


def infer_field_from_text(text):
    """Match first keyword in text -> field. Used for name and context."""
    text = normalize_infer_text(text)
    if not text:
        return ""
    for kw, field in FIELD_KEYWORDS:
        if kw in text:
            return field
    # Fallback: case-insensitive (e.g. CBT vs Cbt, Computers vs computers)
    text_cf = text.casefold()
    for kw, field in FIELD_KEYWORDS:
        if kw.casefold() in text_cf:
            return field
    return ""


def infer_field_from_note(note):
    """From note: count keyword matches per field; return the field that appears most often."""
    note = normalize_infer_text(note)
    if not note:
        return ""
    count = defaultdict(int)
    note_cf = note.casefold()
    for kw, field in FIELD_KEYWORDS:
        if not kw:
            continue
        n = note_cf.count(kw.casefold())
        if n:
            count[field] += n
    if not count:
        return ""
    return max(count, key=lambda f: count[f])


def infer_field_from_context(context_messages):
    """Concatenate recent messages and match first keyword -> field."""
    text = " ".join(msg[2] for msg in context_messages)
    return infer_field_from_text(text)


def infer_from_moshav(context_messages, message_text):
    """Check if any context or the message mentions מושב."""
    combined = message_text + " " + " ".join(msg[2] for msg in context_messages)
    return "מושב" in combined or "מהמושב" in combined or "במושב" in combined


def build_note(sender, message_text, context_messages, max_len=350):
    """Note: one relevant request (the one right before the share) + short extra. Capped length."""
    parts = []
    if message_text and ".vcf" not in message_text:
        parts.append(message_text[:150])
    # closest "request" message (immediately before or near the share)
    for _, _, txt in reversed(context_messages):
        if any(x in txt for x in ["מחפש", "מכיר", "המלצה", "מישהו", "מישהי", "רוצה", "יש למישה"]):
            parts.append(txt[:200].replace("\n", " "))
            break
    out = " | ".join(parts).strip()
    return out[:max_len] + ("..." if len(out) > max_len else "") if out else ""


def main():
    parser = argparse.ArgumentParser(description="WhatsApp ZIP to recommendations JSON")
    parser.add_argument("zip_path", nargs="?", default=DEFAULT_ZIP, help="Path to WhatsApp export ZIP")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUT), help="Output JSON path")
    args = parser.parse_args()
    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"ZIP not found: {zip_path}", flush=True)
        return 1
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading VCF from ZIP...", flush=True)
    by_phone, by_filename = load_vcf_from_zip(zip_path)
    print(f"  Found {len(by_phone)} contacts in VCF, {len(by_filename)} filename mappings", flush=True)

    print("Scanning chat for VCF attachments...", flush=True)
    seen_phones = set()
    entries = []
    for vcf_name, sender, message_text, context in find_vcf_mentions_and_context(zip_path, by_filename):
        # Match vcf_name to contact (filename might be "Name.vcf" or with different encoding)
        key = vcf_name.lower().strip()
        if key not in by_filename:
            key = key.replace(".vcf", "").lower()
        if key not in by_filename:
            continue
        name, phone = by_filename[key]
        if not name:
            name = vcf_name.replace(".vcf", "")
        name = clean_contact_name_start(name)
        if not name:
            name = vcf_name.replace(".vcf", "").strip()
        if phone in seen_phones:
            # Merge note with existing and re-infer field from name + merged note
            for e in entries:
                if e.get("phone") == phone or normalize_phone(e.get("phone", "")) == phone:
                    extra = build_note(sender, message_text, context)
                    if extra and extra not in (e.get("note") or ""):
                        e["note"] = (e.get("note") or "") + " | " + extra
                        # Re-infer field: name first, then note (by frequency)
                        name = e.get("name") or ""
                        merged_note = e.get("note") or ""
                        field = infer_field_from_text(name)
                        if not field:
                            field = infer_field_from_note(merged_note)
                        if field:
                            e["field"] = field
                        e["extra_info"] = infer_additional_info(
                            e.get("name") or "", e.get("note") or "", e.get("field") or ""
                        )
                    break
            continue
        seen_phones.add(phone)
        note = build_note(sender, message_text, context)
        # Priority: 1) name, 2) note (if several fields in note → choose the one that appears most), 3) context
        field = infer_field_from_text(name)
        if not field:
            field = infer_field_from_note(note)
        if not field:
            field = infer_field_from_context(context)
        from_moshav = infer_from_moshav(context, message_text)
        entries.append({
            "name": name,
            "phone": phone,
            "field": field,
            "from_moshav": from_moshav,
            "note": note,
            "extra_info": infer_additional_info(name, note, field),
        })
    print(f"  Found {len(entries)} recommended contacts from VCF attachments only", flush=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
