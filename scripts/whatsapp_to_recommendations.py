#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract recommended contacts from a WhatsApp export ZIP (Hebrew chat + VCF attachments).
Produces JSON: name, phone, field, from_moshav, note.

Usage:
  python scripts/whatsapp_to_recommendations.py [path_to.zip] [--output path.json]

Default ZIP: G:\\My Drive\\ai\\whatsapp test bck.zip
Default output: data/whatsapp_recommendations.json
"""
import re
import json
import zipfile
import argparse
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = r"G:\My Drive\ai\whatsapp test bck.zip"
DEFAULT_OUT = ROOT / "data" / "whatsapp_recommendations.json"

# WhatsApp chat line: 18/06/2015, 16:33 - ‎‫סיגל ראב‬‎: message
CHAT_LINE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2})\s*-\s*(.+?):\s*(.*)$",
    re.UNICODE,
)
# continuation line (no date) - part of previous message
# Attachment in chat: "אורית חשבון.vcf (file attached)" or "something.vcf (file attached)"
VCF_ATTACHED_RE = re.compile(r"(.+?\.vcf)\s*\(file attached\)", re.UNICODE | re.IGNORECASE)

# Israeli mobile: 05x-xxx-xxxx, 05x xxx xxxx, 972-5x-..., +972 50 ...
PHONE_IN_TEXT_RE = re.compile(
    r"(?:\+972|972)[\s\-]?5[\s\-]?\d[\s\-]?\d{3}[\s\-]?\d{4}|"
    r"05[\s\-]?\d[\s\-]?\d{3}[\s\-]?\d{4}|"
    r"05\d[\s\-]?\d{3}[\s\-]?\d{4}",
    re.UNICODE,
)
REQUEST_INDICATORS = ("מחפש", "מחפשת", "מכיר", "מכירה", "המלצה", "מישהו", "מישהי", "רוצה", "יש למישה", "אשמח להמלצה", "מבקשת המלצה", "צריכה המלצה")

# Israeli phone: 05x, 972 5x, +972-54-..., 972549... normalize to digits only, then to 05x
def normalize_phone(s):
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if digits.startswith("972") and len(digits) >= 12:
        # 972544907706 -> 0544907706
        digits = "0" + digits[3:]
    if digits.startswith("0") and len(digits) == 10:
        return digits
    if len(digits) == 9 and digits[0] in "23456789":
        return "0" + digits
    return digits


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
    return (name or "", phone or "")


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
            by_phone[phone] = {"name": name or base.replace(".vcf", ""), "vcf_filename": base}
            by_filename[base.lower()] = (name or base.replace(".vcf", ""), phone)
            # also map without .vcf for flexible matching
            by_filename[base.replace(".vcf", "").lower()] = (name or base.replace(".vcf", ""), phone)
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


# Simple keyword -> field mapping (Hebrew). First match wins. More specific first.
FIELD_KEYWORDS = [
    ("טכנאי תנורים", "טכנאי מכשירי חשמל"),
    ("תנורי אפיה", "טכנאי מכשירי חשמל"),
    ("תנורי אפייה", "טכנאי מכשירי חשמל"),
    ("מתקן תנורים", "טכנאי מכשירי חשמל"),
    ("תנורים", "טכנאי מכשירי חשמל"),
    ("תריסים חשמליים", "תריסים"),
    ("תריסים", "תריסים"),
    ("מורה להוראה מתקנת", "מורים פרטיים"),
    ("הוראה מתקנת", "מורים פרטיים"),
    ("מורה לפסנתר", "מורים פרטיים"),
    ("מורה פרטי", "מורים פרטיים"),
    ("מורה למתמטיקה", "מורים פרטיים"),
    ("מורה ללשון", "מורים פרטיים"),
    ("מורה לאנגלית", "מורים פרטיים"),
    ("מורה לנהיגה", "נהיגה"),
    ("מורה לבר מצווה", "מורים פרטיים"),
    ("מאבחן דידקטי", "מורים פרטיים"),
    ("מתמטיקה", "מורים פרטיים"),
    ("חשבון", "מורים פרטיים"),
    ("לשון", "מורים פרטיים"),
    ("רופא שיניים", "רפואת שיניים"),
    ("רופאת שיניים", "רפואת שיניים"),
    ("שיננית", "רפואת שיניים"),
    ("אורטודנט", "רפואת שיניים"),
    ("רופא", "רפואה"),
    ("רופאה", "רפואה"),
    ("מרפאה", "רפואה"),
    ("נוירולוג", "רפואה"),
    ("פסיכולוג", "פסיכולוגיה"),
    ("פסיכולוגית", "פסיכולוגיה"),
    ("פיזיותרפיסט", "רפואה"),
    ("פיזיותרפיה", "רפואה"),
    ("וטרינר", "רפואה"),
    ("חשמלאי", "חשמל"),
    ("חשמל", "חשמל"),
    ("אינסטלטור", "אינסטלציה"),
    ("אינסטלציה", "אינסטלציה"),
    ("נגר", "נגרות"),
    ("נגרות", "נגרות"),
    ("צבע", "צבע"),
    ("צבעי", "צבע"),
    ("טכנאי מזגנים", "מיזוג"),
    ("איש מזגנים", "מיזוג"),
    ("מתקן מזגנים", "מיזוג"),
    ("מזגן", "מיזוג"),
    ("מיזוג", "מיזוג"),
    ("נהג מונית", "מוניות"),
    ("מונית", "מוניות"),
    ("הובלה", "הובלות"),
    ("הובלות", "הובלות"),
    ("ספר לקטנים", "מספרה"),
    ("ספר גברים", "מספרה"),
    ("ספרית", "מספרה"),
    ("ספר לכלבים", "מספרה"),
    ("מספרת כלבים", "מספרה"),
    ("ספרית כלבים", "מספרה"),
    ("מספרה", "מספרה"),
    ("מספר", "מספרה"),
    ("מנעולן", "מנעולן"),
    ("הדברה", "הדברה"),
    ("מדביר", "הדברה"),
    ("עוזרת בית", "נקיון"),
    ("נקיון", "נקיון"),
    ("מנקה", "נקיון"),
    ("תפירה", "תפירה"),
    ("תופרת", "תפירה"),
    ("קייטרינג", "קייטרינג"),
    ("אילוף כלבים", "אילוף כלבים"),
    ("מאלף כלבים", "אילוף כלבים"),
    ("גננת", "גני ילדים"),
    ("סייעת", "גני ילדים"),
    ("מתקן מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("מכונת כביסה", "טכנאי מכשירי חשמל"),
    ("מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("טכנאי מדיח", "טכנאי מכשירי חשמל"),
    ("טכנאי מכונות כביסה", "טכנאי מכשירי חשמל"),
    ("טכנאי מייבש", "טכנאי מכשירי חשמל"),
    ("מחשבים", "טכנאי מחשבים"),
    ("טכנאי מחשבים", "טכנאי מחשבים"),
    ("טכנאי מכשירי חשמל", "טכנאי מכשירי חשמל"),
    ("מקרר", "טכנאי מכשירי חשמל"),
    ("אלומיניום", "אלומיניום"),
    ("איש אזעקות", "אזעקה"),
    ("אזעקה", "אזעקה"),
    ("שיאצו", "רפואה משלימה"),
    ("שמנים", "רפואה משלימה"),
    ("מסאג'", "עיסוי"),
    ("מסאז'", "עיסוי"),
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
    ("מדריך טיולים", "תיירות"),
    ("מדריכת טיולים", "תיירות"),
    ("רואה חשבון", "ראיית חשבון"),
    ("רואת חשבון", "ראיית חשבון"),
    ("מנהל חשבונות", "ראיית חשבון"),
    ("עורך דין", "משפטים"),
    ("עורכת דין", "משפטים"),
    ("זגג", "זגגות"),
    ("זגגות", "זגגות"),
    ("טכנאי גז", "גז"),
    ("גז", "גז"),
    ("דוד שמש", "דודים"),
    ("דודים", "דודים"),
    ("איטום", "איטום"),
    ("עובש", "איטום"),
    ("פרגולה", "נגרות"),
    ("פרגולות", "נגרות"),
    ("ביטוח", "ביטוח"),
    ("שף", "קייטרינג"),
    ("שף פרטי", "קייטרינג"),
    ("רפד", "ריפוד"),
    ("צורף", "צורפות"),
    ("אופטימטריסט", "רפואה"),
    ("אופטומטריסט", "רפואה"),
    ("מתרגם", "תרגום"),
    ("נוטריון", "נוטריון"),
    ("דיאטנית", "רפואה"),
    ("מרפאה בעיסוק", "מרפאה בעיסוק"),
    ("פסיכיאטר", "רפואה"),
    ("מזגנים ", "מיזוג"),
    ("מתנפחים", "השכרת מתנפחים"),
    ("מצנחי רחיפה", "ספורט"),
    ("פנסיון כלבים", "אילוף כלבים"),
    ("מכבסה", "כביסה"),
    ("מורה לנהיגה", "נהיגה"),
]


def infer_field_from_text(text):
    """Match first keyword in text -> field. Used for note or name."""
    if not text or not text.strip():
        return ""
    for kw, field in FIELD_KEYWORDS:
        if kw in text:
            return field
    return ""


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


def extract_phones_and_names_from_message(text):
    """Find Israeli phone numbers in text; for each, try to get a name from surrounding text. Yield (phone, name)."""
    if not text or not text.strip():
        return
    for m in PHONE_IN_TEXT_RE.finditer(text):
        raw = m.group(0)
        phone = normalize_phone(raw)
        if not phone or len(phone) < 9:
            continue
        # Name: up to ~40 chars before the number, then clean
        start = max(0, m.start() - 45)
        before = text[start:m.start()].strip()
        # Take last "segment" (after : or newline or comma) or last few words
        for sep in (":", "\n", ",", ".", ")", "]"):
            if sep in before:
                before = before.split(sep)[-1].strip()
        # Remove "של" prefix (הטלפון של X -> X)
        before = re.sub(r"^(?:הטלפון|המספר|טל[\.']?)\s+של\s+", "", before, flags=re.IGNORECASE)
        before = re.sub(r"^של\s+", "", before)
        before = before.strip()
        # If it looks like a name (no digits, reasonable length)
        if before and len(before) <= 35 and not re.search(r"\d{3}", before):
            name = before
        else:
            name = ""
        yield (phone, name)


def find_text_only_recommendations(zip_path, window_before=3):
    """Scan chat for messages that contain a phone and are preceded by a request. Yield (phone, name, message_text, context)."""
    messages = list(parse_chat_messages(zip_path))
    for i in range(1, len(messages)):
        _, _, text = messages[i]
        if not PHONE_IN_TEXT_RE.search(text):
            continue
        # Check if any of the previous window_before messages looks like a request
        context = messages[max(0, i - window_before):i]
        context_text = " ".join(msg[2] for msg in context)
        if not any(ind in context_text for ind in REQUEST_INDICATORS):
            continue
        for phone, name in extract_phones_and_names_from_message(text):
            if phone:
                yield (phone, name or "מהצ'אט", text, context)


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
        if phone in seen_phones:
            # optional: merge note with existing
            for e in entries:
                if e.get("phone") == phone or normalize_phone(e.get("phone", "")) == phone:
                    extra = build_note(sender, message_text, context)
                    if extra and extra not in (e.get("note") or ""):
                        e["note"] = (e.get("note") or "") + " | " + extra
                    break
            continue
        seen_phones.add(phone)
        note = build_note(sender, message_text, context)
        # Infer field from the note (the relevant request), not from raw context
        field = infer_field_from_text(note)
        if not field:
            field = infer_field_from_context(context)
        # If name clearly indicates field (e.g. "ברוך תנורים"), prefer that
        name_field = infer_field_from_text(name)
        if name_field:
            field = name_field
        from_moshav = infer_from_moshav(context, message_text)
        entries.append({
            "name": name,
            "phone": phone,
            "field": field,
            "from_moshav": from_moshav,
            "note": note,
        })
    print(f"  Found {len(entries)} recommended contacts from chat attachments", flush=True)

    # Phase 2: contacts mentioned in text (name + phone) without VCF, in recommendation context
    print("Scanning chat for phone numbers in recommendation context (no VCF)...", flush=True)
    added_from_text = 0
    for phone, name, message_text, context in find_text_only_recommendations(zip_path):
        if phone in seen_phones:
            continue
        seen_phones.add(phone)
        note = message_text[:250].replace("\n", " ") if message_text else ""
        if not note:
            for _, _, txt in reversed(context):
                if any(x in txt for x in REQUEST_INDICATORS):
                    note = txt[:200].replace("\n", " ")
                    break
        field = infer_field_from_text(note)
        if not field:
            field = infer_field_from_context(context)
        name_field = infer_field_from_text(name)
        if name_field:
            field = name_field
        from_moshav = infer_from_moshav(context, message_text)
        entries.append({
            "name": name.strip() or "מהצ'אט",
            "phone": phone,
            "field": field,
            "from_moshav": from_moshav,
            "note": note[:350] if note else "",
        })
        added_from_text += 1
    print(f"  Added {added_from_text} contacts from text only (no VCF)", flush=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
