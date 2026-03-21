#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal server: auth (single user), serve entries (base + user_data), add/edit.
"""
import json
import hashlib
import os
import re
import secrets
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config.json"
USER_DATA_PATH = DATA_DIR / "user_data.json"
ENTRIES_PATH = DATA_DIR / "entries.json"
RESTAURANTS_PATH = DATA_DIR / "restaurants.json"

app = Flask(__name__, static_folder=APP_DIR, static_url_path="")


def load_config():
    # Allow auth from environment (e.g. on Render or PythonAnywhere)
    env_user = (
        os.environ.get("PYTHONANYWHERE_USER", "").strip()
        or os.environ.get("RENDER_USER", "").strip()
    )
    env_pass = (
        os.environ.get("PYTHONANYWHERE_PASSWORD", "").strip()
        or os.environ.get("RENDER_PASSWORD", "").strip()
    )
    if env_user and env_pass:
        h = hashlib.sha256(f"{env_user}:{env_pass}".encode()).hexdigest()
        return {"user": env_user, "password_hash": h}
    if not CONFIG_PATH.exists():
        return {"user": "", "password_hash": ""}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_user_data():
    if not USER_DATA_PATH.exists():
        return {"from_moshav": {}, "edits": {}, "added": [], "deleted": [], "notes": {}}
    with open(USER_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("deleted", [])
    data.setdefault("notes", {})
    return data


def save_user_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def norm_phone(p):
    if not p:
        return ""
    return "".join(c for c in str(p) if c.isdigit())[-10:] or str(p)


def merge_entries():
    base = []
    if ENTRIES_PATH.exists():
        with open(ENTRIES_PATH, "r", encoding="utf-8") as f:
            base = json.load(f)
    ud = load_user_data()
    from_moshav = ud.get("from_moshav", {})
    edits = ud.get("edits", {})
    notes = ud.get("notes", {})
    added = ud.get("added", [])
    deleted = set(ud.get("deleted", []))

    result = []
    seen_phone = set()
    for e in base:
        phone = norm_phone(e.get("phone"))
        key = phone or e.get("phone", "")
        if key in deleted or key in seen_phone:
            continue
        seen_phone.add(key)
        row = dict(e)
        row["from_moshav"] = from_moshav[key] if (key and key in from_moshav) else row.get("from_moshav", False)
        if key and key in edits:
            edk = edits[key]
            row.update(edk)
            if "phones" in edk:
                ph = edk.get("phones")
                if ph is None or (isinstance(ph, list) and len(ph) <= 1):
                    row.pop("phones", None)
                elif isinstance(ph, list):
                    row["phones"] = ph
        overlay_note = notes.get(key, "") or (edits.get(key) or {}).get("note", "")
        row["note"] = overlay_note if overlay_note else (row.get("note") or "")
        row["_key"] = norm_phone(row.get("phone")) or key
        result.append(row)
    for e in added:
        phone = norm_phone(e.get("phone"))
        key = phone or ""
        if key in deleted or key in seen_phone:
            continue
        seen_phone.add(key)
        row = dict(e)
        row.setdefault("phone_display", row.get("phone", ""))
        row["from_moshav"] = from_moshav.get(key, row.get("from_moshav", False))
        if key in edits:
            edk = edits[key]
            row.update(edk)
            if "phones" in edk:
                ph = edk.get("phones")
                if ph is None or (isinstance(ph, list) and len(ph) <= 1):
                    row.pop("phones", None)
                elif isinstance(ph, list):
                    row["phones"] = ph
        overlay_note = notes.get(key, "") or (edits.get(key) or {}).get("note", "")
        row["note"] = overlay_note if overlay_note else (row.get("note") or "")
        row["_key"] = norm_phone(row.get("phone")) or key
        row["_added"] = True
        result.append(row)
    return result


def _entry_to_stored(row):
    """Strip internal keys for writing to entries.json."""
    out = {
        "name": row.get("name", ""),
        "phone": row.get("phone_display", row.get("phone", "")),
        "field": row.get("field", ""),
        "from_moshav": bool(row.get("from_moshav")),
        "note": (row.get("note") or "").strip(),
        "extra_info": (row.get("extra_info") or "").strip(),
    }
    phones = row.get("phones")
    if isinstance(phones, list) and len(phones) > 1:
        out["phones"] = phones
    return out


def flush_entries_to_disk():
    """Write current merged state to entries.json and clear user_data overlay."""
    merged = merge_entries()
    stored = [_entry_to_stored(row) for row in merged]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ENTRIES_PATH, "w", encoding="utf-8") as f:
        json.dump(stored, f, ensure_ascii=False, indent=2)
    ud = load_user_data()
    ud["added"] = []
    ud["deleted"] = []
    ud["edits"] = {}
    ud["from_moshav"] = {}
    ud["notes"] = {}
    save_user_data(ud)


def check_auth():
    config = load_config()
    if not config.get("password_hash"):
        return False
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    try:
        parts = token.split(":")
        if len(parts) != 2:
            return False
        user, pw = parts
        h = hashlib.sha256((config.get("user", "") + ":" + pw).encode()).hexdigest()
        return h == config.get("password_hash")
    except Exception:
        return False


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    user = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    config = load_config()
    if not config.get("password_hash"):
        return jsonify({"ok": False, "error": "לא הוגדר משתמש"}), 401
    h = hashlib.sha256((config.get("user", "") + ":" + password).encode()).hexdigest()
    if user != config.get("user", "") or h != config.get("password_hash"):
        return jsonify({"ok": False, "error": "משתמש או סיסמה שגויים"}), 401
    token = f"{user}:{password}"
    return jsonify({"ok": True, "token": token})


def _digits_only_phone(s):
    if s is None:
        return ""
    return re.sub(r"\D", "", str(s))


def _is_israeli_mobile_digits(d):
    x = _digits_only_phone(d)
    if not x:
        return False
    n = x
    if n.startswith("972"):
        n = n[3:]
    elif n.startswith("0"):
        n = n[1:]
    return len(n) >= 9 and n[0] == "5"


def _intl_phone_for_vcf(t):
    """Match professionals.html buildVcardFromSaveButton: digits and + only, then leading +."""
    x = "".join(c for c in str(t) if c.isdigit() or c == "+")
    if not x:
        return ""
    if not x.startswith("+"):
        x = "+" + x
    return x


def _escape_vcf_value(s):
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _build_vcard_v3(name, raw_phone_strings, field, extra_info):
    """Build vCard 3.0 text; raw_phone_strings same as pipe-split list from the UI."""
    intl_list = []
    for t in raw_phone_strings:
        v = _intl_phone_for_vcf(t)
        if v:
            intl_list.append(v)
    if not intl_list:
        return None
    display_name = (name or "").strip() or "איש קשר"
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "FN:" + _escape_vcf_value(display_name),
        "N:;" + _escape_vcf_value(display_name) + ";;;",
    ]
    pref_on_mobile = False
    for intl in intl_list:
        d = intl[1:] if intl.startswith("+") else intl
        mob = _is_israeli_mobile_digits(d)
        type_part = "CELL" if mob else "VOICE"
        if mob and not pref_on_mobile:
            type_part = "CELL,PREF"
            pref_on_mobile = True
        lines.append("TEL;TYPE=" + type_part + ":" + _escape_vcf_value(intl))
    field = (field or "").strip()[:500]
    extra_info = (extra_info or "").strip()[:2000]
    if field:
        lines.append("TITLE:" + _escape_vcf_value(field))
    if extra_info:
        lines.append("X-EXTRA-INFO:" + _escape_vcf_value(extra_info))
    lines.append("END:VCARD")
    return "\r\n".join(lines)


@app.route("/api/contact.vcf", methods=["POST"])
def contact_vcf():
    """Generate vCard on the server (reliable download headers on many browsers)."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:400] if isinstance(data.get("name"), str) else ""
    field = (data.get("field") or "").strip()[:500] if isinstance(data.get("field"), str) else ""
    ex = data.get("extra_info")
    extra_info = (ex.strip()[:2000] if isinstance(ex, str) else "") or ""
    phones_in = data.get("phones")
    if isinstance(phones_in, list):
        raw = [str(p).strip() for p in phones_in[:25] if str(p).strip()]
    else:
        all_tels = data.get("all_tels")
        all_tels = all_tels.strip() if isinstance(all_tels, str) else ""
        raw = [x.strip() for x in all_tels.split("|") if x.strip()][:25]
    vcard = _build_vcard_v3(name, raw, field, extra_info)
    if not vcard:
        return jsonify({"ok": False, "error": "אין מספר טלפון תקין"}), 400
    resp = Response(
        vcard.encode("utf-8"),
        mimetype="text/vcard; charset=utf-8",
    )
    resp.headers["Content-Disposition"] = 'attachment; filename="contact.vcf"'
    return resp


def entry_for_client(row):
    """Copy of row for API; note is internal (import) only, not exposed to the web UI."""
    d = dict(row)
    d.pop("note", None)
    return d


def load_restaurants():
    """רשימת מסעדות מ־JSON; מוסיף id לרשומות ישנות ושומר אם צריך."""
    if not RESTAURANTS_PATH.exists():
        return []
    with open(RESTAURANTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    changed = False
    for row in data:
        if not isinstance(row, dict):
            continue
        if not (row.get("id") or "").strip():
            row["id"] = secrets.token_urlsafe(12)
            changed = True
    if changed:
        save_restaurants(data)
    return [r for r in data if isinstance(r, dict)]


def save_restaurants(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESTAURANTS_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


@app.route("/api/restaurants", methods=["GET"])
def get_restaurants():
    rows = load_restaurants()
    config = load_config()
    has_edit_mode = bool(config.get("password_hash"))
    out = []
    for r in rows:
        d = {k: v for k, v in r.items() if not str(k).startswith("_")}
        out.append(d)
    return jsonify({"restaurants": out, "has_edit_mode": has_edit_mode})


@app.route("/api/restaurants", methods=["POST"])
def add_restaurant():
    if not check_auth():
        return jsonify({"ok": False, "error": "נדרשת התחברות"}), 401
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "נא למלא שם"}), 400
    rows = load_restaurants()
    row = {
        "id": secrets.token_urlsafe(12),
        "name": name,
        "restaurant_type": (data.get("restaurant_type") or "").strip(),
        "location": (data.get("location") or "").strip(),
        "note": (data.get("note") or "").strip(),
        "extra_info": (data.get("extra_info") or "").strip(),
    }
    rows.append(row)
    save_restaurants(rows)
    return jsonify({"ok": True, "id": row["id"]})


@app.route("/api/restaurants/<rid>", methods=["PATCH"])
def patch_restaurant(rid):
    if not check_auth():
        return jsonify({"ok": False, "error": "נדרשת התחברות"}), 401
    rid = rid.replace("%2B", "+")
    data = request.get_json() or {}
    rows = load_restaurants()
    idx = next((i for i, r in enumerate(rows) if str(r.get("id", "")) == rid), -1)
    if idx < 0:
        return jsonify({"ok": False, "error": "לא נמצא"}), 404
    row = rows[idx]
    for key in ("name", "restaurant_type", "location", "note", "extra_info"):
        if key in data:
            row[key] = (data.get(key) or "").strip() if isinstance(data.get(key), str) else str(data.get(key) or "")
    if not (row.get("name") or "").strip():
        return jsonify({"ok": False, "error": "נא למלא שם"}), 400
    save_restaurants(rows)
    return jsonify({"ok": True})


@app.route("/api/restaurants/<rid>", methods=["DELETE"])
def delete_restaurant(rid):
    if not check_auth():
        return jsonify({"ok": False, "error": "נדרשת התחברות"}), 401
    rid = rid.replace("%2B", "+")
    rows = load_restaurants()
    new_rows = [r for r in rows if str(r.get("id", "")) != rid]
    if len(new_rows) == len(rows):
        return jsonify({"ok": False, "error": "לא נמצא"}), 404
    save_restaurants(new_rows)
    return jsonify({"ok": True})


@app.route("/api/entries", methods=["GET"])
def get_entries():
    entries = merge_entries()
    config = load_config()
    has_edit_mode = bool(config.get("password_hash"))
    return jsonify(
        {"entries": [entry_for_client(e) for e in entries], "has_edit_mode": has_edit_mode}
    )


@app.route("/api/entries", methods=["POST"])
def add_entry():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    phone_display = (data.get("phone_display") or "").strip() or phone
    field = (data.get("field") or "").strip()
    from_moshav = bool(data.get("from_moshav"))
    # note is internal only; not accepted from the web UI
    extra_info = (data.get("extra_info") or "").strip()
    if not phone and phone_display:
        phone = "".join(c for c in phone_display if c.isdigit())
    if not name or not (phone or phone_display):
        return jsonify({"ok": False, "error": "נא למלא שם ומספר טלפון"}), 400
    ud = load_user_data()
    added = ud.get("added", [])
    row = {
        "name": name,
        "phone": phone or "".join(c for c in phone_display if c.isdigit()),
        "phone_display": phone_display,
        "field": field,
        "from_moshav": from_moshav,
        "note": "",
        "extra_info": extra_info,
    }
    ph = data.get("phones")
    if isinstance(ph, list) and len(ph) > 1:
        row["phones"] = [str(p).strip() for p in ph if str(p).strip()]
    added.append(row)
    ud["added"] = added
    save_user_data(ud)
    flush_entries_to_disk()
    return jsonify({"ok": True})


@app.route("/api/entries/<key>", methods=["PATCH"])
def patch_entry(key):
    if not check_auth():
        return jsonify({"ok": False, "error": "נדרשת התחברות"}), 401
    data = request.get_json() or {}
    ud = load_user_data()
    key = key.replace("%2B", "+")
    if "from_moshav" in data:
        fm = ud.get("from_moshav", {})
        fm[key] = bool(data["from_moshav"])
        ud["from_moshav"] = fm
    # note is not updated via API (internal / import only)
    if (
        "field" in data
        or "name" in data
        or "phone" in data
        or "phone_display" in data
        or "extra_info" in data
        or "phones" in data
    ):
        ed = ud.get("edits", {})
        if key not in ed:
            ed[key] = {}
        if "field" in data:
            ed[key]["field"] = (data.get("field") or "").strip()
        if "name" in data:
            ed[key]["name"] = (data.get("name") or "").strip()
        if "phone" in data:
            ed[key]["phone"] = (data.get("phone") or "").strip()
        if "phone_display" in data:
            ed[key]["phone_display"] = (data.get("phone_display") or "").strip()
        elif "phone" in data:
            ed[key]["phone_display"] = (data.get("phone") or "").strip()
        if "extra_info" in data:
            ed[key]["extra_info"] = (data.get("extra_info") or "").strip()
        if "phones" in data:
            ph = data.get("phones")
            if isinstance(ph, list) and len(ph) > 1:
                ed[key]["phones"] = [str(p).strip() for p in ph if str(p).strip()]
            else:
                ed[key]["phones"] = None
        ud["edits"] = ed
    save_user_data(ud)
    flush_entries_to_disk()
    return jsonify({"ok": True})


@app.route("/api/entries/<key>", methods=["DELETE"])
def delete_entry(key):
    if not check_auth():
        return jsonify({"ok": False, "error": "נדרשת התחברות"}), 401
    key = key.replace("%2B", "+")
    ud = load_user_data()
    deleted_list = ud.get("deleted", [])
    if key not in deleted_list:
        deleted_list.append(key)
        ud["deleted"] = deleted_list
        save_user_data(ud)
        flush_entries_to_disk()
    return jsonify({"ok": True})


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/professionals.html")
def professionals_page():
    return send_from_directory(APP_DIR, "professionals.html")


@app.route("/restaurants.html")
def restaurants_page():
    return send_from_directory(APP_DIR, "restaurants.html")


@app.route("/data/<path:path>")
def data(path):
    return send_from_directory(DATA_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
