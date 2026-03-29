# -*- coding: utf-8 -*-
"""
LLM על (א) הודעות עם חילוץ **קשיח** — אימות ותיקון; (ב) אופציונלי: הודעות **הקשר אוכל**
(``include_loose_food_llm`` + ``loose_food_context_for_llm_second_pass``; מחמיר כברירת מחדל,
או permissive דרך ``llm_loose_permissive``) בלי שמות מהכללים — **רק** אם יש ניסוח עסק אוכל בהודעה.

ב־--llm-second-pass אין לשלב את שורות החילוץ הקשיח ישירות ל־JSON הסופי (רק גיבוי אם קריאת LLM נכשלה בהודעות strict).

שורות «הקשר אוכל» עוברות סינון נוסף אחרי המודל: חייב עדות לשם בטקסט, אין שאלה בלי המלצה חזקה, ורשימת חסימות.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable

from llm_recommendation_gate import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    _call_gemini_generate_content,
    _call_openai_chat_completions,
    _extract_json_object,
)
from restaurant_chat_scan import (
    extract_restaurants_strict_from_message,
    iter_whatsapp_messages_since,
    loose_food_context_for_llm_second_pass,
    normalize_spaces,
    pre_scan_filters_ok,
    _clean_name,
    _guess_location,
    _guess_location_for_venue,
    _guess_type,
    _scan_explicit_venue,
    _scan_has_strong_recommend,
    _scan_is_recommendation_request,
    _strip_whatsapp_export_meta,
)
from restaurant_name_plausible import is_plausible_restaurant_name

_LOOSE_LLM_NOTE_MARKER = "חילוץ LLM (הקשר אוכל)"


# #region agent log
def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, "debug-b43ac1.log")
        payload = {
            "sessionId": "b43ac1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# #endregion

_LLM_GENERIC_VENUE_LABEL_EXACT: frozenset[str] = frozenset(
    {
        "קפה",
        "בית קפה",
        "בית הקפה",
        "מסעדה",
        "מסעדת",
        "המסעדה",
        "פיצריה",
        "מאפייה",
        "חומוסיה",
        "דוכן",
        "בר",
        "אמא",
        "דוכן קפה ומאפה",
    }
)

_LOOSE_GENERIC_CUISINE_SOLO: frozenset[str] = frozenset(
    {
        "איטלקי",
        "איטלקית",
        "אסייתי",
        "אסייתית",
        "תאילנדית",
        "פרסית",
        "הודית",
        "מקסיקנית",
        "ים תיכוני",
        "ים-תיכוני",
        "סושי",
        "פיצה",
        "חומוס",
        "בשרים",
        "דגים",
    }
)


def _loose_name_tokens(name_cf: str) -> list[str]:
    return re.findall(r"[a-z0-9\u0590-\u05f4]+", name_cf)


def _loose_name_has_evidence_in_message(name: str, nb: str) -> bool:
    nc = normalize_spaces(name).casefold()
    bc = normalize_spaces(nb).casefold()
    if nc in bc:
        return True
    toks = _loose_name_tokens(nc)
    sig: list[str] = []
    for t in toks:
        if t and "\u0590" <= t[0] <= "\u05ff":
            if len(t) >= 2:
                sig.append(t)
        elif len(t) >= 3:
            sig.append(t)
    return any(t in bc for t in sig)


def _loose_message_is_family_tribute_not_venue(nb: str) -> bool:
    """טקסטי כבוד לאם / משפחה — לעיתים מכילים «אוכל» אך אינם המלצת מסעדה."""
    b = normalize_spaces(nb)
    if "אמא יקרה" in b and "האמא שלנו" in b:
        return True
    if "אמא יקרה" in b and "רצינו להגיד" in b:
        return True
    return False


def _loose_message_has_restaurant_commerce_cue(nb: str) -> bool:
    if _scan_explicit_venue(nb):
        return True
    b = normalize_spaces(nb)
    return bool(
        re.search(
            r"מסעד[הת]\s|בית\s+קפה\s|בית\s+הקפה|פיצרי|פיצה\s| חומוס|מאפייה|מאפה\s|"
            r"דוכן\s|פלאפל|סושי|המבורגר|סטייק|בר\s*[-–]\s|ברגר|"
            r"קפה\s+[א-ת\"״][^\s\d]{1,22}",
            b,
        )
    )


def _loose_llm_venue_row_passes(name: str, nb: str) -> bool:
    n = normalize_spaces(name).strip()
    if not n:
        return False
    nc = n.casefold()
    b = normalize_spaces(nb)
    bc = b.casefold()

    if n in _LOOSE_GENERIC_CUISINE_SOLO or nc in {x.casefold() for x in _LOOSE_GENERIC_CUISINE_SOLO}:
        return False

    if nc in ("אתר הזה", "אתר זה", "בית הכנסת", "בית כנסת"):
        return False
    if nc.startswith("בית הכנסת") or nc.startswith("בית כנסת "):
        return False

    if re.search(r"\bfm\b", nc) or re.search(r"\b\d+\s*fm\b", nc):
        return False

    if "אנימל" in nc and (
        "לחיות" in bc or "חיות מחמד" in bc or "ציוד לחיות" in bc or "אוכל לחיות" in bc
    ):
        return False

    if nc == "beyond" and (
        "תערוכ" in bc or "חדר בריחה" in bc or "פעילות" in bc
    ) and "מסעד" not in bc and "בית קפה" not in bc:
        return False

    if b.rstrip().endswith("?") and not _scan_has_strong_recommend(b):
        return False

    if not _loose_name_has_evidence_in_message(n, nb):
        return False

    return True


def _llm_output_name_is_non_food_junk(name: str) -> bool:
    n = normalize_spaces(name).strip()
    if not n:
        return True
    nc = n.casefold()

    if nc in _LLM_GENERIC_VENUE_LABEL_EXACT:
        return True

    if re.search(r"בר\s*/\s*מסעדה|מסעדה\s*/\s*בר|מסעדה\s*/\s*בית\s*קפה|בית\s*קפה\s*/\s*מסעד", nc):
        return True

    if re.search(
        r"בית\s*קפה\s*/\s*מסעדה|מסעדה\s*/\s*בית\s*קפה|בית\s*קפה\s*/\s*מסעדת",
        nc,
    ):
        return True

    if nc.startswith("בית משפחת"):
        return True

    if re.search(
        r"^החוג\b|חוג\s+אומנות|החוג\s+אומנות|החיים\s+מתחילים|מגיל\s+60\b|"
        r"סדנ[אה]\b|קורס\s+[א-ת]|תוכנית\s+לגיל|קהילת\s+",
        nc,
    ):
        return True

    if re.search(r"בר\s+מים\b|בר\s+לב\s+קשה|^ברננים\b|ברננים\s*$", nc):
        return True

    if "גיל ווטרמן" in nc:
        return True

    if nc in ("דורין", "הדס"):
        return True

    if nc.startswith("בית צוקרמן") or nc.startswith("בית מיתר"):
        return True

    parts = n.split()
    if len(parts) == 2 and parts[0] == "בית":
        second = parts[1].strip(' "\'"״׳')
        if second and not second.startswith("ה") and second not in (
            "קפה",
            "מסעדה",
            "מסעדת",
        ):
            if 2 <= len(second) <= 22:
                if re.fullmatch(r"[A-Za-zא-ת״\"']+", second):
                    return True

    return False


def _is_east_asian_script_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3040 <= o <= 0x309F
        or 0x30A0 <= o <= 0x30FF
        or 0xAC00 <= o <= 0xD7AF
    )


def _llm_name_has_cjk_not_in_source(name: str, source: str) -> bool:
    if not name or not source:
        return False
    for ch in name:
        if _is_east_asian_script_char(ch) and ch not in source:
            return True
    return False


def build_restaurant_llm_prompt(
    message_text: str,
    *,
    strict_candidate_names: tuple[str, ...] | None = None,
    loose_discovery: bool = False,
) -> str:
    t = (message_text or "").strip()
    if len(t) > 4000:
        t = t[:3997] + "..."
    common_json = """החזר **אובייקט JSON יחיד** בלבד — בלי טקסט לפני או אחרי, בלי Markdown. מבנה:
{"venues":[{"name":"השם **בדיוק** כפי שבטקסט ההודעה (עברית ו/או לטינית כמו במקור)","location":"","restaurant_type":"","extra_info":""}]}

כללים לשדה name: **אל** תתרגם, **אל** תתעתק לאנגלית אם במקור עברית, **אל** תשתמש בסינית/יפנית/קוריאנית **אלא** אם אותן תווים מופיעים **במפורש** בטקסט ההודעה למעלה. אסור למלא «תרגום» של מילים (למשל 咖啡店, レストラン).

אם אין אף מקום כזה — {"venues":[]}.
שדות ריקים אם אין מידע. extra_info — משפט קצר מההודעה (לא להמציא).

טקסט ההודעה:
---
""" + t + "\n---\n"

    loose_discovery_prompt = f"""הודעת WhatsApp (מעבר **גילוי** — אין שמות מועמדים מכללים).

**פלט ברירת מחדל:** החזר בדיוק {{"venues":[]}}.

כלול **רק** אם **במקביל**: (א) בהודעה יש ניסוח של **עסק מזון/שתייה** (מסעדה/מסעדת, בית קפה, פיצריה, חומוסיה, מאפייה, דוכן, או «קפה» + שם מקום); (ב) הכותב מתאר **ביקור, ארוחה, טעימה או המלצה ללכת לאכול** שם — לא שאלה בלי המלצה, לא פרסום שאינו מסעדה, לא טיול/חוג/אירוע פרטי בלבד.

בשדה **name** חייב להופיע **שם ספציפי** כפי שבהודעה (מותג, שם משפחה של בעלים, שם+מקום) — **אסור** להחזיר רק מילות סוג: «קפה», «בית קפה», «מסעדה», «פיצריה», «בר» ללא שם ייחודי מהטקסט.

**אסור:** להמציא שם שלא מופיע בהודעה; לכלול מקום בלי עסק אוכל מפורש; אדם, מוצר, אתר, רדיו, תערוכה, בית פרטי, חנות שאינה אוכל, מעיין, פארק כטיול, רשימת ספרים.

**אל** לכלול **שם מלון** אם לא נכתב במפורש שם **מסעדה או בית קפה** באותו ניסוח **ו**המלצה לאכול שם. **אל** מודעות **דרושים / גיוס / משרה**.

**במקרה של ספק — תמיד** {{"venues":[]}}.

{common_json}"""

    if loose_discovery:
        return loose_discovery_prompt

    if strict_candidate_names is not None:
        lines = "\n".join(f"- {n}" for n in strict_candidate_names if (n or "").strip())
        if not lines.strip():
            lines = "(אין שמות מהכללים — אמת לפי הטקסט בלבד אם יש מסעדה/בית קפה מפורשים.)"
        return f"""הודעה מצ'אט WhatsApp בעברית (המלצות / אוכל / מסעדות).

**חילוץ אוטומטי (כללים)** הציע את שמות המקומות הבאים (ייתכן כפילות, קטיעה או טעות):
{lines}

משימות:
1) **אמת** שכל פריט הוא **עסק מזון/שתייה לציבור** שאפשר ללכת אליו לאכול או לשתות (מסעדה, בית קפה, בר אוכל, דוכן, פיצריה, מאפייה, חומוסיה וכו') — **בהקשר של המלצה או חוויה חיובית על האוכל/השירות שם**. אם אין ביטוי ברור של המלצה/ביקור לאכול — **אל** לכלול.
2) **שמות:** בשדה name השתמש **באותו אלפבית ובאותו איות** כמו בטקסט ההודעה (אפשר לחתוך רווחים כפולים בלבד). אם הרשימה למעלה טעתה — העדף את הניסוח **מההודעה**. השלם location, restaurant_type, extra_info **רק** מההודעה.
3) **אפשר** להוסיף מקומות מההודעה שהכללים פספסו — **רק** אם הם עומדים בהגדרה של סעיף 1.

**אל** לכלול (גם אם מוזכר אוכל): אולמות אירועים; צימרים/וילות נופש; מלון כשלעצמו אלא אם ההמלצה **מפורשת** על ארוחה במסעדה במלון; אטרקציות שאינן מסעדה; מעיין, פארק, חוף בלי עסק מזון מפורש; שמות אנשים; **«בית שם משפחה»** כשזה בית פרטי; **חוג/סדנה**; **«בר»** שאינו בר משקאות במסעדה.

אם מדובר ברשימת **ספרים/הצגות** בלבד — **אל** להוסיף venues משם.

{common_json}"""

    return loose_discovery_prompt


def parse_llm_venues_response(response_text: str) -> list[dict[str, Any]]:
    text = (response_text or "").strip()
    if not text:
        return []
    try:
        data = _extract_json_object(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    venues = data.get("venues")
    if not isinstance(venues, list):
        return []
    out: list[dict[str, Any]] = []
    for v in venues:
        if not isinstance(v, dict):
            continue
        name = (v.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "location": (v.get("location") or "").strip(),
                "restaurant_type": (v.get("restaurant_type") or "").strip(),
                "extra_info": (v.get("extra_info") or "").strip(),
            }
        )
    return out


def _ollama_generate(
    prompt: str,
    *,
    ollama_url: str,
    model: str,
    timeout_sec: int,
) -> tuple[str, str | None]:
    base = ollama_url.rstrip("/")
    url = f"{base}/api/generate"
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 700},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return "", str(e.reason)
    except TimeoutError:
        return "", "timeout"
    try:
        outer = json.loads(raw_bytes.decode("utf-8"))
        return (outer.get("response") or "").strip(), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "", "bad Ollama response encoding"


def _venues_to_rows(
    venues: list[dict[str, Any]],
    *,
    date: str,
    sender: str,
    nb: str,
    slug_id: Callable[[str], str],
    note_label: str,
) -> list[dict]:
    if _LOOSE_LLM_NOTE_MARKER in note_label:
        if _scan_is_recommendation_request(nb):
            return []
        if _loose_message_is_family_tribute_not_venue(nb):
            return []
        if not _loose_message_has_restaurant_commerce_cue(nb):
            return []
    snippet = nb[:550]
    type_h = _guess_type(nb)
    loc_body = _guess_location(nb)
    src = f"{note_label} · {sender} · {date}"
    out: list[dict] = []
    for v in venues:
        raw_name = (v.get("name") or "").strip()
        cleaned = _clean_name(raw_name)
        name = cleaned or raw_name
        name = unicodedata.normalize("NFKC", normalize_spaces(name))
        if len(name) < 2 or len(name) > 120:
            continue
        if _llm_name_has_cjk_not_in_source(name, nb):
            continue
        if not is_plausible_restaurant_name(name):
            continue
        if _llm_output_name_is_non_food_junk(name):
            continue
        if _LOOSE_LLM_NOTE_MARKER in note_label and not _loose_llm_venue_row_passes(name, nb):
            continue
        loc = (v.get("location") or "").strip() or (
            _guess_location_for_venue(nb, name) or loc_body
        )
        rtype = (v.get("restaurant_type") or "").strip() or type_h
        extra = (v.get("extra_info") or "").strip() or snippet[:600]
        out.append(
            {
                "id": slug_id("llm2:" + name + date + sender[:20]),
                "name": name[:120],
                "restaurant_type": rtype[:150],
                "location": loc[:250],
                "note": src[:400],
                "extra_info": extra[:600],
            }
        )
    return out


def extract_venues_llm_single_message(
    message_text: str,
    *,
    backend: str,
    ollama_url: str,
    model: str,
    openai_base_url: str,
    openai_api_key: str,
    gemini_api_key: str,
    timeout_sec: int = 120,
    strict_candidate_names: tuple[str, ...] | None = None,
    loose_discovery: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (parsed venue dicts from model, error or None)."""
    prompt = build_restaurant_llm_prompt(
        message_text,
        strict_candidate_names=strict_candidate_names,
        loose_discovery=loose_discovery,
    )
    err: str | None = None
    raw = ""
    if backend == "openai":
        raw, err = _call_openai_chat_completions(
            base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
            api_key=openai_api_key,
            model=model,
            prompt=prompt,
            timeout_sec=timeout_sec,
            max_tokens=700,
        )
    elif backend == "gemini":
        raw, err = _call_gemini_generate_content(
            api_key=gemini_api_key,
            model=model,
            prompt=prompt,
            timeout_sec=timeout_sec,
            max_output_tokens=700,
        )
    else:
        raw, err = _ollama_generate(
            prompt, ollama_url=ollama_url, model=model, timeout_sec=timeout_sec
        )
    if err:
        return [], err
    return parse_llm_venues_response(raw), None


def collect_llm_second_pass_rows(
    text: str,
    *,
    slug_id: Callable[[str], str],
    min_year: int | None,
    backend: str,
    ollama_url: str,
    model: str,
    openai_base_url: str,
    openai_api_key: str,
    gemini_api_key: str,
    timeout_sec: int,
    llm_limit: int | None,
    llm_sleep_sec: float,
    llm_loose_permissive: bool = False,
    include_loose_food_llm: bool = False,
    log: Callable[[str], None] | None = None,
) -> tuple[list[dict], int, int, int, int]:
    """
    שולח למודל: הודעות עם חילוץ קשיח; אופציונלית גם הודעות «הקשר אוכל» בלי שמות מהכללים
    (רק אם ``include_loose_food_llm=True``).
    """
    log = log or (lambda _m: None)
    rows: list[dict] = []
    calls = 0
    strict_verify_messages = 0
    strict_rule_rows = 0
    loose_food_llm_messages = 0

    jobs: list[dict[str, Any]] = []
    for date, sender, body in iter_whatsapp_messages_since(text, min_year):
        if not body or len(body) < 10 or body == "<Media omitted>":
            continue
        nb = _strip_whatsapp_export_meta(normalize_spaces(body))

        strict = extract_restaurants_strict_from_message(
            date, sender, body, slug_id=slug_id
        )

        if strict:
            strict_verify_messages += 1
            strict_rule_rows += len(strict)
            seen: set[str] = set()
            ordered: list[str] = []
            for r in strict:
                n = (r.get("name") or "").strip()
                if not n:
                    continue
                k = n.casefold()
                if k not in seen:
                    seen.add(k)
                    ordered.append(n)
            names_hint = tuple(ordered)
            jobs.append(
                {
                    "date": date,
                    "sender": sender,
                    "nb": nb,
                    "names_hint": names_hint,
                    "loose_discovery": False,
                    "fallback_strict": strict,
                    "note_label": "חילוץ LLM (אימות כללים)",
                }
            )
        elif (
            include_loose_food_llm
            and pre_scan_filters_ok(nb)
            and not _loose_message_is_family_tribute_not_venue(nb)
            and loose_food_context_for_llm_second_pass(nb, permissive=llm_loose_permissive)
            and _loose_message_has_restaurant_commerce_cue(nb)
        ):
            loose_food_llm_messages += 1
            jobs.append(
                {
                    "date": date,
                    "sender": sender,
                    "nb": nb,
                    "names_hint": None,
                    "loose_discovery": True,
                    "fallback_strict": [],
                    "note_label": "חילוץ LLM (הקשר אוכל)",
                }
            )

    _agent_debug_log(
        "H1",
        "restaurant_llm_second_pass.py:collect_llm_second_pass_rows",
        "llm_job_prep_summary",
        {
            "include_loose_food_llm": include_loose_food_llm,
            "loose_permissive": llm_loose_permissive,
            "strict_messages": strict_verify_messages,
            "loose_messages_queued": loose_food_llm_messages,
            "total_jobs": len(jobs),
        },
    )

    log(
        f"LLM prep: {loose_food_llm_messages} loose food-context message(s) "
        f"(no strict names); {strict_verify_messages} message(s) with strict extraction."
    )

    for job in jobs:
        if llm_limit is not None and calls >= llm_limit:
            continue

        date = job["date"]
        sender = job["sender"]
        nb = job["nb"]
        names_hint = job["names_hint"]
        loose_discovery = bool(job.get("loose_discovery"))
        fallback_strict = job["fallback_strict"]
        note_label = job["note_label"]

        venues, err = extract_venues_llm_single_message(
            nb,
            backend=backend,
            ollama_url=ollama_url,
            model=model,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key,
            timeout_sec=timeout_sec,
            strict_candidate_names=names_hint,
            loose_discovery=loose_discovery,
        )
        calls += 1
        if calls % 5 == 0:
            log(f"LLM progress: {calls} request(s) sent.")
        if err:
            log(f"  LLM error ({date}): {err}")
            rows.extend(fallback_strict)
            if llm_sleep_sec > 0:
                time.sleep(llm_sleep_sec)
            continue
        rows.extend(
            _venues_to_rows(
                venues,
                date=date,
                sender=sender,
                nb=nb,
                slug_id=slug_id,
                note_label=note_label,
            )
        )
        if llm_sleep_sec > 0:
            time.sleep(llm_sleep_sec)
    return rows, calls, strict_verify_messages, strict_rule_rows, loose_food_llm_messages
