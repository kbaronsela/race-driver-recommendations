# -*- coding: utf-8 -*-
"""
Heuristic scan of a full WhatsApp export for restaurant-related messages.
Produces the same dict shape as extract_restaurants_whatsapp (note=מקור, extra_info=טקסט).

Messages qualify if they contain a food cue AND (explicit venue wording like "מסעדת …"
or strong recommendation phrases like "מומלץ"/"ממליצ" — not bare "מעולה"/"טעים",
which matched too much of the chat). בקשות להמלצות (מחפשים, אשמח להמלצה וכו׳) נזרקות — רק טקסט
שמדמה המלצה בפועל. Tune _FOOD / _STRONG_RECOMMEND / _REQUEST / _EXCLUDE as needed.
"""
from __future__ import annotations

import re
from typing import Iterator

from restaurant_name_plausible import is_plausible_restaurant_name

# --- message splitting (WhatsApp Android/iOS export style) ---
_MSG_HEAD = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)\s*$"
)


def iter_whatsapp_messages(text: str) -> Iterator[tuple[str, str, str]]:
    """Yield (date_str, sender, body) for each message."""
    current_date: str | None = None
    current_sender: str | None = None
    body_lines: list[str] = []
    for line in text.splitlines():
        m = _MSG_HEAD.match(line)
        if m:
            if current_date is not None:
                yield (current_date, current_sender or "", "\n".join(body_lines).strip())
            current_date, current_sender = m.group(1), normalize_sender(m.group(2))
            rest = m.group(3) or ""
            body_lines = [rest] if rest else []
        else:
            if current_date is not None:
                body_lines.append(line)
    if current_date is not None:
        yield (current_date, current_sender or "", "\n".join(body_lines).strip())


def normalize_sender(s: str) -> str:
    s = (s or "").replace("\u200e", "").replace("\u200f", "").replace("\u202a", "").replace("\u202c", "")
    s = re.sub(r"^[‎‏‫‬\s]+|[‎‏‫‬\s]+$", "", s)
    return s.strip()


def normalize_spaces(s: str) -> str:
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    return re.sub(r"\s+", " ", s).strip()


_FOOD = (
    "מסעד",
    "בית קפה",
    "קפה ",
    " סושי",
    "סושי ",
    "פיצה",
    "פלאפל",
    "פסטה",
    "דגים",
    "חומוס",
    "בראנץ",
    "ברנץ",
    "איטלק",
    "אסיית",
    "תאילנד",
    "פרסית",
    "לבנונ",
    "מטבח ",
    "משלוחי ",
    "משלוחים ",
    "ארוחת בוקר",
    "ארוחת ערב",
    "סטייק",
    "המבורגר",
    "נודלס",
    "רמן",
    "דוכן ",
    "שוק ",
    "מאפייה",
    "מאפה ",
    "יקב ",
    "בר ",
)

# רמזי המלצה *חזקים* בלבד — לא "מעולה"/"טעים" לבדם; בלי "המלצה/המלצות" כי מופיעות גם בבקשות.
_STRONG_RECOMMEND = (
    "מומלץ",
    "ממליצ",
    "חובה לנסות",
    "חובה ללכת",
    "חובה לבקר",
    "דיברו בחום",
    "ממש אהבנו",
    "מומלצת בחום",
    "המלצה חמה",
    "המלצות חמות",
)

# הודעה שמבקשת המלצות — לא לשמור כרשומת מסעדה
_REQUEST = (
    "אשמח להמלצ",
    "אשמח על המלצ",
    "אשמח לשמוע המלצ",
    "בקשה להמלצ",
    "בקשת המלצ",
    "מחפשת המלצ",
    "מחפש המלצ",
    "מחפשים המלצ",
    "מחפשות המלצ",
    "למי יש המלצ",
    "למישהיא יש המלצ",
    "למישהי יש המלצ",
    "יש המלצה לבית קפה",
    "יש המלצה למסעד",
    "בבקשה המלצה למסעדה",
    "בבקשה המלצה לבית קפה",
    "בבקשה המלצה לארוחת",
    "באזורינו?",
    "באזורנו?",
    "באזורכם?",
    "באזורכן?",
    "באזורם?",
    "באזורה?",
    "באזורו?",
    "באיזורנו?",
    "באיזורכם?",
    "באיזורכן?",
    "מה אתן ממליצ",
    "מה אתם ממליצ",
    "מה את ממליצ",
    "מישהו יודע מסעד",
    "מישהו יודע על מסעד",
    "מישהו יודע לגבי מסעד",
    "מישהו מכיר מסעד",
    "מישהי מכירה מסעד",
    "מישהו יכול להמליץ",
    "יש לכם המלצ",
    "יש למישהו המלצ",
    "תעזרו לי למצוא",
    "תעזרו לי עם",
    "תעזרו לי בבחירת",
    "מי יודע מסעד",
    "מי מכיר מסעד",
    "רוצה לשמוע המלצ",
    "רוצה המלצ",
    "צריכה המלצ",
    "צריך המלצ",
    "צריכים המלצ",
    "נדרשת המלצ",
    "אפשר המלצ",
    "תשתפו בהמלצ",
    "מחפשת מסעד",
    "מחפש מסעד",
    "מחפשים מסעד",
    "מחפשות מסעד",
    "מחפשת בית קפה",
    "מחפש בית קפה",
    "מחפשים בית קפה",
    "מחפשות בית קפה",
    "מחפשת מקום לאכול",
    "מחפש מקום לאכול",
    "איפה אוכלים",
    "איפה אוכלים טוב",
    "לאן ללכת לאכול",
    "לאן לאכול",
    "עזרה עם מסעד",
    "עזרה למצוא מסעד",
    "תודה על ההמלצ",
    "תודה לכולן על ההמלצ",
    "תודה לכם על ההמלצ",
    # תיאור בקשה: «…טובה ב… שאפשר לקחת אליה/אורח»
    "שאפשר לקחת אליה אור",
    "שאפשר לקחת אליו אור",
    "שאפשר לקחת אליה אורח",
    "שאפשר לקחת אליו אורח",
    "שאפשר לקחת אליה את",
    "שאפשר לקחת אליו את",
    "שאפשר לקחת אליה אורחים",
    "שאפשר לקחת אליו אורחים",
    "אנא המלצתכן",
    "המלצתכן למסעד",
    "המלצתכן לבית קפה",
    # בקשות — ניסוח «המלצה למסעד…» / «מי יכול…» (לא תשובה)
    "המלצה למסעדה",
    "המלצה למסעדת",
    "המלצות למסעדה",
    "המלצות למסעדת",
    "המלצה על מסעדה",
    "המלצות על מסעדה",
    "מי יכולה להמליץ",
    "מי יכול להמליץ",
    "מי יכולות להמליץ",
    "מנסה שוב:",
    "שאלה מאתגרת",
    "איזה עגלת קפה",
    "איזו מסעדת",
    "איזה מסעדת",
    # «יש מסעדה חדשה… מישהו יודע איך קוראים לה?»
    "איך קוראים לה",
    "איך קוראים לו",
    "מישהו יודע במקרה",
    "מישהי יודעת במקרה",
    "מישהו יודע איך קוראים",
    "מישהי יודעת איך קוראים",
)

_EXCLUDE = (
    "נרצחו באכזריות",
    "קיבוץ חולית נחרב",
    "המלצות על מלון",
    "מלון ומסעדות ברומא",
    "מורה פרטי",
    "מורה למתמטיקה",
    "אינסטלטור",
    "חשמלאי",
    "רופא ",
    "וטרינר",
    "פסיכולוג",
    "טכנאי",
    "מעצב",
    "צלם ",
    "נגר ",
    "שיפוצניק",
    "עורך דין",
    "מאמן כושר",
    "מחפשת המלצות ל",
    "מחפש המלצות ל",
    "ביקשו להפיץ",
    "vcf",
    ".vcf",
)

_BAD_NAME_FRAGMENTS = frozenset(
    {
        "מישהי",
        "מישהו",
        "שם",
        "אתמול",
        "היום",
        "מחר",
        "שם המסעדה",
        "פה",
        "שם",
        "אכזריות",
    }
)

# «באוקטובר» נתפס בטעות כ־ב+שם עסק בגלל פסיק אחרי החודש
_HEBREW_MONTHS = frozenset(
    {
        "ינואר",
        "פברואר",
        "מרץ",
        "אפריל",
        "מאי",
        "יוני",
        "יולי",
        "אוגוסט",
        "ספטמבר",
        "אוקטובר",
        "נובמבר",
        "דצמבר",
    }
)

# אחרי "גם … ב" — לא שמות מקום
_GAM_STOP = frozenset(
    {
        "אני",
        "אתה",
        "אתם",
        "אתן",
        "אנחנו",
        "הם",
        "הן",
        "זה",
        "זו",
        "מה",
        "שם",
        "כל",
        "כמה",
        "כולם",
        "כן",
        "לא",
        "פה",
        "שם",
        "יש",
        "אין",
    }
)


def _scan_exclude(body: str) -> bool:
    b = body.casefold()
    return any(x.casefold() in b for x in _EXCLUDE)


def _scan_has_food(body: str) -> bool:
    return any(x in body for x in _FOOD)


def _scan_has_strong_recommend(body: str) -> bool:
    return any(x in body for x in _STRONG_RECOMMEND)


def _scan_is_recommendation_request(body: str) -> bool:
    """True if the message reads like asking for tips, not giving one."""
    return any(x in body for x in _REQUEST)


def _scan_venue_plus_bazor_question_without_rec(body: str) -> bool:
    """«מסעדת … באזור?» / «בית קפה … באזור?» בלי ניסוח ממליץ — כמעט תמיד בקשה."""
    if _scan_has_strong_recommend(body):
        return False
    if "?" not in body:
        return False
    b = normalize_spaces(body)
    if re.search(r"מסעד[הת]\s+.{1,120}באזור", b):
        return True
    if re.search(r"מסעד[הת]\s+.{1,120}באיזור", b):
        return True
    if re.search(r"בית קפה\s+.{1,120}באזור", b):
        return True
    if re.search(r"בית קפה\s+.{1,120}באיזור", b):
        return True
    return False


def _scan_explicit_venue(body: str) -> bool:
    return bool(
        re.search(r"מסעד[הת]\s", body)
        or re.search(r"בית קפה\s", body)
        or re.search(r"קפה\s+[א-ת]", body)
    )


_CITIES = (
    "תל אביב",
    'ת"א',
    "רעננה",
    "כפר סבא",
    "כפ״ס",
    "קניון הירוקה",
    "הירוקה",
    "יהוד",
    "נתניה",
    "חיפה",
    "ירושלים",
    "הוד השרון",
    "אילת",
    "הרצליה",
    "רמת גן",
    "גבעתיים",
    "פתח תקווה",
    "קרית אונו",
    "רמת החייל",
    "יפו",
    "נווה צדק",
    "זכרון יעקב",
    "אחד העם",
    "פלורנטין",
    "שוק מחנה יהודה",
    "בי אנד סאן",
    "שדרות",
)


def _guess_location(body: str) -> str:
    hits = [c for c in _CITIES if c in body]
    if not hits:
        return ""
    # prefer longer city names first
    hits.sort(key=len, reverse=True)
    return hits[0][:200]


def _guess_type(body: str) -> str:
    if "סושי" in body:
        return "סושי / אסייתי"
    if "פיצה" in body:
        return "פיצה"
    if "חומוס" in body or "פלאפל" in body:
        return "חומוס / מזרח תיכוני"
    if "בראנץ" in body or "ברנץ" in body or "ארוחת בוקר" in body:
        return "בראנץ' / ארוחת בוקר"
    if "בית קפה" in body or re.search(r"\bקפה\s+[א-ת]", body):
        return "בית קפה"
    if "איטלק" in body or "פסטה" in body:
        return "איטלקית"
    return "מסעדה (חילוץ צ'אט)"


def _clean_name(raw: str) -> str:
    s = normalize_spaces(raw)
    s = s.strip(' "\'"״׳-–')
    s = re.sub(r"\s+", " ", s)
    if len(s) < 2 or len(s) > 55:
        return ""
    low = s.lower()
    if low in _BAD_NAME_FRAGMENTS or s in _BAD_NAME_FRAGMENTS:
        return ""
    first_tok = (s.split() or [""])[0]
    if s in _HEBREW_MONTHS or first_tok in _HEBREW_MONTHS:
        return ""
    if re.fullmatch(r"[\d\s\-\+\.]+", s):
        return ""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^\*+\s*|\s*\*+$", "", s).strip()
    # drop trailing parenthetical English only
    s = re.sub(r"\s*\([A-Za-z][^)]{0,40}\)\s*$", "", s).strip()
    s = re.sub(r"\s+ביום\s+שישי\b.*$", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"\s*\(מעולה.*$", "", s, flags=re.UNICODE).strip()
    s = s[:120]
    if not is_plausible_restaurant_name(s):
        return ""
    return s


def _extract_names(body: str) -> list[str]:
    names: list[str] = []
    # מסעדת שם / מסעדה שם
    for pat in (
        r"מסעדת\s+([^\n\.,:;!?]{2,55})",
        r"מסעדה\s+([^\n\.,:;!?]{2,50})",
        r"בית קפה\s+([^\n\.,:;!?]{2,50})",
    ):
        for m in re.finditer(pat, body):
            names.append(m.group(1).strip())
    # קפה שם (not "קפה של")
    for m in re.finditer(r"קפה\s+((?!של\s|זה\s)[א-ת][^\n\.,:;!?]{1,45})", body):
        names.append(m.group(1).strip())
    # במסעדת X
    for m in re.finditer(r"במסעד[הת]\s+([א-ת][^\n\.,:;!?]{1,45})", body):
        names.append(m.group(1).strip())
    # בגומבה / בזינק — short Hebrew token after ב
    for m in re.finditer(
        r"(?:^|[\s,.;:!?])ב([א-ת][א-ת']{1,18})(?=\s+ב(?:רעננה|כפר סבא|תל אביב|יהוד|נתניה|חיפה|הוד|קניון|שוק|יפו|זכרון)|\s+פתוח|\s+למשלוח|\s*$|[,.!?])",
        body,
    ):
        names.append(m.group(1).strip())
    # גם X ב...
    for m in re.finditer(r"(?:^|[\s,;])גם\s+([א-ת][א-ת0-9\s']{1,25}?)\s+ב", body):
        chunk = m.group(1).strip()
        first = chunk.split()[0] if chunk.split() else ""
        if first and first not in _GAM_STOP:
            names.append(chunk)
    # quoted
    for m in re.finditer(r'[""׳״]([^""׳״]{2,42})[""׳״]', body):
        t = m.group(1).strip()
        if any(f in t for f in _FOOD) or "מסעד" in t:
            names.append(t)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        k = n.casefold().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def extract_restaurants_from_chat_scan(
    text: str,
    *,
    slug_id,
) -> list[dict]:
    """
    Walk all messages; emit one entry per extracted venue name per message (merge later in pipeline).
    ``slug_id`` is the same callable as in extract_restaurants_whatsapp (stable id).
    """
    rows: list[dict] = []
    for date, sender, body in iter_whatsapp_messages(text):
        if not body or len(body) < 10:
            continue
        if body == "<Media omitted>":
            continue
        nb = normalize_spaces(body)
        if _scan_exclude(nb):
            continue
        if not _scan_has_food(nb):
            continue
        if _scan_is_recommendation_request(nb):
            continue
        if _scan_venue_plus_bazor_question_without_rec(nb):
            continue
        if not (_scan_explicit_venue(nb) or _scan_has_strong_recommend(nb)):
            continue
        names = _extract_names(nb)
        if not names:
            continue
        loc = _guess_location(nb)
        rtype = _guess_type(nb)
        src = f"חילוץ אוטומטי מצ'אט · {sender} · {date}"
        snippet = nb[:550]
        for raw in names:
            name = _clean_name(raw)
            if not name:
                continue
            rows.append(
                {
                    "id": slug_id("scan:" + name + date + sender[:20]),
                    "name": name,
                    "restaurant_type": rtype[:150],
                    "location": loc,
                    "note": src[:400],
                    "extra_info": snippet[:600],
                }
            )
    return rows
