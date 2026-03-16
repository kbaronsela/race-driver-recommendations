#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal server: auth (single user), serve entries (base + user_data), add/edit.
"""
import json
import hashlib
import os
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config.json"
USER_DATA_PATH = DATA_DIR / "user_data.json"
ENTRIES_PATH = DATA_DIR / "entries.json"

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
            row.update(edits[key])
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
            row.update(edits[key])
        overlay_note = notes.get(key, "") or (edits.get(key) or {}).get("note", "")
        row["note"] = overlay_note if overlay_note else (row.get("note") or "")
        row["_key"] = norm_phone(row.get("phone")) or key
        row["_added"] = True
        result.append(row)
    return result


def _entry_to_stored(row):
    """Strip internal keys for writing to entries.json."""
    return {
        "name": row.get("name", ""),
        "phone": row.get("phone_display", row.get("phone", "")),
        "field": row.get("field", ""),
        "from_moshav": bool(row.get("from_moshav")),
        "note": (row.get("note") or "").strip(),
    }


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


@app.route("/api/entries", methods=["GET"])
def get_entries():
    entries = merge_entries()
    config = load_config()
    has_edit_mode = bool(config.get("password_hash"))
    return jsonify({"entries": entries, "has_edit_mode": has_edit_mode})


@app.route("/api/entries", methods=["POST"])
def add_entry():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    field = (data.get("field") or "").strip()
    from_moshav = bool(data.get("from_moshav"))
    note = (data.get("note") or "").strip()
    if not name or not phone:
        return jsonify({"ok": False, "error": "נא למלא שם ומספר טלפון"}), 400
    ud = load_user_data()
    added = ud.get("added", [])
    added.append({
        "name": name,
        "phone": phone,
        "phone_display": phone,
        "field": field,
        "from_moshav": from_moshav,
        "note": note,
    })
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
    if "note" in data:
        no = ud.get("notes", {})
        no[key] = (data.get("note") or "").strip()
        ud["notes"] = no
    if "field" in data or "name" in data or "phone" in data:
        ed = ud.get("edits", {})
        if key not in ed:
            ed[key] = {}
        if "field" in data:
            ed[key]["field"] = (data.get("field") or "").strip()
        if "name" in data:
            ed[key]["name"] = (data.get("name") or "").strip()
        if "phone" in data:
            new_phone = (data.get("phone") or "").strip()
            ed[key]["phone"] = new_phone
            ed[key]["phone_display"] = new_phone
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


@app.route("/data/<path:path>")
def data(path):
    return send_from_directory(DATA_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
