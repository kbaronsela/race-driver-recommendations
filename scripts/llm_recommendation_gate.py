# -*- coding: utf-8 -*-
"""
שער LLM (Ollama): האם שיתוף VCF בצ'אט הוא המלצה על בעל מקצוע/עסק, ומה תחום העיסוק.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"


def _format_chat_block(messages: list[tuple[str, str, str]], max_msg_len: int = 600) -> str:
    lines = []
    for dt, sender, text in messages:
        text = (text or "").replace("\n", " ").strip()
        if len(text) > max_msg_len:
            text = text[: max_msg_len - 3] + "..."
        lines.append(f"- [{dt}] {sender}: {text}")
    return "\n".join(lines) if lines else "(אין)"


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.lower().startswith("json"):
                p = p[4:].lstrip()
            if p.startswith("{"):
                text = p
                break
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end])


def _parse_model_json_response(response_text: str) -> tuple[dict | None, str | None]:
    """
    מנסה JSON תקין; אם נכשל — מחלץ לפחות include (ובהצלחה גם field/reason) ב-regex.
    מחזיר (data, error_message). error_message הוא None אם הצליח.
    """
    text = (response_text or "").strip()
    if not text:
        return None, "empty model response"

    try:
        return _extract_json_object(text), None
    except (json.JSONDecodeError, ValueError) as e:
        strict_err = str(e)

    blob = text
    if "{" in text and "}" in text:
        blob = text[text.find("{") : text.rfind("}") + 1]

    inc_m = re.search(r'"include"\s*:\s*(true|false)', blob, re.I)
    if not inc_m:
        return None, f"JSON parse: {strict_err}"

    include = inc_m.group(1).lower() == "true"
    field = ""
    fm = re.search(r'"field"\s*:\s*"((?:[^"\\]|\\.)*)"', blob, re.DOTALL)
    if fm:
        field = fm.group(1).replace('\\"', '"').replace("\\\\", "\\")
    reason = ""
    rm = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', blob, re.DOTALL)
    if rm:
        reason = rm.group(1).replace('\\"', '"').replace("\\\\", "\\")

    return {"include": include, "field": field, "reason": reason}, None


def classify_vcf_share(
    *,
    ollama_url: str,
    model: str,
    name: str,
    phone: str,
    vcf_filename: str,
    org: str,
    note_vcf: str,
    title_vcf: str,
    sender: str,
    attach_message: str,
    context_before: list[tuple[str, str, str]],
    context_after: list[tuple[str, str, str]],
    timeout_sec: int = 180,
) -> dict:
    """
    קורא ל-Ollama. מחזיר dict:
      include (bool), field (str), reason (str), error (str|None), raw_response (str)
    """
    org = (org or "").strip()
    note_vcf = (note_vcf or "").strip()
    title_vcf = (title_vcf or "").strip()
    base = ollama_url.rstrip("/")
    url = f"{base}/api/generate"

    prompt = f"""אתה מסווג יצוא צ'אט וואטסאפ בעברית. הועלה כרטיס איש קשר (VCF) לקבוצה.

## פרטים מכרטיס ה-VCF
- שם: {name}
- טלפון: {phone}
- שם קובץ: {vcf_filename}
- ארגון/עסק (אם מופיע בכרטיס): {org or "(ריק)"}
- תפקיד/כותרת (אם מופיע): {title_vcf or "(ריק)"}
- הערה בתוך ה-VCF (אם יש): {note_vcf or "(אין)"}

## ההודעה שבה שותף הקובץ
- שולח: {sender}
- תוכן ההודעה: {attach_message.replace(chr(10), " ")[:800]}

## הודעות בצ'אט לפני השיתוף (מהישן לחדש)
{_format_chat_block(context_before)}

## הודעות בצ'אט אחרי השיתוף (המידע הראשון אחרי)
{_format_chat_block(context_after)}

---

החלט:
1) האם מדובר בהמלצה על **בעל מקצוע / עסק / נותן שירות** (מישהו שממליצים עליו כדי לקבל שירות מקצועי), לעומת איש קשר אישי/משפחה/חבר בלי הקשר מקצועי, או שיתוף בלי המלצה?
2) אם כן — מה **תחום העיסוק** בעברית, כקטגוריה קצרה (למשל: חשמל, אינסטלציה, רפואת שיניים, מורים פרטיים).

השב **רק** ב-JSON תקין (בלי טקסט לפני או אחרי). המפתחות: include (בוליאני true/false), field (מחרוזת), reason (מחרוזת בעברית).
דוגמה ל-exclude: {{"include": false, "field": "", "reason": "אין הקשר מקצועי"}}
דוגמה ל-include: {{"include": true, "field": "חשמל", "reason": "מחפשים חשמלאי מומלץ"}}

חשוב לתחביר JSON: אל תכתוב מרכאות כפולות ASCII (") **בתוך** הטקסט בשדות field ו-reason. אם צריך ציטוט — בלי מרכאות או עם גרש ' בלבד.

כללים:
- "include": true רק אם מההקשר (כולל שם הקובץ, תוכן ההודעות והכרטיס) **סביר** שזו המלצה מקצועית או שיתוף של איש שירות/עסק.
- "include": false אם זה נראה אישי בלבד, אין שום רמז להמלצה מקצועית, או אין מספיק מידע.
- "field": מלא רק כש-include הוא true; אחרת מחרוזת ריקה.
"""

    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 400},
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
        return {
            "include": False,
            "field": "",
            "reason": "",
            "error": f"HTTP {e.code}: {e.reason}",
            "raw_response": "",
        }
    except urllib.error.URLError as e:
        return {
            "include": False,
            "field": "",
            "reason": "",
            "error": str(e.reason),
            "raw_response": "",
        }
    except TimeoutError:
        return {
            "include": False,
            "field": "",
            "reason": "",
            "error": "timeout",
            "raw_response": "",
        }

    try:
        outer = json.loads(raw_bytes.decode("utf-8"))
        response_text = outer.get("response", "")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "include": False,
            "field": "",
            "reason": "",
            "error": "bad Ollama response encoding",
            "raw_response": "",
        }

    data, parse_err = _parse_model_json_response(response_text)
    if data is None:
        return {
            "include": False,
            "field": "",
            "reason": "",
            "error": parse_err or "parse failed",
            "raw_response": response_text[:2000],
        }

    include = bool(data.get("include"))
    field = (data.get("field") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not include:
        field = ""
    return {
        "include": include,
        "field": field,
        "reason": reason,
        "error": None,
        "raw_response": response_text[:2000],
    }
