# -*- coding: utf-8 -*-
"""
שער LLM: האם שיתוף VCF בצ'אט הוא **המלצה** (או מענה לבקשת המלצה) על בעל מקצוע/עסק, ומה תחום העיסוק.

Backends:
  - ollama: POST /api/generate (מקומי)
  - openai: POST .../v1/chat/completions (OpenAI-compatible: Groq, Together, OpenRouter, וכו')
  - gemini: Google Generative Language API (מפתח חינמי מ-Google AI Studio)
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"

# Groq free tier — OpenAI-compatible base URL (needs GROQ_API_KEY)
DEFAULT_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_OPENAI_MODEL = "llama-3.1-8b-instant"

# Google AI Studio — https://aistudio.google.com/apikey
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

# Cloudflare/WAF often block urllib's default User-Agent (Python-urllib/…).
_CLIENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _format_chat_block(messages: list[tuple[str, str, str]], max_msg_len: int = 400) -> str:
    lines = []
    for dt, sender, text in messages:
        text = (text or "").replace("\n", " ").strip()
        if len(text) > max_msg_len:
            text = text[: max_msg_len - 3] + "..."
        lines.append(f"- [{dt}] {sender}: {text}")
    return "\n".join(lines) if lines else "(אין)"


def build_classification_prompt(
    *,
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
    hybrid: bool = False,
) -> str:
    org = (org or "").strip()
    note_vcf = (note_vcf or "").strip()
    title_vcf = (title_vcf or "").strip()
    base = f"""אתה מסווג יצוא צ'אט וואטסאפ בעברית. הועלה כרטיס איש קשר (VCF) לקבוצה.

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

"""
    if hybrid:
        return base + """מצב hybrid: החלט **רק** האם שיתוף ה-VCF הוא **המלצה** (או מענה ישיר לבקשה להמלצה) על בעל מקצוע / עסק / נותן שירות. לא לקבוע תחום עיסוק.

## מה נחשב include=true (רק אחד מאלה)
- בהודעת השיתוף או בהודעות **סמוכות** בצ'אט מופיע **ניסוח של המלצה** על אותו איש מקצוע/עסק (למשל: "ממליצה", "מומלץ בחום", "פניתי אליו מצוין", "הנה אצל מי עשיתי", "שולחת את המספר של…" בהקשר של שירות).
- או: בשרשור יש **בקשה מפורשת** להמלצה על סוג שירות (מחפשים, מכירים, מישהו ש…, המלצה ל…) **והשיתוף** נראה כ**מענה** לבקשה הזו (כרטיס שנשלח מיד אחרי/לפני הבקשה או כהמשך טבעי לדיון על אותו סוג שירות).

## include=false (ברירת המחדל כשלא מתקיים לעיל)
- שיתוף כרטיס **בלי** אינדיקציה שהוא חלק מהמלצה או ממענה לבקשת שירות (למשל רק "קובץ מצורף", העברה שגרתית, או דיון שלא נוגע לשירות מקצועי).
- איש קשר אישי / שכונה / חברות (למשל "…-שכנה") כשאין ניסוח המלצה או בקשה רלוונטית בשרשור.
- **אם לא ברור** שהשיתוף נועד כהמלצה או כמענה לבקשה — **include=false**.

חובה: החזר **אובייקט JSON יחיד בלבד** — בלי טקסט לפני או אחרי, בלי Markdown. המפתחות באנגלית:
- "include": true או false
- "reason": מחרוזת קצרה **בעברית**

אסור להוסיף מפתח "field".

דוגמאות תקינות:
{"include":false,"reason":"שיתוף קובץ בלי ניסוח המלצה או בקשה לשירות בשרשור"}
{"include":false,"reason":"איש קשר שכונתי בלי המלצה"}
{"include":true,"reason":"ממליצה במפורש על בעל המקצוע"}
{"include":true,"reason":"מענה לבקשה אינסטלטור בשרשור הסמוך"}
"""
    return base + """החלט:
1) האם שיתוף ה-VCF הוא **המלצה** או **מענה ישיר** לבקשה להמלצה על בעל מקצוע / עסק / נותן שירות?
2) רק אם כן — מה תחום העיסוק בעברית (קטגוריה קצרה).

כלל: **include=true** רק כשיש בסיס בטקסט (הודעת השיתוף או הודעות סמוכות) לניסוח המלצה או לבקשה+מענה כמתואר במצב hybrid. אחרת include=false.

חובה: החזר **אובייקט JSON יחיד בלבד** — בלי טקסט לפני או אחרי. המפתחות באנגלית: "include", "field", "reason" (הסיבה בעברית).

דוגמאות:
{"include":false,"field":"","reason":"אין המלצה או מענה לבקשת שירות בשרשור"}
{"include":true,"field":"חשמל","reason":"ממליצה על החשמלאי והכרטיס שלו"}

כללים:
- "field" רק כש-include הוא true; אחרת "".
- בלי מרכאות כפולות בתוך הערכים בעברית; אם צריך — גרש יחיד.
"""


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


def _loose_parse_classification(text: str) -> dict | None:
    """
    When the model does not return clean JSON, try to recover include (+ optional reason/field).
    Handles missing braces, 'include: true', single-quoted keys, etc.
    """
    t = (text or "").strip()
    if not t:
        return None
    # Innermost JSON-like slice
    if "{" in t and "}" in t:
        sub = t[t.find("{") : t.rfind("}") + 1]
        for attempt in (sub, t):
            try:
                d = json.loads(attempt)
                if isinstance(d, dict) and "include" in d:
                    return d
            except json.JSONDecodeError:
                continue
    # Unquoted JSON values: {"include":true
    inc_m = re.search(r'["\']?include["\']?\s*:\s*(true|false)\b', t, re.I)
    if not inc_m:
        inc_m = re.search(r"\binclude\b\s*[:=]\s*(true|false)\b", t, re.I)
    if not inc_m:
        return None
    include = inc_m.group(1).lower() == "true"
    field = ""
    fm = re.search(r'["\']?field["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', t, re.DOTALL)
    if fm:
        field = fm.group(1).replace('\\"', '"').replace("\\\\", "\\")
    reason = ""
    rm = re.search(r'["\']?reason["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', t, re.DOTALL)
    if rm:
        reason = rm.group(1).replace('\\"', '"').replace("\\\\", "\\")
    return {"include": include, "field": field, "reason": reason}


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
        loose = _loose_parse_classification(text)
        if loose is not None:
            return loose, None
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


def _normalize_openai_base(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return b
    if not b.endswith("/v1"):
        b = b + "/v1"
    return b


def _http_error_detail(e: urllib.error.HTTPError, body: str | None = None) -> str:
    if body is None:
        try:
            body = e.read().decode("utf-8", errors="replace")[:900]
        except Exception:
            body = ""
    msg = f"HTTP {e.code}: {e.reason}"
    if body.strip():
        msg += f" {body.strip()}"
    if e.code == 403 and ("1010" in body or "Cloudflare" in body or "cf-ray" in body.lower()):
        msg += (
            " — Often: IP blocked (VPN/datacenter) or WAF. Try another network/VPN off, "
            "or use --llm-backend gemini with GEMINI_API_KEY from https://aistudio.google.com/apikey"
        )
    return msg


def _parse_rate_limit_wait_seconds(body: str, headers) -> float:
    """Groq/OpenAI/Gemini: Retry-After header, 'try again in Xs', or google.rpc RetryInfo."""
    if headers is not None and hasattr(headers, "get"):
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if ra:
            try:
                return min(float(ra), 120.0)
            except ValueError:
                pass
    # Google RPC: "retryDelay": "42s"
    m = re.search(r'"retryDelay"\s*:\s*"(\d+)s"', body)
    if m:
        return min(float(m.group(1)) + 1.0, 120.0)
    m = re.search(r"try again in ([\d.]+)\s*s", body, re.I)
    if m:
        return min(float(m.group(1)) + 0.75, 120.0)
    return 10.0


def _gemini_error_is_daily_quota_exhausted(body: str) -> bool:
    """True only when the error indicates daily (or fixed) quota is exhausted — retrying immediately won't help."""
    b = body.lower()
    if "per_day" in b or "requests_per_day" in b or "generate_requests_per_day" in b:
        return True
    if "generate_content_requests_per_day" in b:
        return True
    return False


def _call_openai_chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout_sec: int,
    max_retries: int = 15,
    max_tokens: int = 350,
) -> tuple[str, str | None]:
    """
    Returns (response_text, error_message). On HTTP 429, sleep (from API message) and retry.
    """
    base = _normalize_openai_base(base_url)
    url = f"{base}/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
            **_CLIENT_HEADERS,
        },
        method="POST",
    )
    raw_bytes: bytes | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = resp.read()
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < max_retries:
                wait = _parse_rate_limit_wait_seconds(err_body, e.headers)
                print(
                    f"  ... rate limited (429), sleeping {wait:.1f}s then retry (attempt {attempt}/{max_retries})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if e.code == 503 and attempt < max_retries:
                print(
                    f"  ... server busy (503), sleeping 5s then retry (attempt {attempt}/{max_retries})",
                    flush=True,
                )
                time.sleep(5.0)
                continue
            return "", _http_error_detail(e, err_body)
        except urllib.error.URLError as e:
            return "", str(e.reason)
        except TimeoutError:
            return "", "timeout"

    if raw_bytes is None:
        return "", "empty response"

    try:
        outer = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "", "bad API response encoding"

    if isinstance(outer, dict) and outer.get("error"):
        err = outer["error"]
        if isinstance(err, dict):
            return "", err.get("message", str(err))
        return "", str(err)

    try:
        content = outer["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return "", "unexpected API response shape"
    return (content or "").strip(), None


def _call_gemini_generate_content(
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_sec: int,
    max_retries: int = 15,
    max_output_tokens: int = 400,
) -> tuple[str, str | None]:
    """Gemini generateContent REST. Retries on 429/503 like OpenAI-compatible path."""
    safe = (model or "").strip()
    if not safe:
        return "", "empty gemini model name"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{safe}:generateContent?key={api_key}"
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_output_tokens,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8", **_CLIENT_HEADERS},
        method="POST",
    )
    raw_bytes: bytes | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw_bytes = resp.read()
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < max_retries:
                if _gemini_error_is_daily_quota_exhausted(err_body):
                    return (
                        "",
                        _http_error_detail(e, err_body)
                        + " — Daily request quota looks exhausted; wait until reset or check "
                        "https://aistudio.google.com/ and Cloud billing/quotas.",
                    )
                wait = _parse_rate_limit_wait_seconds(err_body, e.headers)
                print(
                    f"  ... Gemini rate limited (429), sleeping {wait:.1f}s then retry (attempt {attempt}/{max_retries})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if e.code == 503 and attempt < max_retries:
                print(
                    f"  ... Gemini busy (503), sleeping 8s then retry (attempt {attempt}/{max_retries})",
                    flush=True,
                )
                time.sleep(8.0)
                continue
            return "", _http_error_detail(e, err_body)
        except urllib.error.URLError as e:
            return "", str(e.reason)
        except TimeoutError:
            return "", "timeout"

    if raw_bytes is None:
        return "", "empty response"

    try:
        outer = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "", "bad Gemini response encoding"

    if isinstance(outer, dict) and outer.get("error"):
        err = outer["error"]
        if isinstance(err, dict):
            return "", err.get("message", str(err))
        return "", str(err)

    if not outer.get("candidates"):
        fb = outer.get("promptFeedback") or outer.get("error")
        return "", f"Gemini no candidates: {fb}"

    try:
        parts = outer["candidates"][0]["content"]["parts"]
        text = "".join((p.get("text") or "") for p in parts)
    except (KeyError, IndexError, TypeError):
        return "", "unexpected Gemini response shape"
    return (text or "").strip(), None


def classify_vcf_share(
    *,
    backend: str = "ollama",
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
    openai_base_url: str = "",
    openai_api_key: str = "",
    gemini_api_key: str = "",
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
    hybrid: bool = True,
) -> dict:
    """
    מחזיר dict:
      include (bool), field (str), reason (str), error (str|None), raw_response (str)

    backend: "ollama" | "openai" | "gemini"
    hybrid: True = prompt asks include/reason only; caller should set field via keyword rules.
    """
    prompt = build_classification_prompt(
        name=name,
        phone=phone,
        vcf_filename=vcf_filename,
        org=org,
        note_vcf=note_vcf,
        title_vcf=title_vcf,
        sender=sender,
        attach_message=attach_message,
        context_before=context_before,
        context_after=context_after,
        hybrid=hybrid,
    )

    if backend == "openai":
        response_text, err = _call_openai_chat_completions(
            base_url=openai_base_url or DEFAULT_OPENAI_BASE_URL,
            api_key=openai_api_key or "",
            model=model,
            prompt=prompt,
            timeout_sec=timeout_sec,
        )
        if err:
            return {
                "include": False,
                "field": "",
                "reason": "",
                "error": err,
                "raw_response": "",
            }
    elif backend == "gemini":
        response_text, err = _call_gemini_generate_content(
            api_key=gemini_api_key or "",
            model=model,
            prompt=prompt,
            timeout_sec=timeout_sec,
        )
        if err:
            return {
                "include": False,
                "field": "",
                "reason": "",
                "error": err,
                "raw_response": "",
            }
    else:
        base = ollama_url.rstrip("/")
        url = f"{base}/api/generate"
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
            "raw_response": (response_text or "")[:2000],
        }

    include = bool(data.get("include"))
    field = (data.get("field") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not include:
        field = ""
    if hybrid:
        field = ""
    return {
        "include": include,
        "field": field,
        "reason": reason,
        "error": None,
        "raw_response": (response_text or "")[:2000],
    }
