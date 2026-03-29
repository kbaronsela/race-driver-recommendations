#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract recommended contacts from a WhatsApp export (ZIP or extracted folder: Hebrew chat + VCF attachments).
For each VCF share in the chat, context (messages before/after) is sent to an LLM (Ollama / Groq / Gemini)
to decide if the share is an explicit **recommendation** or a **direct reply** to a request for a professional/service provider. By default (**hybrid**), the model only decides
include/exclude; **field** (תחום) comes from Hebrew keyword rules (name, filename, TITLE/ORG, chat). Use
``--no-hybrid`` for the older behavior where the model also suggests field.
Produces JSON: name, phone, field, from_moshav, note, extra_info. Phone numbers in plain text are ignored.
Contact names are trimmed of leading junk until the first letter (digits, '.', symbols, marks, etc.).
Only Israeli domestic phone numbers (normalized 10-digit 0…) are kept.
Duplicate contacts (same field, related names, different numbers) are merged into one row with a phones[] list.

Usage:
  python scripts/whatsapp_to_recommendations.py [path_to.zip|export_folder] [--output path.json]
  python scripts/whatsapp_to_recommendations.py ... --legacy   # keyword rules only, no LLM
  python scripts/whatsapp_to_recommendations.py ... --limit 5    # first 5 VCF lines in chat (smoke test)
  python scripts/whatsapp_to_recommendations.py ... --no-hybrid # LLM returns field too (legacy)

Default export: <repo>/whatsapp test.zip (if missing, pass path explicitly)
Default output: data/entries.json (also refreshes view_recommendations.html when using that path)
Default local LLM: http://127.0.0.1:11434, model qwen2.5:7b
Remote: --llm-backend openai + GROQ_API_KEY, or --llm-backend gemini + GEMINI_API_KEY (Google AI Studio)
"""
import os
import re
import sys
import time
import json
import zipfile
import argparse
import unicodedata
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORT = ROOT / "whatsapp test.zip"
DEFAULT_OUT = ROOT / "data" / "entries.json"

from additional_info import infer_additional_info  # noqa: E402
from duplicate_contact_merge import apply_duplicate_merge_to_entries  # noqa: E402
from generate_recommendations_view import main as regenerate_recommendations_view  # noqa: E402
from llm_recommendation_gate import (  # noqa: E402
    DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_GEMINI_MODEL,
    classify_vcf_share,
)

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


# Israeli national format after normalize_phone (digits only, trunk 0).
# 10-digit: mobile 05x; geographic 0[23489]+8 subscriber; VoIP 072/073/074/076/077/079 +7.
# 9-digit: geographic 02/03/04/08/09 + 7-digit subscriber (e.g. 035028838 for 03-5028838).
_ISRAELI_10_RE = re.compile(
    r"^(?:05[0-9]\d{7}|0[23489]\d{8}|07[234679]\d{7})$"
)
_ISRAELI_9_GEO_RE = re.compile(r"^0[23489]\d{7}$")


def is_israeli_phone(s):
    """True if normalized number is a valid Israeli domestic landline or mobile."""
    if not s:
        return False
    d = normalize_phone(s)
    if not d.isdigit() or not d.startswith("0"):
        return False
    if len(d) == 10:
        return bool(_ISRAELI_10_RE.match(d))
    if len(d) == 9:
        return bool(_ISRAELI_9_GEO_RE.match(d))
    return False


def clean_contact_name_start(s):
    """
    Strip leading characters until the first Unicode letter (L*).
    Removes leading digits, '.', '-', emoji, RTL marks, spaces, etc.
    """
    if not s or not str(s).strip():
        return ""
    original = str(s).strip()
    i = 0
    while i < len(original):
        cat = unicodedata.category(original[i])
        if cat[0] == "L":
            break
        i += 1
    out = original[i:].strip()
    return out if out else original


def _vcf_field_upper(line):
    """Upper part before first colon (property name, ignoring value)."""
    if ":" not in line:
        return ""
    return line.split(":", 1)[0].upper()


def parse_vcard(content):
    """Parse one VCF. Return dict: name, phone, org, note_vcf, title_vcf."""
    name = None
    phone = None
    org = ""
    note_vcf = ""
    title_vcf = ""
    for line in content.splitlines():
        line = line.strip()
        prop = _vcf_field_upper(line)
        if line.startswith("FN:"):
            name = line[3:].strip()
        elif "TEL" in prop and "LABEL" not in prop:
            m = re.search(r"[\d\-\+\s]{9,}", line)
            if m and not phone:
                phone = normalize_phone(m.group(0))
        elif prop.startswith("ORG"):
            org = line.split(":", 1)[-1].strip() if ":" in line else ""
        elif prop.startswith("NOTE"):
            note_vcf = line.split(":", 1)[-1].strip() if ":" in line else ""
        elif prop.startswith("TITLE"):
            title_vcf = line.split(":", 1)[-1].strip() if ":" in line else ""
    if not name and "N:" in content:
        for line in content.splitlines():
            if line.startswith("N:"):
                parts = line[2:].split(";")
                if len(parts) >= 2:
                    name = (parts[2] + " " + parts[1]).strip() or parts[1]
                break
    name = clean_contact_name_start(name or "")
    return {
        "name": name,
        "phone": phone or "",
        "org": org,
        "note_vcf": note_vcf,
        "title_vcf": title_vcf,
    }


def load_vcf_from_zip(zip_path):
    """Return by_phone index and by_filename -> contact dict (name, phone, org, note_vcf, title_vcf)."""
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
            vc = parse_vcard(raw)
            phone = vc.get("phone") or ""
            if not phone:
                continue
            base = Path(info.filename).name
            stem = base.replace(".vcf", "").replace(".VCF", "")
            display = clean_contact_name_start(vc.get("name") or "") if vc.get("name") else clean_contact_name_start(stem)
            if not display:
                display = stem
            rec = {
                "name": display,
                "phone": phone,
                "org": (vc.get("org") or "").strip(),
                "note_vcf": (vc.get("note_vcf") or "").strip(),
                "title_vcf": (vc.get("title_vcf") or "").strip(),
                "vcf_filename": base,
            }
            by_phone[phone] = {"name": display, "vcf_filename": base}
            by_filename[base.lower()] = rec
            by_filename[stem.lower()] = rec
    return by_phone, by_filename


def load_vcf_from_directory(dir_path: Path):
    """Same indexing as load_vcf_from_zip, for a flat folder of .vcf + chat .txt."""
    by_phone = {}
    by_filename = {}
    for p in sorted(dir_path.glob("*.vcf")):
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        vc = parse_vcard(raw)
        phone = vc.get("phone") or ""
        if not phone:
            continue
        base = p.name
        stem = base.replace(".vcf", "").replace(".VCF", "")
        display = clean_contact_name_start(vc.get("name") or "") if vc.get("name") else clean_contact_name_start(stem)
        if not display:
            display = stem
        rec = {
            "name": display,
            "phone": phone,
            "org": (vc.get("org") or "").strip(),
            "note_vcf": (vc.get("note_vcf") or "").strip(),
            "title_vcf": (vc.get("title_vcf") or "").strip(),
            "vcf_filename": base,
        }
        by_phone[phone] = {"name": display, "vcf_filename": base}
        by_filename[base.lower()] = rec
        by_filename[stem.lower()] = rec
    return by_phone, by_filename


def load_vcf_index(export_path: Path):
    """Load VCF index from a WhatsApp export .zip or extracted directory."""
    if export_path.is_dir():
        return load_vcf_from_directory(export_path)
    return load_vcf_from_zip(export_path)


def read_export_chat_text(export_path: Path) -> str:
    """Read UTF-8 chat text from export: .zip (first .txt member), folder (WhatsApp Chat*.txt), or a single .txt path."""
    if export_path.is_dir():
        for p in sorted(export_path.glob("WhatsApp Chat*.txt")):
            return p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(export_path.glob("*.txt")):
            return p.read_text(encoding="utf-8", errors="replace")
        return ""
    if export_path.is_file() and export_path.suffix.lower() == ".txt":
        return export_path.read_text(encoding="utf-8", errors="replace")
    if export_path.is_file() and export_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(export_path, "r") as z:
            for info in z.infolist():
                if info.filename.endswith(".txt"):
                    return z.read(info).decode("utf-8", errors="replace")
    return ""


def parse_chat_messages(export_path):
    """Yield (datetime_str, sender, message_text) for each message. Multi-line messages merged."""
    lines = read_export_chat_text(export_path).splitlines()
    if not lines:
        return
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


def find_vcf_mentions_and_context(export_path, by_filename, window_before=5, window_after=3):
    """For each VCF attachment, yield (vcf_filename, sender, message_text, context_before, context_after)."""
    messages = list(parse_chat_messages(export_path))
    for i, (dt, sender, text) in enumerate(messages):
        for m in VCF_ATTACHED_RE.finditer(text):
            vcf_name = m.group(1).strip()
            context_before = []
            for j in range(max(0, i - window_before), i):
                context_before.append(messages[j])
            context_after = []
            for j in range(i + 1, min(len(messages), i + 1 + window_after)):
                context_after.append(messages[j])
            yield (vcf_name, sender, text, context_before, context_after)


def normalize_infer_text(s):
    """Collapse weird spaces / direction marks so 'דר ' etc. match VCF/chat exports."""
    if not s:
        return ""
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    s = re.sub(r"\s+", " ", s).strip()
    # עו׳ד (ו+גרש עברי) / עו'ד / עו״ד → עו"ד — כדי שיתאים לרשומת עו"ד ב-FIELD_KEYWORDS
    s = s.replace("עו׳ד", 'עו"ד').replace("עו'ד", 'עו"ד')
    s = s.replace("עו״ד", 'עו"ד')
    return s


# Merged notes concatenate many chat snippets; counting on the full string overweights
# frequent topics (רופא, הובלות…). Field inference uses only this prefix.
NOTE_INFER_MAX_LEN = 420


def _count_gaz_occurrences(s: str) -> int:
    """Count 'גז' without matching inside ארגז/מגזין/גזר (common false positives in group chats)."""
    n = 0
    i = 0
    while True:
        j = s.find("גז", i)
        if j < 0:
            break
        if j > 0 and s[j - 1] in ("ר", "מ"):
            i = j + 2
            continue
        if j + 2 < len(s) and s[j + 2] == "ר":
            i = j + 2
            continue
        n += 1
        i = j + 2
    return n


def _count_dikur_occurrences(s: str) -> int:
    """לא לתפוס את 'דיקור' בתוך 'פדיקור'."""
    n = 0
    i = 0
    needle = "דיקור"
    step = len(needle)
    while True:
        j = s.find(needle, i)
        if j < 0:
            break
        if j > 0 and s[j - 1] == "פ":
            i = j + step
            continue
        n += 1
        i = j + step
    return n


def _is_hebrew_letter(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return 0x0590 <= o <= 0x05FF


def _match_nagar_at(text: str, j: int) -> bool:
    """נגר כמקצוע בלבד — לא בתוך זינגרמן / אינגריד וכו'."""
    if j + 5 <= len(text) and text[j : j + 5] == "נגרות":
        return True
    if j + 5 <= len(text) and text[j : j + 5] == "נגרית":
        return True
    if j + 4 <= len(text) and text[j : j + 4] == "נגרים":
        return True
    if j + 3 > len(text) or text[j : j + 3] != "נגר":
        return False
    after = j + 3
    if after < len(text) and _is_hebrew_letter(text[after]):
        return False
    if j == 0:
        return True
    prev = text[j - 1]
    if not _is_hebrew_letter(prev):
        return True
    if prev == "ה" and (j == 1 or not _is_hebrew_letter(text[j - 2])):
        return True
    return False


def _count_nagar_occurrences(text: str) -> int:
    n = 0
    j = 0
    while j < len(text):
        if _match_nagar_at(text, j):
            if j + 5 <= len(text) and text[j : j + 5] in ("נגרות", "נגרית"):
                j += 5
            elif j + 4 <= len(text) and text[j : j + 4] == "נגרים":
                j += 4
            else:
                j += 3
            n += 1
        else:
            j += 1
    return n


def _keyword_occurrences_in_text(kw: str, text: str) -> int:
    if not kw or not text:
        return 0
    if kw == "גז":
        return _count_gaz_occurrences(text)
    if kw == "נגר":
        return _count_nagar_occurrences(text)
    if kw == "דיקור":
        return _count_dikur_occurrences(text)
    return text.count(kw)


def _keyword_in_text(kw: str, text: str) -> bool:
    return _keyword_occurrences_in_text(kw, text) > 0


# Simple keyword -> field mapping (Hebrew). First match wins. More specific first.
FIELD_KEYWORDS = [
    ("טכנאי תנורים", "טכנאי מכשירי חשמל"),
    ("תנורי אפיה", "טכנאי מכשירי חשמל"),
    ("תנורי אפייה", "טכנאי מכשירי חשמל"),
    ("מתקן תנורים", "טכנאי מכשירי חשמל"),
    ("תנורים", "טכנאי מכשירי חשמל"),
    ("תריסים חשמליים", "תריסים"),
    ("תריסים", "תריסים"),
    ("תריס", "תריסים"),
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
    ("מורה לחשבון", "מורים פרטיים"),
    ("מורת חשבון", "מורים פרטיים"),
    ("מורים לחשבון", "מורים פרטיים"),
    ("רואה חשבון", "ראיית חשבון"),
    ("רואת חשבון", "ראיית חשבון"),
    ("מנהל חשבונות", "ראיית חשבון"),
    ("חשבונאות", "ראיית חשבון"),
    ("משרד חשבון", "ראיית חשבון"),
    ("מורה לנהיגה", "נהיגה"),
    ("מורה נהיגה", "נהיגה"),
    ("מורה לבר מצווה", "מורים פרטיים"),
    ("מאבחן דידקטי", "אבחון"),
    ("מאבחנת דידקטית", "אבחון"),
    ("מאבחנת פסיכודידקטית", "אבחון"),
    ("מאבחנת", "אבחון"),
    ("מאבחן", "אבחון"),
    ("מתמטיקה", "מורים פרטיים"),
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
    ("נומרולוג", "נומרולוגיה"),
    ("מיניאטורות", "חוגים"),
    ("אדריכלית", "אדריכלות"),
    ("אדריכל", "אדריכלות"),
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
    ("תיקון שעונים", "שענות"),
    ("שעונאי", "שענות"),
    ("שעונים", "שענות"),
    ("שען", "שענות"),
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
    ("בית ספר", "חינוך"),
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
    ("מטפלת", "רפואה משלימה"),
    ("מטפל", "רפואה משלימה"),
    ("רפלקסולוג", "רפואה משלימה"),
    ("יוגה", "רפואה משלימה"),
    ("מאפרת", "קוסמטיקה"),
    ("מאפר", "קוסמטיקה"),
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
    # לא "כלבים" לבד — מופיע בהמון הודעות ממוזגות ודוחף תחום שגוי (למשל פלאפל).
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
    ("וילה", "תיירות"),
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
    ("פלאפל", "קייטרינג"),
    ("מאפיה", "קייטרינג"),
    ("מאפייה", "קייטרינג"),
    ("סחלבים", "קייטרינג"),
    ("סחלב", "קייטרינג"),
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
        if _keyword_in_text(kw, text):
            return field
    # Fallback: case-insensitive (e.g. CBT vs Cbt, Computers vs computers)
    text_cf = text.casefold()
    for kw, field in FIELD_KEYWORDS:
        kw_cf = kw.casefold()
        if kw_cf == "גז":
            if _count_gaz_occurrences(text_cf) > 0:
                return field
        elif kw_cf == "נגר":
            if _count_nagar_occurrences(text_cf) > 0:
                return field
        elif kw_cf == "דיקור":
            if _count_dikur_occurrences(text_cf) > 0:
                return field
        elif kw_cf in text_cf:
            return field
    return ""


def infer_field_from_note(note):
    """From note: count keyword matches per field; return the field that appears most often."""
    note = normalize_infer_text(note)
    if not note:
        return ""
    if len(note) > NOTE_INFER_MAX_LEN:
        note = note[:NOTE_INFER_MAX_LEN]
    count = defaultdict(int)
    note_cf = note.casefold()
    for kw, field in FIELD_KEYWORDS:
        if not kw:
            continue
        kw_cf = kw.casefold()
        if kw_cf == "גז":
            n = _count_gaz_occurrences(note_cf)
        elif kw_cf == "נגר":
            n = _count_nagar_occurrences(note_cf)
        elif kw_cf == "דיקור":
            n = _count_dikur_occurrences(note_cf)
        else:
            n = note_cf.count(kw_cf)
        if n:
            count[field] += n
    if not count:
        return ""
    return max(count, key=lambda f: count[f])


def infer_field_from_context(context_messages):
    """Concatenate recent messages and match first keyword -> field."""
    text = normalize_infer_text(" ".join(msg[2] for msg in context_messages))
    if len(text) > NOTE_INFER_MAX_LEN:
        text = text[-NOTE_INFER_MAX_LEN:]
    return infer_field_from_text(text)


# שענות: הקשר בלבד (5 הודעות לפני ה־VCF) לעיתים תופס המלצה על שען מהשיחה הסמוכה.
_SHAANUT_MARKERS = (
    "תיקון שעונים",
    "חנות שעונים",
    "שעונאי",
    "שעונים",
    "שען",
)


def refine_field_shaanut(field, name, note):
    """Keep שענות only if name or note contains a watchmaking cue; else clear."""
    if field != "שענות":
        return field
    combined = normalize_infer_text((name or "") + " " + (note or ""))
    if not combined.strip():
        return ""
    comb_cf = combined.casefold()
    for m in _SHAANUT_MARKERS:
        if m.casefold() in comb_cf:
            return field
    return ""


# תחומים שנבחרים לעיתים מהקשר צ'אט רחוק — נשאיר רק אם יש רמז בשם או בראש ההערה.
_TSILUM_MARKERS = (
    "צילום",
    "צלם",
    "צלמת",
    "צילומי",
    "צילומים",
    "מצלם",
    "מצלמת",
    "צילומי משפחה",
)
_SHCHIYA_MARKERS = (
    "שחייה",
    "שחיה",
    "בריכה",
    "בריכת",
    "שחיין",
    "שחיינית",
    "מורה שחייה",
)
_MOSHEH_MARKERS = (
    "מוסך",
    "צמיג",
    "צמיגים",
    "טכנאי רכב",
    "חשמלאי רכב",
    "פחח",
    "פחחות",
)


def refine_field_chat_noise(field, name, note):
    """Clear צילום / שחייה / מוסך when cue exists only in far chat, not in name or note head."""
    if field not in ("צילום", "שחייה", "מוסך"):
        return field
    n = normalize_infer_text(name or "")
    nt = normalize_infer_text(note or "")
    if len(nt) > NOTE_INFER_MAX_LEN:
        nt = nt[:NOTE_INFER_MAX_LEN]
    combined = normalize_infer_text(n + " " + nt).casefold()
    if not combined.strip():
        return ""
    if field == "צילום":
        markers = _TSILUM_MARKERS
    elif field == "שחייה":
        markers = _SHCHIYA_MARKERS
    else:
        markers = _MOSHEH_MARKERS
    for m in markers:
        if m.casefold() in combined:
            return field
    return ""


def infer_from_moshav(context_messages, message_text, context_after=None):
    """Check if any context or the message mentions מושב."""
    combined = message_text + " " + " ".join(msg[2] for msg in context_messages)
    if context_after:
        combined += " " + " ".join(msg[2] for msg in context_after)
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


def _infer_field_fallback(
    name,
    note,
    context_before,
    context_after,
    title_vcf="",
    org="",
    vcf_filename="",
):
    """Keyword-based field: contact name, filename stem, TITLE/ORG, then note and chat context."""
    stem = ""
    if vcf_filename:
        stem = str(vcf_filename).replace(".vcf", "").replace(".VCF", "").strip()
    field = infer_field_from_text(name or "")
    if not field and stem:
        field = infer_field_from_text(stem)
    if not field:
        field = infer_field_from_text(((title_vcf or "") + " " + (org or "")).strip())
    if not field:
        field = infer_field_from_note(note)
    if not field:
        field = infer_field_from_context(context_before)
    if not field:
        field = infer_field_from_context(context_after)
    return field


def main():
    # Windows consoles often default to cp1252; Hebrew log lines must not crash the script.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass

    parser = argparse.ArgumentParser(description="WhatsApp export (ZIP or folder) to recommendations JSON")
    parser.add_argument(
        "export_path",
        nargs="?",
        default=str(DEFAULT_EXPORT),
        help="WhatsApp export: .zip or folder with chat .txt and .vcf files (default: %(default)s)",
    )
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUT), help="Output JSON path")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Do not call the LLM; use keyword rules only (old behavior).",
    )
    parser.add_argument(
        "--no-hybrid",
        action="store_true",
        help="When using LLM: also ask the model for field (legacy). Default: hybrid — LLM only include/exclude; field from keyword rules.",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL),
        help="Ollama API base URL (default: %(default)s or env OLLAMA_URL)",
    )
    parser.add_argument(
        "--ollama-model",
        default=os.environ.get("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL),
        help="Model name (default: %(default)s or env OLLAMA_MODEL)",
    )
    parser.add_argument(
        "--llm-timeout",
        type=int,
        default=180,
        help="Seconds per LLM request (default: %(default)s)",
    )
    parser.add_argument(
        "--llm-backend",
        choices=("ollama", "openai", "gemini"),
        default=os.environ.get("LLM_BACKEND", "ollama"),
        help="ollama=local; openai=Groq/OpenRouter/…; gemini=Google. Env: LLM_BACKEND.",
    )
    parser.add_argument(
        "--openai-base-url",
        default=os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        help="OpenAI-compatible base (default: Groq %(default)s). Env: OPENAI_BASE_URL.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
        help="API key for --llm-backend openai. Env: GROQ_API_KEY or OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--openai-model",
        default=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        help="Model id for OpenAI-compatible API (default: Groq %(default)s). Env: OPENAI_MODEL.",
    )
    parser.add_argument(
        "--gemini-api-key",
        default=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
        help="API key for --llm-backend gemini (https://aistudio.google.com/apikey). Env: GEMINI_API_KEY.",
    )
    parser.add_argument(
        "--gemini-model",
        default=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        help="Gemini model id (default: %(default)s). Env: GEMINI_MODEL.",
    )
    parser.add_argument(
        "--llm-delay",
        type=float,
        default=float(os.environ.get("LLM_DELAY") or "0"),
        metavar="SEC",
        help="Seconds to sleep after each remote LLM call (openai/gemini). Groq free tier is ~6000 TPM; "
        "use e.g. 10–15 to avoid bursts. Env: LLM_DELAY. Default: %(default)s.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N VCF attachment lines in chat order (for testing).",
    )
    args = parser.parse_args()
    export_path = Path(args.export_path)
    if not export_path.exists():
        print(f"Export not found: {export_path}", flush=True)
        return 1
    if not export_path.is_dir() and not (export_path.is_file() and export_path.suffix.lower() == ".zip"):
        print("Export must be a .zip file or a folder containing WhatsApp Chat *.txt and .vcf files.", flush=True)
        return 1
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading VCF from export...", flush=True)
    by_phone, by_filename = load_vcf_index(export_path)
    print(f"  Found {len(by_phone)} contacts in VCF, {len(by_filename)} filename mappings", flush=True)

    use_llm = not args.legacy
    if use_llm:
        if args.llm_backend == "openai":
            if not (args.openai_api_key or "").strip():
                print(
                    "  --llm-backend openai requires an API key. Set GROQ_API_KEY (free at https://console.groq.com) "
                    "or OPENAI_API_KEY, or pass --openai-api-key.",
                    flush=True,
                )
                return 1
            print(
                f"  LLM gate (OpenAI-compatible): {args.openai_base_url} model={args.openai_model}",
                flush=True,
            )
            if args.llm_delay <= 0:
                print(
                    "  Tip: Groq free tier limits tokens/minute — 429s auto-retry with backoff; "
                    "add --llm-delay 12 for fewer rate limits on long runs.",
                    flush=True,
                )
        elif args.llm_backend == "gemini":
            if not (args.gemini_api_key or "").strip():
                print(
                    "  --llm-backend gemini requires GEMINI_API_KEY (free at https://aistudio.google.com/apikey) "
                    "or pass --gemini-api-key.",
                    flush=True,
                )
                return 1
            print(f"  LLM gate (Gemini): model={args.gemini_model}", flush=True)
            if args.llm_delay <= 0:
                print(
                    "  Tip: Gemini free tier has RPM limits — use --llm-delay 4–8 on long runs if you see many 429s.",
                    flush=True,
                )
        else:
            print(f"  LLM gate (Ollama): {args.ollama_url} model={args.ollama_model}", flush=True)
        if not args.no_hybrid:
            print(
                "  Hybrid: LLM decides include/exclude only; field = keyword rules (name, file, TITLE/ORG, chat).",
                flush=True,
            )
        else:
            print("  Legacy LLM: model also returns field when possible.", flush=True)
    else:
        print("  Mode: --legacy (keyword rules only, no LLM)", flush=True)

    print("Scanning chat for VCF attachments...", flush=True)
    if args.limit is not None:
        print(
            f"  --limit {args.limit}: will stop after {args.limit} VCF attachment line(s) in chat order.",
            flush=True,
        )
    if use_llm and args.llm_backend == "ollama":
        print(
            "  (מודל מקומי: בקשה אחת לכל צירוף VCF בצ'אט; בין שורות בלוג יכולות לעבור דקות על מעבד.)",
            flush=True,
        )
    seen_phones = set()
    entries = []
    llm_skipped = 0
    llm_errors = 0
    llm_calls = 0
    n = 0
    for vcf_name, sender, message_text, context_before, context_after in find_vcf_mentions_and_context(
        export_path, by_filename
    ):
        n += 1
        if args.limit is not None and n > args.limit:
            break
        if n % 100 == 0:
            print(f"  ... processed {n} VCF attachment(s) in chat", flush=True)
        key = vcf_name.lower().strip()
        if key not in by_filename:
            key = key.replace(".vcf", "").lower()
        if key not in by_filename:
            continue
        rec = by_filename[key]
        name = rec["name"]
        phone = rec["phone"]
        org = rec.get("org") or ""
        note_vcf = rec.get("note_vcf") or ""
        title_vcf = rec.get("title_vcf") or ""
        vcf_filename = rec.get("vcf_filename") or vcf_name
        if not is_israeli_phone(phone):
            continue
        phone_key = normalize_phone(phone)
        if not name:
            name = vcf_name.replace(".vcf", "")
        name = clean_contact_name_start(name)
        if not name:
            name = vcf_name.replace(".vcf", "").strip()

        note = build_note(sender, message_text, context_before)
        if phone_key in seen_phones:
            for e in entries:
                if e.get("phone") == phone or normalize_phone(e.get("phone", "")) == phone_key:
                    extra = build_note(sender, message_text, context_before)
                    if extra and extra not in (e.get("note") or ""):
                        e["note"] = (e.get("note") or "") + " | " + extra
                        name = e.get("name") or ""
                        merged_note = e.get("note") or ""
                        field = infer_field_from_text(name)
                        if not field:
                            field = infer_field_from_note(merged_note)
                        if not field:
                            field = e.get("field") or ""
                        field = refine_field_chat_noise(
                            refine_field_shaanut(field, name, merged_note), name, merged_note
                        )
                        e["field"] = field
                        e["extra_info"] = infer_additional_info(
                            e.get("name") or "", e.get("note") or "", e.get("field") or ""
                        )
                    break
            continue

        if use_llm:
            if args.llm_backend == "openai":
                llm_model = args.openai_model
            elif args.llm_backend == "gemini":
                llm_model = args.gemini_model
            else:
                llm_model = args.ollama_model
            llm = classify_vcf_share(
                backend=args.llm_backend,
                ollama_url=args.ollama_url,
                model=llm_model,
                openai_base_url=args.openai_base_url,
                openai_api_key=args.openai_api_key,
                gemini_api_key=args.gemini_api_key,
                name=name,
                phone=phone,
                vcf_filename=vcf_filename,
                org=org,
                note_vcf=note_vcf,
                title_vcf=title_vcf,
                sender=sender,
                attach_message=message_text,
                context_before=context_before,
                context_after=context_after,
                timeout_sec=args.llm_timeout,
                hybrid=not args.no_hybrid,
            )
            llm_calls += 1
            if llm_calls == 1 or llm_calls % 5 == 0:
                print(
                    f"  ... LLM completed {llm_calls} request(s); last: {phone} (attachment #{n} in chat)",
                    flush=True,
                )
            if llm.get("error"):
                llm_errors += 1
                print(f"  LLM error (skip entry): {phone} {name!r} — {llm['error']}", flush=True)
                if args.llm_delay > 0 and args.llm_backend in ("openai", "gemini"):
                    time.sleep(args.llm_delay)
                continue
            if not llm.get("include"):
                llm_skipped += 1
                if args.llm_delay > 0 and args.llm_backend in ("openai", "gemini"):
                    time.sleep(args.llm_delay)
                continue
            if args.no_hybrid:
                field = (llm.get("field") or "").strip()
                if not field:
                    field = _infer_field_fallback(
                        name, note, context_before, context_after, title_vcf, org, vcf_filename
                    )
            else:
                field = _infer_field_fallback(
                    name, note, context_before, context_after, title_vcf, org, vcf_filename
                )
            field = refine_field_chat_noise(refine_field_shaanut(field, name, note), name, note)
            if args.llm_delay > 0 and args.llm_backend in ("openai", "gemini"):
                time.sleep(args.llm_delay)
        else:
            field = _infer_field_fallback(name, note, context_before, context_after)
            field = refine_field_chat_noise(refine_field_shaanut(field, name, note), name, note)

        seen_phones.add(phone_key)
        from_moshav = infer_from_moshav(context_before, message_text, context_after)
        entries.append({
            "name": name,
            "phone": phone,
            "field": field,
            "from_moshav": from_moshav,
            "note": note,
            "extra_info": infer_additional_info(name, note, field),
        })
    print(f"  Found {len(entries)} recommended contacts from VCF attachments only", flush=True)
    if use_llm:
        print(f"  LLM: excluded {llm_skipped} attachment(s), errors {llm_errors}", flush=True)

    entries, n_dup_groups = apply_duplicate_merge_to_entries(entries)
    if n_dup_groups:
        print(f"  Merged {n_dup_groups} duplicate group(s) -> {len(entries)} entries (phones[] where merged)", flush=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}", flush=True)
    try:
        if out_path.resolve() == (ROOT / "data" / "entries.json").resolve():
            vr = regenerate_recommendations_view()
            if vr != 0:
                print(f"  Warning: regenerate view_recommendations.html exited {vr}", flush=True)
        else:
            print(
                f"  Skipped view_recommendations.html (output is not data/entries.json)",
                flush=True,
            )
    except Exception as e:
        print(f"  Warning: could not refresh view_recommendations.html: {e}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
