# -*- coding: utf-8 -*-
"""
LLM על (א) הודעות עם חילוץ **קשיח** — אימות ותיקון; (ב) הודעות עם **הקשר אוכל רחב**
(``loose_food_context_for_llm_second_pass``) בלי שמות מהכללים — חילוץ במודל בלבד.

ב־--llm-second-pass אין לשלב את שורות החילוץ הקשיח ישירות ל־JSON הסופי (רק גיבוי אם קריאת LLM נכשלה בהודעות strict).
"""
from __future__ import annotations

import json
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
    _strip_whatsapp_export_meta,
)
from restaurant_name_plausible import is_plausible_restaurant_name


def _is_east_asian_script_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF  # CJK Unified
        or 0x3040 <= o <= 0x309F  # Hiragana
        or 0x30A0 <= o <= 0x30FF  # Katakana
        or 0xAC00 <= o <= 0xD7AF  # Hangul syllables
    )


def _llm_name_has_cjk_not_in_source(name: str, source: str) -> bool:
    """דוחה שמות שהמודל ״תרגם״ לסינית/יפנית/קוריאנית שלא מופיעות במקור."""
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

    if strict_candidate_names:
        lines = "\n".join(f"- {n}" for n in strict_candidate_names if (n or "").strip())
        return f"""הודעה מצ'אט WhatsApp בעברית (המלצות / אוכל / מסעדות).

**חילוץ אוטומטי (כללים)** הציע את שמות המקומות הבאים (ייתכן כפילות, קטיעה או טעות):
{lines}

משימות:
1) **אמת** שכל פריט הוא עסק **אוכל או שתייה במקום** (מסעדה, בית קפה, בר אוכל, דוכן, פיצריה וכו') — שנזכר כהמלצה, חוויה חיובית, או שם מקום רלוונטי. אם שם אינו מסעדה/מקום אוכל — **אל** לכלול אותו.
2) **שמות:** בשדה name השתמש **באותו אלפבית ובאותו איות** כמו בטקסט ההודעה (אפשר לחתוך רווחים כפולים בלבד). אם הרשימה למעלה טעתה — העדף את הניסוח **מההודעה**. השלם location, restaurant_type, extra_info **רק** מההודעה.
3) **אפשר** להוסיף מקומות מההודעה שהכללים פספסו.

{common_json}"""

    return f"""הודעה מצ'אט WhatsApp בעברית (המלצות / אוכל / מסעדות). משימה אחת בלבד.

חלץ **רק** מקומות לאכול/לשתות (מסעדה, בית קפה, בר אוכל, דוכן, פיצריה וכו') שהכותב **ממליץ עליהם**, מתאר אותם בחום, או מציין שם מקום כהמלצה. אל תמציא שמות — רק מה שמופיע או מרומז בבירור בטקסט.

אל תכלול: בקשות להמלצות, שאלות בלי תשובה, דיונים פוליטיים, מוצרי מטבח לבית, או אנשי קשר שאינם עסקי מזון.

{common_json}"""


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
) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (parsed venue dicts from model, error or None)."""
    prompt = build_restaurant_llm_prompt(
        message_text, strict_candidate_names=strict_candidate_names
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
    log: Callable[[str], None] | None = None,
) -> tuple[list[dict], int, int, int, int]:
    """
    שולח למודל: הודעות עם חילוץ קשיח, וגם הודעות עם הקשר אוכל רחב בלי שמות מהכללים.

    מחזיר (שורות, קריאות API, הודעות strict שנשלחו/מועמדות, סה\"כ שורות strict לפני LLM,
    הודעות loose-only מועמדות ל-LLM).
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
            names_hint = tuple(ordered) if ordered else None
            jobs.append(
                {
                    "date": date,
                    "sender": sender,
                    "nb": nb,
                    "names_hint": names_hint,
                    "fallback_strict": strict,
                    "note_label": "חילוץ LLM (אימות כללים)",
                }
            )
        elif pre_scan_filters_ok(nb) and loose_food_context_for_llm_second_pass(nb):
            loose_food_llm_messages += 1
            jobs.append(
                {
                    "date": date,
                    "sender": sender,
                    "nb": nb,
                    "names_hint": None,
                    "fallback_strict": [],
                    "note_label": "חילוץ LLM (הקשר אוכל)",
                }
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
