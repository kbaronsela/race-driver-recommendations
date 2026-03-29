# -*- coding: utf-8 -*-
"""
Heuristic scan of a full WhatsApp export for restaurant-related messages.
Produces the same dict shape as extract_restaurants_whatsapp (note=מקור, extra_info=טקסט).

Messages qualify only with **food/venue context**: either explicit wording (מסעדת… / בית קפה… / קפה + שם),
or a **strong** recommend ("מומלץ"/"ממליצ"…) **together with** a concrete food/dining anchor (מפי _FOOD_ANCHOR) —
not recommendation alone on unrelated topics. בקשות להמלצות נזרקות; 🙏 (כולל גווני עור) מוחלף ב־«בבקשה» לפני בדיקת _REQUEST. Tune _FOOD_ANCHOR / _STRONG_RECOMMEND / _REQUEST / _EXCLUDE as needed.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterator

from restaurant_name_plausible import is_chat_junk_extracted_name, is_plausible_restaurant_name

# --- message splitting (WhatsApp Android/iOS export style) ---
_MSG_HEAD = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4},\s*\d{1,2}:\d{2})\s*-\s*([^:]+):\s*(.*)\s*$"
)


def parse_whatsapp_message_year(date_str: str) -> int | None:
    """מחזיר שנה ממחרוזת תאריך בכותרת ייצוא WhatsApp («DD/MM/YYYY, HH:MM»)."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", (date_str or "").strip())
    if not m:
        return None
    return int(m.group(3))
# 🙏 / 🙏🏻 / 🙏‍♀️ / 🙏‍♂️ … — בבדיקת בקשות נחשב כמו המילה «בבקשה»
# סדר מילוי: קודם רצפים ארוכים (עור+ZWJ+מגדר), אחר כך ZWJ+מגדר, אחר כך פשוט
_PRAYER_EMOJI_VARIANTS = (
    re.compile(
        r"\U0001f64f(?:\U0001f3fb|\U0001f3fc|\U0001f3fd|\U0001f3fe|\U0001f3ff)"
        r"\u200d(?:\u2640|\u2642)\uFE0F?"
    ),
    re.compile(r"\U0001f64f\uFE0F?\u200d(?:\u2640|\u2642)\uFE0F?"),
    re.compile(
        r"\U0001f64f\uFE0F?(?:\U0001f3fb|\U0001f3fc|\U0001f3fd|\U0001f3fe|\U0001f3ff)?"
    ),
)
# «בבית קפה» מכילה «בית קפה» — לא לתפוס את אותה הופעה כ«בית קפה + שם» (למשל «בבית קפה בתקופות…»)
_BAYIT_KAFEH_STANDALONE = re.compile(r"(?<![ב])בית קפה")

# אחרי «בבית קפה » — לא שם מקום אלא תיאור זמן/מצב (לא אוכל)
_BABAYIT_KAFEH_TAIL_JUNK_FIRST = frozenset(
    {
        "בתקופות",
        "בזמן",
        "במשך",
        "בימים",
        "בחודשים",
        "בשנת",
        "בעת",
    }
)


def _junk_babayit_kafeh_capture(tail: str) -> bool:
    """True אם מה שאחרי «בבית קפה » הוא לא שם עסק (למשל «בתקופות קצת…»)."""
    t = normalize_spaces((tail or "").strip())
    if not t:
        return True
    first = (t.split() or [""])[0]
    return any(first.startswith(p) for p in _BABAYIT_KAFEH_TAIL_JUNK_FIRST)


def _body_for_request_scan(body: str) -> str:
    """מחליף אמוג'י תפילה ב־«בבקשה» כדי ש־_REQUEST ייתפוס ניסוחים כמו «המלצה… 🙏»."""
    s = normalize_spaces(body)
    for pat in _PRAYER_EMOJI_VARIANTS:
        s = pat.sub(" בבקשה ", s)
    return normalize_spaces(s)


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


def iter_whatsapp_messages_since(
    text: str, min_year: int | None = None
) -> Iterator[tuple[str, str, str]]:
    """
    כמו iter_whatsapp_messages, אבל מדלג על הודעות שתאריך הכותרת שלהן לפני min_year.
    כש־min_year הוא None — אין סינון. בודקים שנה לפני כל עיבוד על גוף ההודעה.
    """
    for date, sender, body in iter_whatsapp_messages(text):
        if min_year is not None:
            y = parse_whatsapp_message_year(date)
            if y is None or y < min_year:
                continue
        yield date, sender, body


def normalize_sender(s: str) -> str:
    s = (s or "").replace("\u200e", "").replace("\u200f", "").replace("\u202a", "").replace("\u202c", "")
    s = re.sub(r"^[‎‏‫‬\s]+|[‎‏‫‬\s]+$", "", s)
    return s.strip()


def normalize_spaces(s: str) -> str:
    s = s.replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    return re.sub(r"\s+", " ", s).strip()


def _strip_whatsapp_export_meta(text: str) -> str:
    """מסיר סימוני עריכה/מטא שמצורפים לטקסט בייצוא וואטסאפ."""
    s = text or ""
    s = re.sub(r"\s*<This message was edited>\s*", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*<הודעה זו נערכה>\s*", " ", s)
    s = re.sub(r"\s*<הודעה נערכה>\s*", " ", s)
    return normalize_spaces(s)


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

# רמזים שמצביעים שההודעה *עוסקת באוכל / מסעדה / משקה במקום אוכל* — לצימוד עם המלצה חזקה כשאין ניסוח מפורש של שם מקום
_FOOD_ANCHOR = (
    "מסעדת ",
    "מסעדה ",
    "במסעד",
    "למסעד",
    "ממסעד",
    "בית קפה",
    "עגלת קפה",
    "קפה ",
    " בקפה",
    " לקפה",
    " מקפה",
    "פיצה",
    " סושי",
    "סושי ",
    "חומוס",
    "פלאפל",
    "ארוחת בוקר",
    "ארוחת ערב",
    "ארוחת צהריים",
    "בראנץ",
    "ברנץ",
    "מאפייה",
    "מאפה ",
    "פסטה",
    "איטלק",
    "אסיית",
    "תאילנד",
    "פרסית",
    "לבנונ",
    "סטייק",
    "המבורגר",
    "נודלס",
    "רמן",
    # לא «דגים» לבד — מתאים גם ל«דגים ופירות ים» (קטגוריה, לא מקום); מסעדת דגים נשאר דרך «מסעד…»
    "מטבח ",
    "משלוחי ",
    "משלוחים ",
    "דוכן ",
    "יקב ",
    "לאכול",
    "מקום לאכול",
    "פאב",
    "נשנוש",
    "קינוח",
    "מנות ",
    "תפריט",
    "דוכן אוכל",
    "מוצרי מזון",
    "עסקי מזון",
    "שוק מחנה",
    " בשוק ",
    " בר ",
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
    # אחרי החלפת 🙏 ב־«בבקשה» — בקשת המלצות (למשל «טוב בבוקר☕️ תודה מראש🙏»)
    "תודה מראש בבקשה",
    "בבקשה תודה מראש",
    # תיאור מקום לארוחה + 🙏 — בקשה (למשל «טובה ורומנטית לשישי בערב 🙏»)
    "טובה ורומנטית לשישי בערב בבקשה",
    "בבקשה טובה ורומנטית לשישי בערב",
    "לשישי בערב בבקשה",
    "בבקשה לשישי בערב",
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
    # בקשות — ניסוח «המלצה למסעד…» / «המלצה לבית קפה ב…» (לא תשובה)
    "המלצה לבית קפה",
    "המלצות לבית קפה",
    "המלצה לקפה ",
    "המלצה לבר",
    "המלצה לבר/",
    "המלצות לבר",
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
    "איך קוראים לבית קפה",
    "איך קוראים לבית הקפה",
    "איך קוראים למסעדה",
    "איך קוראים למסעדת",
    "מישהו יודע במקרה",
    "מישהי יודעת במקרה",
    "מישהו יודע איך קוראים",
    "מישהי יודעת איך קוראים",
    # שמעו על מקום / מבקשים חוות דעת — לא המלצה
    "שמעה על מסעד",
    "שמעתי על מסעד",
    "שמעת על מסעד",
    "שמעו על מסעד",
    "מישהו שמע על",
    "מישהי שמעה על",
    "נשמע על מסעד",
    # שאלות מיקום / «איפה …?» — לא המלצה (גם כשמופיעים יחד שאלות רפואה ואוכל)
    "איפה בית הקפה",
    "איפה יש בית קפה",
    "איפה יש מסעד",
    "איפה המסעדה",
    "איפה זה קפה",
    "איפה זה בית קפה",
    "איפה זה בית הקפה",
    "איפה זה המסעדה",
    "הייתי שמחה לקבל",
    "הייתי שמח לקבל",
    "נשמח לקבל כל מידע",
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
    # טקסטים ארוכים / לא אוכל — נתפסים בטעות בגלל «מסעדה» / «קפה»
    "הכי משמעותי ומעורר שקראתי",
    "עיסוי תינוקות",
    "מעגל אימהות",
    "על העיוורון / אמילי עמרוסי",
    # לוח חסימות / הפגנות / תנועה — לא המלצות אוכל (גם אם מופיע «קפה …» / «ארקפה» ברשימה)
    "חסימת הצמתים",
    "חסימות הצמתים",
    "צעדה להסתדרות",
    "מחאת ההייטקיסטים",
    "מחאת הגלימות",
    "שיירת הצפון",
    "יציאה לשיירה",
    # טכנולוגיה / אבטחה / הזדהות — לא אוכל (גם כשמופיע רמז שוואי מתוך «התקפה»→«קפה»)
    "דיסק הקשיח",
    "תפרמט לכם את הטלפון",
    "אגף טכנולוגיות מידע",
    "טכנולוגיות מידע – משרד",
    "שיחות לא מזוהות בשום מקרה",
    # אירועים / מפגשים עסקיים בבית קפה — לא המלצה על מקום אוכל (גם אם מצוין «בקפה …»)
    "דילמה עסקית",
    "דילמות עסקיות",
    "למי יש דילמה",
    "לפתרון דילמות עסקיות",
    "יעסוק בפתרון דילמות",
    # ניהול קהילתי / ועד — לא המלצות אוכל (גם אם מוזכר «בית קפה» בתכנון עתידי)
    "ועד האגודה והנהלת",
    "ועד האגודה משיקוליו",
    "דרישה להסדיר מספר עניינים במושב",
    # מועדון / פעילות לניצולי שואה — לא המלצת אוכל
    "מועדון אזורי לניצולי שואה",
    "מועדון אזורי לניצולי שואה במועצה שלנו",
    "מועדון לניצולי שואה",
    "לניצולי שואה במועצה",
    "ניצולי שואה במועצה",
    "קפה בשדה\"- מועדון אזורי",
    "קפה בשדה- מועדון לניצולי שואה",
    # חדשות / תנועה / משפטים — לא המלצות אוכל (גם אם מופיע «מסעדה»)
    "כרגע בתקיפה ארצית של המנהל",
    "תקיפה ארצית של המנהל",
    "לבר ומהבר שוב למסעדה",
    "ל24 שעות",
    "ל 24 שעות",
    # דיגסט הרצאות / קהילת מרצים — לא המלצות אוכל (גם כשמופיעים «מומלץ», «לאכול», «קפה מהמכונה»)
    "נטוורקינג למרצים",
    "תכנית ההרצאות",
    # פלייר / חיילת שמוכרת קינוחים מהבית — לא מסעדה
    "מעבירה אליכם פלייר",
    "מתמחה בקינוחים",
)

# מוצרי קפה לבית / אריזות — לא המלצת מסעדה (גם אם מופיע «קפה» / «מסעדה» בשארית)
_EXCLUDE_COFFEE_PRODUCT = (
    "מכונת קפה",
    "מכונות קפה",
    "קפסולות קפה",
    "קפסולות נספרסו",
    "קפסולות לנספרסו",
    "קפסולות למכונת",
    "קפסולות",
    "קפסולת",
    "שקיות קפה",
    "שקית קפה",
    "חבילות קפה",
    "חבילת קפה",
    "אבקת קפה",
    "אבקת נמס",
    "קפה נמס",
    "קפה בקפסולות",
    "קפה טחון",
    "פולי קפה",
    "טחינת קפה",
    "סוגי קפה",
    " סוג קפה",
    "סוג קפה ",
    "נספרסו",
    "פודים",
    "פוד ",
    "מילוי קפסול",
    "תואם למכונת",
    "תואם נספרסו",
    "תואם לנספרסו",
    "טורקי סגורות",
    "טורקי סגורות חדשות",
    "סגורות חדשות בתוקף",
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
# אחרי «קפה » — לא שם עסק אלא מקום/גוף («קפה ביד», «קפה בגינה»)
_CAFE_CAPTURE_SKIP_PREFIX = (
    "ביד",
    "בפה",
    "בבית",
    "בגינה",
    "בחצר",
    "בהוד",
    "בכיכר",
    "במרפסת",
    "בדרך",
    "במכונית",
    "ברכב",
    "באוטו",
)

# מקטע מתוך «המסעדה בימי…» / ימים — לא שם
_MESADA_CAPTURE_SKIP_PREFIX = ("בימי", "ביום", "בשבת", "בחג", "בלילה", "בערב")

# אחרי «ב»+שם: לא לתפוס «בו…» קצר (בובה→ובה, בוולט→וולט, בוהריים→והריים); חריגים נדירים
_BE_VAV_INNER_MAX_LEN = 6
_BE_VAV_INNER_ALLOW = frozenset(
    {
        "וושינגטון",
        "ווינה",
    }
)

_HEB_WORD_AT = re.compile(r"[א-ת׳״']+")


def _be_prefix_capture_ok(body: str, m: re.Match) -> bool:
    """
    דפוס (תחילית)ב+שם: לוודא שלא מדובר בפיצול של מילה ב+ו… (בוגר, בובה, בוינגייט)
    ולא בחיתוך באמצע מילה ארוכה יותר (ב+צופי כשהמילה המלאה בצופית).
    """
    name = (m.group("name") or "").strip()
    if not name:
        return False
    bet_start = m.start("bet")
    wmatch = _HEB_WORD_AT.match(body, bet_start)
    full = wmatch.group(0) if wmatch else ""
    if full and len(full) > 1 + len(name):
        return False
    if (
        name.startswith("ו")
        and name not in _BE_VAV_INNER_ALLOW
        and len(name) <= _BE_VAV_INNER_MAX_LEN
    ):
        return False
    # «בבירה» / «בבקשה» / «במכולת» — תחיליות מיקום או ניסוח, לא שם עסק
    if name == "בירה" and full == "בבירה":
        return False
    if name == "בקשה" and full == "בבקשה":
        return False
    # «בגין» (בית ספר בגין, רחוב בגין) — לא «מסעדת גין»
    if name == "גין" and full == "בגין":
        return False
    if full.startswith(
        (
            "במכולת",
            "במשק",
            "במתחם",
            "בכניסה",
            "בכוסות",
            "בבקשה",
            "בכפר",
        )
    ):
        return False
    return True


# תפיסה מ־«ב» לפני עיר / סוף משפט — לא שם מסעדה (בהסגר, בוולט, בוגר→וגר)
_BE_CAPTURE_JUNK = frozenset(
    {
        "איטליזים",
        "אתר",
        "ביט",
        "ביד",
        # ב־+ה… / ביטויים תחביריים
        "הסגר",
        "העברה",
        "הערב",
        "הפתעה",
        "הצלחה",
        "הקדם",
        "הרצאה",
        "התאם",
        "התנדבות",
        # שארית מ־בואו / בוולט / בוטיק / בוכה / בודדים / בוינגייט / בויתקין
        "ואו",
        "וגר",
        "וגרות",
        "ודד",
        "ודדים",
        "וכה",
        "וטיק",
        "וינגייט",
        "ויתקין",
        "וולט",
        "וואטפס",
        # שארית מ־בובה / בוקר / בואכם / בורוכוב (ב+ו…)
        "ובה",
        "ואכם",
        "וקר",
        "ורוכוב",
        "גין",
        # «רק במטבח» / סוף משפט — לא «במסעדת מטבח»
        "מטבח",
    }
)

_BE_IN_CITY = re.compile(
    r"(?P<prefix>(?:^|[\s,.;:!?]))(?P<bet>ב)(?P<name>[א-ת][א-ת']{1,18})"
    r"(?=\s+ב(?:רעננה|כפר סבא|תל אביב|יהוד|נתניה|חיפה|הוד|קניון|שוק|יפו|זכרון)|\s+פתוח|\s+למשלוח|\s*$)",
)

# «המפלט האחרון - מסעדת דגים מעולה» — השם הוא לפני המקף; אחרי «מסעדת» זה תיאור מטבח לא שם המותג
_DASH_NAME_THEN_MASADAT = re.compile(
    r"(?:^|[\s.,:;!?])"
    r"([א-ת][א-ת0-9\s''״]{1,42}?)\s*[-–—]\s*"
    r"מסעד[הת]\s+(?!ו)([^\n\.,:;!?]{2,55})",
    re.UNICODE,
)

_DASH_LEAD_FIRST_WORD_BAD = frozenset(
    {
        "ב",
        "ל",
        "מ",
        "של",
        "על",
        "עם",
        "את",
        "גם",
        "יש",
        "כל",
        "לא",
        "כי",
        "אבל",
        "או",
        "זה",
        "זו",
        "מה",
        "איך",
        "למה",
    }
)

# שמות שחולצו בטעות מתיאורים / מועדון / משפט — לא עסקי מזון
_JUNK_VENUE_NAME_EXACT = frozenset(
    {
        "גדול",
        "גדים",
        "חום",
        "חוםםםםםם",
        "חד פעמית",
        "חופש",
        "חזית",
        "חיינו",
        "חינם",
        "חירתכם",
        "חלל",
        "חשבון",
        "טבע",
        "טוח",
        "טלוויזיה",
        "יום יומית",
        "יומן",
        "יומו",
        "יטוחים",
        "יטחוני",
        "ימיינו",
        "ינוני",
        "יניהם",
        "יקורת",
        "יתי",
        "כבר ראיתי",
        "כולנו",
        "כושר",
        "כי",
        "כלל",
        "לבד",
        "ליבם",
        "חרוצים",
        "טובה ורומנטית לשישי בערב",
        "טורקי סגורות חדשות בתוקף עד יולי",
        "מעל שבועיים",
    }
)


def _junk_extracted_venue_name(raw: str) -> bool:
    """True = זרוק — לא שם מסעדה אמיתי."""
    s = normalize_spaces((raw or "").strip())
    if not s:
        return True
    if is_chat_junk_extracted_name(s):
        return True
    # קטגוריית מטבח — לא שם עסק (גם «פרות» שגיאת הקלדה)
    if "דגים ופירות ים" in s or "דגים ופרות ים" in s:
        return True
    # שארית מ־«מכונת הקפה הישנה שלכם» — לא שם עסק
    if re.fullmatch(r"(?:הישנה|הישן)\s+של(כם|נו|ך|הם|הן|כן)", s):
        return True
    if re.fullmatch(r"הנחמד הקרוב\??", s):
        return True
    if any(w in s for w in ("דיסק הקשיח", "תפרמט", "וירוס ", "טכנולוגיות מידע")):
        return True
    # מושג מתוך הזמנה למפגש («למי יש דילמה עסקית?») — לא שם מסעדה
    if re.fullmatch(r"\*?דילמה\*?\??", s):
        return True
    # שארית מ־«בבית קפה בתקופות…» / תיאור זמן
    if re.match(r"^בתקופות\b", s) or re.match(r"^בזמן\b", s) or re.match(r"^במשך\b", s):
        return True
    if "חלוש ידבר איתך" in s or "בתעסוקה ומגורים" in s:
        return True
    # מוצרי קפה / אריזות / מכונה — לא שם מסעדה
    if "טורקי" in s and "סגורות" in s:
        return True
    if any(
        w in s
        for w in (
            "מכונת קפה",
            "מכונות קפה",
            "קפסולות",
            "נספרסו",
            "קפה נמס",
            "אבקת קפה",
            "שקית קפה",
            "שקיות קפה",
            "חבילת קפה",
            "חבילות קפה",
            "פולי קפה",
            "קפה בקפסולות",
        )
    ):
        return True
    if s in _JUNK_VENUE_NAME_EXACT:
        return True
    # תיאור אירוע / מגורים / שולחן — לא שם מסעדה
    if s in (
        "מאפה ופירות",
        "בשיכון",
        "בשולחן הקינוחים",
        "קינוחים",
        "נייד",
    ):
        return True
    if s.startswith("בשיכון בנים"):
        return True
    if re.fullmatch(r"ל\s*24\s*שעות", s):
        return True
    if re.fullmatch(r"חוםם+", s):
        return True
    if s in _BE_CAPTURE_JUNK:
        return True
    for p in _CAFE_CAPTURE_SKIP_PREFIX:
        if s.startswith(p):
            return True
    for p in _MESADA_CAPTURE_SKIP_PREFIX:
        if s.startswith(p):
            return True
    if "מוצרים אחרים" in s:
        return True
    if "אחלה" in s and "מוצרים" in s:
        return True
    if "ברוב האנשים אין גינה" in s or "באוירה פסטורלית" in s:
        return True
    if s.startswith("באתר "):
        return True
    if "איטליה בסמוך" in s:
        return True
    # שאריות מ־בוהריים / בהתה / רשימות אחרי «קפה» שעדיין דולפות
    for p in (
        "והריים",
        "והתה",
        "ואוכל",
        "וארוחת",
        "וגם ",
        "ומאפה",
        "ומסעדות",
        "ונשנוש",
        "וסנדוויץ",
        "ועוגה",
        "ושוקולד",
        "ותבלינים",
        "ולא ",
        "ומאוד ",
        "ומשהו ",
        "ומוסיקה",
        "ונאלץ ",
        "וגרמת",
        "ותה עלינו",
        "ותה ונותנת",
    ):
        if s.startswith(p):
            return True
    # ביטויי מיקום / משפט אחרי «קפה» / «בית קפה» / «מסעדה» — לא שם מותג
    for p in (
        "במכולת",
        "במשק",
        "במתחם",
        "בכניסה",
        "בכוסות",
        "בבקשה",
        "בכפר",
    ):
        if s.startswith(p):
            return True
    if s in (
        "בקשה",
        "בקשישים",
        "ברזילאית",
        "מכולת",
    ):
        return True
    if s.startswith("בתוך "):
        return True
    return False


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
        # «גם הפתעה בתפקיד» / «גם העברה…» — לא שם מקום
        "הסגר",
        "העברה",
        "הערב",
        "הפתעה",
        "הצלחה",
        "הקדם",
        "הרצאה",
        "התאם",
        "התנדבות",
        # «גם בתוך המים… ביחד» — לא «גם שם מקום ב…»
        "בתוך",
        "בלי",
    }
)


def _scan_exclude(body: str) -> bool:
    b = body.casefold()
    if any(x.casefold() in b for x in _EXCLUDE):
        return True
    return any(x.casefold() in b for x in _EXCLUDE_COFFEE_PRODUCT)


def _scan_body_is_hairdressing_not_food(body: str) -> bool:
    """
    המלצה על ספרית / תספורת (לעיתים ליד «עגלת קפה») — לא המלצת אוכל.
    לדוגמה: «שמספרת … בעגלת הקפה צ'ופצ'יק» עם קישורי IG לשיער.
    """
    b = normalize_spaces(body)
    bl = b.casefold()
    if "שמספרת" in b:
        return True
    if "yourhair" in bl or "frizura" in bl or "inyourhair" in bl:
        return True
    if "בעגלת הקפה" in b and "ספרית" in b:
        return True
    if "תספורת" in b and "בעגלת הקפה" in b:
        return True
    return False


def _scan_has_food_anchor(body: str) -> bool:
    """האם יש בהודעה הקשר מפורש לאוכל / מסעדה / קפה (לא רק «שוק» / מילה כללית)."""
    for a in _FOOD_ANCHOR:
        if a == "בית קפה":
            if _BAYIT_KAFEH_STANDALONE.search(body) or "בבית קפה" in body:
                return True
            continue
        # «מוזמנות» מכילה את תת־המחרוזת «מנות » — לא מנות אוכל
        if a == "מנות ":
            if re.search(r"(?<!ז)מנות\s", body):
                return True
            continue
        if a != "קפה ":
            if a in body:
                return True
            continue
        for m in re.finditer(re.escape(a), body):
            if not _kafeh_is_cafe_word_not_subword_noise(body, m.start()):
                continue
            return True
    return False


def _scan_qualifies_for_chat_extraction(body: str) -> bool:
    """
    כניסה לחילוץ שמות: או ניסוח מקום (מסעדת… / בית קפה… / קפה + שם),
    או המלצה חזקה *בתוספת* רמז אוכל — לא המלצה על נושא אחר.
    """
    if _scan_explicit_venue(body):
        return True
    if _scan_has_strong_recommend(body) and _scan_has_food_anchor(body):
        return True
    return False


def _scan_has_strong_recommend(body: str) -> bool:
    return any(x in body for x in _STRONG_RECOMMEND)


def _scan_is_recommendation_request(body: str) -> bool:
    """True if the message reads like asking for tips, not giving one."""
    b = _body_for_request_scan(body)
    return any(x in b for x in _REQUEST)


def _scan_opinion_or_gossip_about_venue(body: str) -> bool:
    """
    שאלות סוג «מסעדת X …? איך היא?» / «מה דעת» — מבקשות חוות דעת, לא ממליצות.
    רק כשאין ניסוח ממליץ חזק באותה הודעה.
    """
    if _scan_has_strong_recommend(body):
        return False
    b = normalize_spaces(body)
    if "?" not in b:
        return False
    if (
        not re.search(r"מסעד[הת]\s", b)
        and not _BAYIT_KAFEH_STANDALONE.search(b)
        and "בית הקפה" not in b
    ):
        return False
    gossip = (
        "איך היא",
        "איך הוא",
        "מה דעת",
        "מה אתן אומרות",
        "מה אתם אומרים",
        "מה חווית",
        "מישהו ניסה",
        "מישהי ניסתה",
        "מישהו היה שם",
        "מישהי הייתה שם",
        "מישהו יכול לספר",
        "מישהי יכולה לספר",
        "מישהו מכיר את",
        "מישהי מכירה את",
        "שווה את זה",
        "שווה ללכת",
    )
    return any(g in b for g in gossip)


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
    if re.search(r"(?<![ב])בית קפה\s+.{1,120}באזור", b):
        return True
    if re.search(r"(?<![ב])בית קפה\s+.{1,120}באיזור", b):
        return True
    return False


def _scan_opening_shabbat_question_without_rec(body: str) -> bool:
    """
    «הבית קפה בחרוצים פתוח בשבת?» — שאלה על שעות/שבת, לא המלצה (גם אם נחלצת «חרוצים» כשם).
    """
    if _scan_has_strong_recommend(body):
        return False
    if "?" not in body:
        return False
    b = normalize_spaces(body)
    if "שבת" not in b:
        return False
    if not any(
        x in b
        for x in ("פתוח", "פתוחה", "פתוחים", "פתוחות", "סגור", "סגורה", "סגורים")
    ):
        return False
    if not (
        _BAYIT_KAFEH_STANDALONE.search(b)
        or "בית הקפה" in b
        or re.search(r"מסעד", b)
    ):
        return False
    return True


def _scan_where_food_question_without_rec(body: str) -> bool:
    """
    «איפה … בית קפה / מסעד… ?» בלי ניסוח ממליץ — בקשת מידע / המלצה מהקבוצה, לא המלצה.
    (למשל: «איפה בית הקפה הנחמד הקרוב?», «איפה יש… וכל המסעדות…?»)
    """
    if _scan_has_strong_recommend(body):
        return False
    if "?" not in body:
        return False
    b = normalize_spaces(body)
    if "איפה" not in b:
        return False
    if _BAYIT_KAFEH_STANDALONE.search(b) or "בית הקפה" in b or re.search(r"מסעד", b):
        return True
    return False


def _scan_message_ends_with_question_not_recommendation(body: str) -> bool:
    """
    הודעה שנגמרת ב־? — כמעט תמיד שאלה («פתוח בחול המועד?»), לא המלצה.
    אם יש באותה הודעה המלצה חזקה — לא מסננים (למשל שאלת המשך אחרי «מומלץ בחום»).
    """
    if _scan_has_strong_recommend(body):
        return False
    t = normalize_spaces(body).rstrip()
    return bool(t) and t.endswith("?")


# אחרי «קפה » — מילה שאינה שם עסק (שתייה במקום / תיאור), לא «קפה + מותג»
_CAFE_FIRST_WORD_NOT_VENUE = frozenset(
    {
        "בדשא",
        "בבית",
        "במשרד",
        "ברכב",
        "במכונית",
        "בכוס",
        "עם",
        "של",
        "בלי",
        "שחור",
        "חם",
        "קר",
        # אחרי «קפה» בתוך «בבית קפה …» — תיאור זמן/מצב, לא שם מקום
        "בתקופות",
        "בזמן",
        "במשך",
        "בימים",
        "בחודשים",
        "בשנת",
        "בעת",
        # «קפה מהמכונה» — לא שם מקום
        "מהמכונה",
    }
)


def _coffee_appliance_before_kafeh(body: str, kafeh_start: int) -> bool:
    """True אם «קפה» כאן הוא חלק ממכשיר («מכונת קפה» / «מכונות הקפה»), לא מקום לאכול."""
    if kafeh_start < 0 or kafeh_start > len(body):
        return False
    before = body[max(0, kafeh_start - 20) : kafeh_start]
    return bool(re.search(r"(?:מכונת|מכונות)(?:\s+ה)?\s*$", before))


def _kafeh_is_cafe_word_not_subword_noise(body: str, kafeh_start: int) -> bool:
    """
    «קפה» כבית קפה / שם — לא תת־מחרוזת של «התקפה» / «בהתקפה» (ה+ת+קפה).
    לא לדחות «בית קפה» — שם לפני «קפה» יש «ת» מ«בית» (לפני הת יש י, לא ה).
    """
    if (
        kafeh_start >= 2
        and body[kafeh_start - 1] == "ת"
        and body[kafeh_start - 2] == "ה"
    ):
        return False
    if _coffee_appliance_before_kafeh(body, kafeh_start):
        return False
    return True


def _scan_has_explicit_cafe_venue_name(body: str) -> bool:
    """«קפה X» כש־X נראה כמו שם מקום — לא «קפה בדשא» / «קפה עם סוכר»."""
    for m in re.finditer(r"קפה\s+", body):
        if not _kafeh_is_cafe_word_not_subword_noise(body, m.start()):
            continue
        rest = body[m.end() : m.end() + 45]
        mt = re.match(r"([^\s\.,:;!?]{1,24})", rest)
        if not mt:
            continue
        first = (mt.group(1).split() or [""])[0]
        if first in _CAFE_FIRST_WORD_NOT_VENUE:
            continue
        return True
    return False


def _scan_explicit_venue(body: str) -> bool:
    if re.search(r"מסעד[הת]\s", body):
        return True
    if re.search(r"(?<![ב])בית קפה\s", body):
        return True
    bm = re.search(r"בבית קפה\s+", body)
    if bm:
        tail = body[bm.end() : bm.end() + 80]
        if not _junk_babayit_kafeh_capture(tail):
            return True
    return _scan_has_explicit_cafe_venue_name(body)


def _build_location_canonical_to_aliases() -> dict[str, frozenset[str]]:
    """
    שם מלא → כל הצורות שמזוהות בטקסט (כולל קיצורים וראשי תיבות).
    הערך המוחזר מ־_guess_location / expand_location_abbreviations הוא תמיד השם המלא.
    """
    special: dict[str, frozenset[str]] = {
        "הוד השרון": frozenset(
            {
                "הוד השרון",
                "הוד\"ש",
                "הוד״ש",
                "הודש",
            }
        ),
        "רמת השרון": frozenset(
            {
                "רמת השרון",
                "רמה\"ש",
                "רמה״ש",
                "רמהש",
            }
        ),
        "תל אביב": frozenset({"תל אביב", "ת\"א", "ת״א"}),
        "כפר סבא": frozenset({"כפר סבא", "כפ\"ס", "כפ״ס"}),
        "פתח תקווה": frozenset({"פתח תקווה", "פ\"ת", "פ״ת"}),
        "זכרון יעקב": frozenset({"זכרון יעקב", "זכרון יעקוב"}),
    }
    base_only = (
        "רעננה",
        "קניון הירוקה",
        "הירוקה",
        "יהוד",
        "נתניה",
        "חיפה",
        "ירושלים",
        "אילת",
        "הרצליה",
        "רמת גן",
        "גבעתיים",
        "קרית אונו",
        "רמת החייל",
        "נווה צדק",
        "אחד העם",
        "פלורנטין",
        "שוק מחנה יהודה",
        "בי אנד סאן",
        "שדרות",
        "תל מונד",
        "כפר מונש",
        "קיבוץ העוגן",
    )
    m = dict(special)
    for c in base_only:
        m.setdefault(c, frozenset({c}))
    return m


# שם מלא → כינויים (לזיהוי בצ'אט ולהרחבה בשדה location)
LOCATION_CANONICAL_TO_ALIASES: dict[str, frozenset[str]] = _build_location_canonical_to_aliases()

def _be_suffix_alias_canonical_ordered() -> tuple[tuple[str, str], ...]:
    """כל כינוי מקום → שם קנוני, מהארוך לקצר (כולל כתיבים חלופיים כמו זכרון יעקוב)."""
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in LOCATION_CANONICAL_TO_ALIASES.items():
        for a in aliases:
            pairs.append((a, canonical))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return tuple(pairs)


_BE_SUFFIX_ALIAS_CANONICAL_ORDERED: tuple[tuple[str, str], ...] = (
    _be_suffix_alias_canonical_ordered()
)


def _split_trailing_be_place(name: str) -> tuple[str, str]:
    """«צ'אנג מאי בזכרון יעקוב» → (צ'אנג מאי, זכרון יעקב). אם אין התאמה — (name, '')."""
    s = normalize_spaces(name or "")
    if not s or " ב" not in s:
        return s, ""
    for alias, canonical in _BE_SUFFIX_ALIAS_CANONICAL_ORDERED:
        suf = f" ב{alias}"
        if s.endswith(suf):
            base = normalize_spaces(s[: -len(suf)])
            if len(base) >= 2:
                return base, canonical
    return s, ""


_BE_KIBBUTZ_IN_NAME = re.compile(
    r"^(.{2,50}?)\s+בקיבוץ\s+(.{2,80})$",
    re.UNICODE,
)


def _split_be_kibbutz(name: str) -> tuple[str, str]:
    """«גראציה בקיבוץ העוגן» → (גראציה, קיבוץ העוגן)."""
    s = normalize_spaces(name or "")
    m = _BE_KIBBUTZ_IN_NAME.match(s)
    if not m:
        return s, ""
    brand, k_tail = normalize_spaces(m.group(1)), normalize_spaces(m.group(2))
    k_tail = re.sub(r"\s*[-–—].*$", "", k_tail).strip()
    if len(brand) < 2 or len(k_tail) < 2:
        return s, ""
    return brand, f"קיבוץ {k_tail}"


def _split_name_location_suffixes(name: str) -> tuple[str, str]:
    """מנסה « ב<מקום> » ואז « בקיבוץ <שם> »."""
    base, loc = _split_trailing_be_place(name)
    if loc:
        return base, loc
    return _split_be_kibbutz(base)

# «יפו» כעיר — לא תת־מחרוזת של «סיפור», «חיפוש», «מיפוי» וכו׳
_IPPO_PLACE_RE = re.compile(
    r"(?:^|[^\u0590-\u05FF])(?:ב|ל|מ|כ)?יפו(?:$|\s|[^\u0590-\u05FF])",
    re.UNICODE,
)


def expand_location_abbreviations(loc: str) -> str:
    """
    מחליף קיצורים וראשי תיבות בשם העיר המלא; מנקה כפילויות אחרי איחוד (|).
    """
    s = normalize_spaces(loc or "")
    if not s:
        return ""
    pairs: list[tuple[str, str]] = []
    for canonical, aliases in LOCATION_CANONICAL_TO_ALIASES.items():
        for a in aliases:
            if a != canonical:
                pairs.append((a, canonical))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    for ab, canonical in pairs:
        if ab in s:
            s = s.replace(ab, canonical)
    s = normalize_spaces(s)
    parts = re.split(r"\s*\|\s*", s)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = normalize_spaces(p)
        if not p:
            continue
        k = p.casefold()
        if k not in seen:
            seen.add(k)
            out.append(p)
    joined = " | ".join(out)
    return joined[:250] if len(joined) > 250 else joined


def _guess_location(body: str) -> str:
    if not body:
        return ""
    hits: list[str] = []
    for canonical, aliases in LOCATION_CANONICAL_TO_ALIASES.items():
        if any(a in body for a in aliases):
            hits.append(canonical)
    if _IPPO_PLACE_RE.search(body):
        hits.append("יפו")
    if not hits:
        return ""
    uniq = list(dict.fromkeys(hits))
    uniq.sort(key=len, reverse=True)
    return uniq[0][:200]


def _guess_location_for_venue(body: str, venue_name: str) -> str:
    """
    כשבאותה הודעה מופיעים כמה יישובים — מנסים לקשור מקום לפי צמידות לשם המקום בטקסט
    (למשל נומי↔כפר מונש, מלצ'ט↔תל מונד).
    """
    if not body or not venue_name:
        return ""
    vn = venue_name.strip()
    window = 48
    if re.search(r"מלצ['\u05f3]ט", vn):
        if "תל מונד" in body and (
            re.search(
                rf"מלצ['\u05f3]ט.{{0,{window}}}תל מונד",
                body,
                re.DOTALL,
            )
            or re.search(
                rf"תל מונד.{{0,{window}}}מלצ['\u05f3]ט",
                body,
                re.DOTALL,
            )
        ):
            return "תל מונד"
    if "נומי" in vn:
        if "כפר מונש" in body and (
            re.search(rf"נומי.{{0,{window}}}כפר מונש", body, re.DOTALL)
            or re.search(rf"כפר מונש.{{0,{window}}}נומי", body, re.DOTALL)
        ):
            return "כפר מונש"
    return ""


def _guess_type(body: str) -> str:
    if "סושי" in body:
        return "סושי / אסייתי"
    if "פיצה" in body:
        return "פיצה"
    if "חומוס" in body or "פלאפל" in body:
        return "חומוס / מזרח תיכוני"
    if "בראנץ" in body or "ברנץ" in body or "ארוחת בוקר" in body:
        return "בראנץ' / ארוחת בוקר"
    if (
        _BAYIT_KAFEH_STANDALONE.search(body)
        or "בבית קפה" in body
        or re.search(r"\bקפה\s+[א-ת]", body)
    ):
        return "בית קפה"
    if "איטלק" in body or "פסטה" in body:
        return "איטלקית"
    # ברירת מחדל: ריק — לא «מסעדה (חילוץ צ'אט)» (מקור החילוץ כבר ב־note)
    return ""


# רצף לטיני באותיות קטנות בלבד (שגיאות מודל); לא נוגע ב־Timo / PE וכו'
_LATIN_LOWERCASE_JUNK = r"[a-z\u00E0-\u024F]{2,14}"


def scrub_latin_corruption_in_hebrew_venue_name(s: str) -> str:
    """
    מסיר רצפי לטינית שמודל או עיוות תווים דוחפים לתוך שם בעברית
    (למשל «ķafeה גן סיפור», «דגי האדי מifo»). לא נוגע בשם לטיני בלבד.
    """
    if not s or not re.search(r"[\u0590-\u05FF]", s):
        return s
    t = unicodedata.normalize("NFKC", s.strip())
    # אות לטינית בודדת לפני «פה» (עיוות/מודל: k במקום ק) — לדוגמה ķפה גן סיפור → קפה גן סיפור
    t = re.sub(r"^[\u0137\u0138ķkKqQ]\s*(?=פה)", "ק", t)
    lat = _LATIN_LOWERCASE_JUNK
    for _ in range(10):
        prev = t
        t = re.sub(rf"^{lat}(?=[\u0590-\u05FF])", "", t).strip()
        t = re.sub(rf"(?<=[\u0590-\u05FF])\s+{lat}\s*$", "", t, flags=re.UNICODE).strip()
        t = re.sub(
            rf"(?<=[\u0590-\u05FF])\s+{lat}(?=\s+[\u0590-\u05FF])",
            " ",
            t,
            flags=re.UNICODE,
        )
        t = re.sub(
            rf"(?<=[\u0590-\u05FF]){lat}(?=[\u0590-\u05FF])",
            " ",
            t,
            flags=re.UNICODE,
        )
        t = normalize_spaces(t)
        if t == prev:
            break
    # אחרי הורדת «cafe» לטינית נשאר לעיתים «ה גן סיפור» — שחזור סביר ל־«קפה גן סיפור»
    t = re.sub(r"^\s*ה\s+(?=גן סיפור\b)", "קפה ", t).strip()
    return t


def _clean_name(raw: str) -> str:
    s = _strip_whatsapp_export_meta(raw)
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
    # שבח בסוף השם («- נהדר», «— מעולה») — לא חלק מהמותג
    s = re.sub(
        r"\s*[-–—]\s*(?:נהדר|נהדרת|מעולה|מעולים|מעולות|טעים|טעימה|טעימים|שווה|מומלץ|מומלצת|מומלצים)\s*!*\s*$",
        "",
        s,
        flags=re.UNICODE,
    ).strip()
    # drop trailing parenthetical English only
    s = re.sub(r"\s*\([A-Za-z][^)]{0,40}\)\s*$", "", s).strip()
    s = re.sub(r"\s+ביום\s+שישי\b.*$", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"\s*\(מעולה.*$", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"\s+https?://\S+", "", s, flags=re.UNICODE).strip()
    s = re.sub(r"\s+https\s*$", "", s, flags=re.UNICODE | re.IGNORECASE).strip()
    s = re.sub(
        r"\s+(?:\+?972[\s\-]?\d{1,2}[\s\-]?\d{3}[\s\-]?\d{4}|0\d{1,2}[\s\-]?\d{3}[\s\-]?\d{4})\s*$",
        "",
        s,
        flags=re.UNICODE,
    ).strip()
    # סניף/אזור שצמוד לשם בלי « ב » (למשל «גן סיפור הוד"ש») — המיקום ייגזר מגוף ההודעה
    s = re.sub(r"^(גן סיפור)\s*הוד[\"״]ש\s*$", r"\1", s).strip()
    s = scrub_latin_corruption_in_hebrew_venue_name(s)
    s = s[:120]
    if not is_plausible_restaurant_name(s):
        return ""
    return s


def _extract_names(body: str) -> list[str]:
    names: list[str] = []
    skip_spans: list[tuple[int, int]] = []
    for m in _DASH_NAME_THEN_MASADAT.finditer(body):
        lead = normalize_spaces(m.group(1).strip())
        if not lead or _junk_extracted_venue_name(lead):
            continue
        parts = lead.split()
        if not parts:
            continue
        if parts[0] in _DASH_LEAD_FIRST_WORD_BAD:
            continue
        names.append(lead)
        skip_spans.append((m.start(), m.end()))

    def _in_skipped(idx: int) -> bool:
        return any(a <= idx < b for a, b in skip_spans)

    # מסעדת שם / מסעדה שם
    for pat in (
        # לא «מסעדה ומאוד…» / «מסעדת ומוצרי…» (ו מחבר רשימה)
        r"מסעדת\s+(?!ו)([^\n\.,:;!?]{2,55})",
        r"מסעדה\s+(?!ו)([^\n\.,:;!?]{2,50})",
        # אחרי «בית קפה » לא לתפוס המשך רשימה («בית קפה ומאפה»); לא «בבית קפה …»
        r"(?<![ב])בית קפה\s+(?!ו)([^\n\.,:;!?]{2,50})",
    ):
        for m in re.finditer(pat, body):
            if _in_skipped(m.start()):
                continue
            names.append(m.group(1).strip())
    for m in re.finditer(
        r"בבית קפה\s+(?!ו)([^\n\.,:;!?]{2,50})",
        body,
    ):
        if _in_skipped(m.start()):
            continue
        cap = m.group(1).strip()
        if _junk_babayit_kafeh_capture(cap):
            continue
        names.append(cap)
    # קפה שם (not "קפה של"; not "קפה ומאפה" / "קפה ואוכל" — ו מחבר רשימה)
    for m in re.finditer(
        r"קפה\s+(?!ו)((?!של\s|זה\s)[א-ת][^\n\.,:;!?]{1,45})",
        body,
    ):
        if _in_skipped(m.start()):
            continue
        if not _kafeh_is_cafe_word_not_subword_noise(body, m.start()):
            continue
        names.append(m.group(1).strip())
    # במסעדת X (לא «במסעדה וגם…»)
    for m in re.finditer(
        r"במסעד[הת]\s+(?!ו)([א-ת][^\n\.,:;!?]{1,45})",
        body,
    ):
        if _in_skipped(m.start()):
            continue
        names.append(m.group(1).strip())
    # בגומבה / בזינק — תחילית ב+שם לפני עיר / «פתוח» / פיסוק (עם סינון ב+ו… וחיתוך שגוי)
    for m in _BE_IN_CITY.finditer(body):
        if _in_skipped(m.start()):
            continue
        if not _be_prefix_capture_ok(body, m):
            continue
        names.append(m.group("name").strip())
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
        if _junk_extracted_venue_name(n):
            continue
        k = n.casefold().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def pre_scan_filters_ok(nb: str) -> bool:
    """סינון משותף לפני חילוץ שמות (מעבר ראשון) או לפני מועמדות למודל (מעבר שני)."""
    if _scan_exclude(nb):
        return False
    if _scan_body_is_hairdressing_not_food(nb):
        return False
    if _scan_is_recommendation_request(nb):
        return False
    if _scan_where_food_question_without_rec(nb):
        return False
    if _scan_opinion_or_gossip_about_venue(nb):
        return False
    if _scan_venue_plus_bazor_question_without_rec(nb):
        return False
    if _scan_opening_shabbat_question_without_rec(nb):
        return False
    if _scan_message_ends_with_question_not_recommendation(nb):
        return False
    return True


def loose_food_context_for_llm_second_pass(nb: str, *, permissive: bool = False) -> bool:
    """
    רמזי אוכל/מקום להודעות שעברו pre_scan_filters_ok אבל ללא חילוץ קשיח.

    ``permissive=False`` (ברירת מחדל): כמו כניסה לחילוץ שמות — מקום מפורש או המלצה חזקה + עוגן אוכל.

    ``permissive=True``: התנהגות רחבה יותר (עוגן אוכל בלבד, או מילות שבח + מילת מזון) — לשימוש עם ``--llm-loose-permissive``.
    """
    if _scan_explicit_venue(nb):
        return True
    if permissive:
        if _scan_has_food_anchor(nb):
            return True
        soft = (
            "מעולה",
            "טעים",
            "טעימה",
            "נהדר",
            "מדהים",
            "אהבנו",
            "מושלם",
            "שווה",
            "היינו",
            "הייתי",
            "נסענו",
            "ממליץ",
            "ממליצה",
            "ממליצים",
        )
        if any(s in nb for s in soft) and any(f in nb for f in _FOOD):
            return True
        return False
    if _scan_has_strong_recommend(nb) and _scan_has_food_anchor(nb):
        return True
    return False


def extract_restaurants_strict_from_message(
    date: str,
    sender: str,
    body: str,
    *,
    slug_id,
) -> list[dict]:
    """
    חילוץ לפי כללים (מעבר ראשון). רשימה ריקה אם ההודעה לא עומדת בתנאים או בלי שמות שניתן לנקות.
    סינון לפי שנה — ב־iter_whatsapp_messages_since לפני הקריאה לפה.
    """
    if not body or len(body) < 10:
        return []
    if body == "<Media omitted>":
        return []
    nb = _strip_whatsapp_export_meta(normalize_spaces(body))
    if not pre_scan_filters_ok(nb):
        return []
    if not _scan_qualifies_for_chat_extraction(nb):
        return []
    names = _extract_names(nb)
    if not names:
        return []
    loc_body = _guess_location(nb)
    rtype = _guess_type(nb)
    src = f"חילוץ אוטומטי מצ'אט · {sender} · {date}"
    snippet = nb[:550]
    rows: list[dict] = []
    for raw in names:
        name = _clean_name(raw)
        if not name:
            continue
        name, loc_from_name = _split_name_location_suffixes(name)
        loc = (
            loc_from_name
            or _guess_location_for_venue(nb, name)
            or loc_body
        )
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


def extract_restaurants_from_chat_scan(
    text: str,
    *,
    slug_id,
    min_year: int | None = None,
) -> list[dict]:
    """
    Walk all messages; emit one entry per extracted venue name per message (merge later in pipeline).
    ``slug_id`` is the same callable as in extract_restaurants_whatsapp (stable id).
    אם ``min_year`` מוגדר — מדלגים על הודעות עם תאריך לפני אותה שנה (לפי כותרת ההודעה),
    לפני כל חילוץ (iter_whatsapp_messages_since).
    """
    rows: list[dict] = []
    for date, sender, body in iter_whatsapp_messages_since(text, min_year):
        rows.extend(
            extract_restaurants_strict_from_message(date, sender, body, slug_id=slug_id)
        )
    return rows
