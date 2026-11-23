#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mishelanu — אינדקס בעלי מקצוע בשדה ורבורג.

הרצה מקומית:   python mishelanu/app.py   ואז לפתוח http://localhost:5002
פריסה:         gunicorn app:app   (מתוך התיקייה mishelanu)

מנהל/ת האתר (עריכה ומחיקה): כניסה בעמוד /login. פרטי הכניסה מוגדרים במשתני סביבה
MISHELANU_USER ו־MISHELANU_PASSWORD, או על ידי  python mishelanu/set_password.py  שיוצר את config.json.
כשהאתר מוצפן (HTTPS) כדאי להגדיר MISHELANU_SECURE_COOKIES=1.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import (Flask, abort, g, redirect, render_template, request, session,
                   send_from_directory, url_for)
from markupsafe import Markup, escape

import db
import media

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SECRET_PATH = db.DATA_DIR / "secret_key"

# מרכז המושב שדה ורבורג לפי OpenStreetMap — נקודת ההתחלה של המפה
HOME_LAT, HOME_LNG = 32.2061, 34.9048
MAX_IMAGES = 8
LIMITS = {"name": 80, "field": 60, "phone": 30, "address": 200, "description": 4000}
CSRF_COOKIE = "mishelanu_csrf"

LIST_SELECT = """
    SELECT b.*,
           (SELECT i.thumb FROM images i
             WHERE i.business_id = b.id ORDER BY i.sort, i.id LIMIT 1) AS thumb
      FROM businesses b
"""

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("MISHELANU_SECURE_COOKIES") == "1"
# שם משלו, כדי שלא להתנגש עם עוגיות של אתר אחר שרץ על אותה כתובת
app.config["SESSION_COOKIE_NAME"] = "mishelanu_session"

db.init_db()


def load_secret_key():
    """המפתח שחותם על עוגיית ההתחברות. נשמר בתיקיית הנתונים כדי שההתחברות תשרוד הפעלה מחדש."""
    try:
        key = SECRET_PATH.read_bytes()
    except OSError:
        key = b""
    if len(key) < 32:
        key = secrets.token_bytes(32)
        SECRET_PATH.write_bytes(key)
    return key


app.secret_key = load_secret_key()


# ---------------------------------------------------------------- עזרים לתבניות

def digits(value):
    return re.sub(r"\D", "", value or "")


def wa_number(phone):
    """מספר הטלפון בפורמט בין־לאומי לקישור וואטסאפ."""
    number = digits(phone)
    if number.startswith("972"):
        return number
    if number.startswith("0"):
        return "972" + number[1:]
    return number


def waze_url(row):
    """קישור ל-Waze בפורמט הרשמי (https://waze.com/ul): ניווט לפי מיקום שנשמר, ואם אין — חיפוש הכתובת.

    במחשב Waze נפתח כמפה באתר; בטלפון עם האפליקציה הוא נפתח באפליקציה ומתחיל לנווט.
    """
    if row["lat"] is not None and row["lng"] is not None:
        point = quote(f"{row['lat']},{row['lng']}", safe="")
        return f"https://waze.com/ul?ll={point}&navigate=yes"
    if row["address"]:
        return "https://waze.com/ul?q=" + quote(f"{row['address']}, שדה ורבורג")
    return None


_URL_RE = re.compile(r"(https?://[^\s<>\"']+?)([.,;:!?]*)(?=\s|$)")


def render_text(text):
    """טקסט חופשי → HTML בטוח: ירידת שורה נשמרת וכתובות הופכות לקישורים."""
    safe = str(escape(text or ""))
    safe = _URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener">\1</a>\2', safe)
    return Markup(safe.replace("\r\n", "\n").replace("\n", "<br>\n"))


app.jinja_env.filters["text"] = render_text
app.jinja_env.globals.update(
    digits=digits, wa_number=wa_number, waze_url=waze_url,
    home_lat=HOME_LAT, home_lng=HOME_LNG,
)


# -------------------------------------------------------------------- מסד נתונים

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def list_businesses(q=None, field=None):
    """חיפוש: כל מילה צריכה להופיע בשם, בתחום, בטקסט או בכתובת."""
    where, args = [], []
    for word in (q or "").split():
        pattern = f"%{word}%"
        where.append(
            "(b.name LIKE ? OR b.field LIKE ? OR b.description LIKE ? OR b.address LIKE ?)"
        )
        args += [pattern] * 4
    if field:
        where.append("b.field = ?")
        args.append(field)
    sql = LIST_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY b.name"
    return query(sql, args)


def get_business(bid):
    rows = query("SELECT * FROM businesses WHERE id = ?", (bid,))
    return rows[0] if rows else None


def get_images(bid):
    return query(
        "SELECT * FROM images WHERE business_id = ? ORDER BY sort, id", (bid,)
    )


def list_fields():
    rows = query(
        "SELECT field, COUNT(*) AS n FROM businesses WHERE field <> ''"
        " GROUP BY field ORDER BY n DESC, field"
    )
    return [{"name": r["field"], "count": r["n"]} for r in rows]


def save_images(bid, files, conn):
    """שומר תמונות חדשות לבעל מקצוע. אם אחת מהן לא תקינה — לא נשמרת אף אחת."""
    saved = []
    try:
        for file_storage in files:
            saved.append(media.save_image(file_storage))
    except media.ImageError:
        media.delete_image_files([file_name for file_name, _thumb in saved])
        raise
    start = conn.execute(
        "SELECT COALESCE(MAX(sort), -1) + 1 FROM images WHERE business_id = ?", (bid,)
    ).fetchone()[0]
    conn.executemany(
        "INSERT INTO images (business_id, file, thumb, sort) VALUES (?, ?, ?, ?)",
        [(bid, file_name, thumb, start + i) for i, (file_name, thumb) in enumerate(saved)],
    )


def create_business(values, files):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO businesses (name, field, phone, address, lat, lng, description)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (values["name"], values["field"], values["phone"], values["address"],
         values["lat"], values["lng"], values["description"]),
    )
    bid = cur.lastrowid
    try:
        save_images(bid, files, conn)
    except media.ImageError:
        conn.rollback()
        raise
    conn.commit()
    return bid


def update_business(bid, values, files, remove_ids):
    conn = get_db()
    save_images(bid, files, conn)
    removed = []
    for image_id in remove_ids:
        row = conn.execute(
            "SELECT file FROM images WHERE id = ? AND business_id = ?", (image_id, bid)
        ).fetchone()
        if row:
            removed.append(row["file"])
            conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.execute(
        "UPDATE businesses SET name = ?, field = ?, phone = ?, address = ?,"
        " lat = ?, lng = ?, description = ? WHERE id = ?",
        (values["name"], values["field"], values["phone"], values["address"],
         values["lat"], values["lng"], values["description"], bid),
    )
    conn.commit()
    media.delete_image_files(removed)


# -------------------------------------------------------------------- הרשאות מנהל

def password_hash(user, password):
    return hashlib.sha256(f"{user}:{password}".encode()).hexdigest()


def load_admin():
    user = os.environ.get("MISHELANU_USER", "").strip()
    password = os.environ.get("MISHELANU_PASSWORD", "").strip()
    if user and password:
        return {"user": user, "password_hash": password_hash(user, password)}
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(saved, dict) and saved.get("user") and saved.get("password_hash"):
            return saved
    return None


def is_admin():
    return bool(session.get("admin")) and load_admin() is not None


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not load_admin():
            return render_template(
                "error.html", title="אין הרשאה",
                message="עריכה ומחיקה זמינות רק למנהל/ת האתר.",
                back=url_for("index"),
            ), 403
        if not is_admin():
            # הנתיב המלא, כולל הקידומת כשהאתר רץ מתוך שרת אחר (למשל /mishelanu)
            return redirect(url_for("login", next=request.script_root + request.path))
        return view(*args, **kwargs)

    return wrapped


def is_safe_target(path):
    """רק נתיב פנימי באתר — כדי שאחרי הכניסה אי אפשר יהיה להפנות לאתר אחר."""
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        check_csrf_or_abort()
        admin = load_admin()
        user = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        allowed = admin is not None and all([
            hmac.compare_digest(user.encode(), str(admin["user"]).encode()),
            hmac.compare_digest(
                password_hash(admin["user"], password).encode(),
                str(admin["password_hash"]).encode(),
            ),
        ])
        if allowed:
            session.clear()
            session["admin"] = True
            target = request.form.get("next") or ""
            return redirect(target if is_safe_target(target) else url_for("index"))
        time.sleep(0.4)  # האטה קלה למי שמנסה לנחש סיסמה
        error = "שם המשתמש או הסיסמה שגויים."
    return render_template(
        "login.html", error=error, target=request.args.get("next", "")
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.context_processor
def inject_admin():
    return {"is_admin": is_admin(), "admin_ready": load_admin() is not None}


# --------------------------------------------------- הגנה מבקשות מזויפות (CSRF)

def csrf_token():
    """טוקן נגד שליחת טופס מאתר אחר: עוגייה ושדה מוסתר עם אותו ערך."""
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = secrets.token_urlsafe(24)
        g.new_csrf_token = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.after_request
def save_csrf_cookie(resp):
    token = g.pop("new_csrf_token", None)
    if token:
        resp.set_cookie(
            CSRF_COOKIE, token, max_age=31536000, httponly=True, samesite="Lax",
            secure=request.is_secure, path=(request.script_root or "") + "/",
        )
    return resp


def check_csrf_or_abort():
    sent = (request.form.get("csrf_token") or "").encode()
    stored = (request.cookies.get(CSRF_COOKIE) or "").encode()
    if not sent or not hmac.compare_digest(sent, stored):
        abort(400)


# ------------------------------------------------------------------------ טפסים

def empty_values():
    return {"name": "", "field": "", "phone": "", "address": "", "description": "",
            "lat": None, "lng": None}


def read_form():
    """קורא את הטופס ומחזיר (ערכים, שגיאות לפי שדה)."""
    values, errors = empty_values(), {}
    for key, limit in LIMITS.items():
        values[key] = (request.form.get(key) or "").strip()[:limit]
    if not values["name"]:
        errors["name"] = "נא למלא שם."
    if not values["field"]:
        errors["field"] = "נא למלא תחום."
    if len(digits(values["phone"])) < 9:
        errors["phone"] = "נא למלא מספר טלפון תקין."
    if request.form.get("lat") or request.form.get("lng"):
        try:
            lat = float(request.form.get("lat"))
            lng = float(request.form.get("lng"))
        except (TypeError, ValueError):
            lat = lng = None
        if lat is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            errors["location"] = "המיקום שסומן על המפה אינו תקין. נא לסמן מחדש."
        else:
            values["lat"], values["lng"] = lat, lng
    return values, errors


def uploaded_files():
    return [f for f in request.files.getlist("images") if f and f.filename]


def form_context(heading, action, values, errors, images):
    return {
        "heading": heading, "action": action, "values": values, "errors": errors,
        "images": images, "fields": [f["name"] for f in list_fields()],
    }


# ------------------------------------------------------------------------ דפים

@app.route("/")
def index():
    q = (request.args.get("q") or "").strip()[:100]
    field = (request.args.get("field") or "").strip()[:60]
    rows = list_businesses(q, field or None)
    # תחומים נפוצים מוצגים ככפתורי סינון; תחום פעיל מוצג תמיד
    chips = [f for f in list_fields() if f["count"] > 1][:16]
    if field and field not in [f["name"] for f in chips]:
        chips.append({"name": field, "count": len(rows)})
    return render_template("index.html", q=q, field=field, rows=rows, chips=chips)


@app.route("/add", methods=["GET", "POST"])
def add():
    values, errors, files = empty_values(), {}, []
    if request.method == "POST":
        check_csrf_or_abort()
        if request.form.get("contact_website"):  # שדה מוסתר שרק בוטים ממלאים
            return redirect(url_for("index"))
        values, errors = read_form()
        files = uploaded_files()
        if len(files) > MAX_IMAGES:
            errors["images"] = f"אפשר להעלות עד {MAX_IMAGES} תמונות."
        if not errors:
            try:
                bid = create_business(values, files)
            except media.ImageError as exc:
                errors["images"] = str(exc)
            else:
                return redirect(url_for("detail", bid=bid))
    return render_template(
        "form.html",
        **form_context("הוספה לאינדקס", url_for("add"), values, errors, []),
    )


@app.route("/b/<int:bid>")
def detail(bid):
    row = get_business(bid)
    if row is None:
        abort(404)
    return render_template("detail.html", b=row, images=get_images(bid))


@app.route("/b/<int:bid>/edit", methods=["GET", "POST"])
@require_admin
def edit(bid):
    row = get_business(bid)
    if row is None:
        abort(404)
    errors = {}
    if request.method == "POST":
        check_csrf_or_abort()
        values, errors = read_form()
        files = uploaded_files()
        if len(files) > MAX_IMAGES:
            errors["images"] = f"אפשר להעלות עד {MAX_IMAGES} תמונות."
        if not errors:
            try:
                update_business(
                    bid, values, files, request.form.getlist("remove_images")
                )
            except media.ImageError as exc:
                errors["images"] = str(exc)
            else:
                return redirect(url_for("detail", bid=bid))
    else:
        values = dict(row)
    return render_template(
        "form.html",
        **form_context(
            "עריכה", url_for("edit", bid=bid), values, errors, get_images(bid)
        ),
    )


@app.route("/b/<int:bid>/delete", methods=["POST"])
@require_admin
def delete(bid):
    check_csrf_or_abort()
    conn = get_db()
    files = [r["file"] for r in conn.execute(
        "SELECT file FROM images WHERE business_id = ?", (bid,)
    )]
    conn.execute("DELETE FROM businesses WHERE id = ?", (bid,))
    conn.commit()
    media.delete_image_files(files)
    return redirect(url_for("index"))


@app.route("/i/<int:image_id>/delete", methods=["POST"])
@require_admin
def delete_image(image_id):
    check_csrf_or_abort()
    conn = get_db()
    row = conn.execute("SELECT file, business_id FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None:
        abort(404)
    conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()
    media.delete_image_files([row["file"]])
    return redirect(url_for("edit", bid=row["business_id"]))


@app.route("/map")
def map_page():
    rows = query(LIST_SELECT + " WHERE lat IS NOT NULL AND lng IS NOT NULL ORDER BY b.name")
    points = [{
        "id": r["id"], "name": r["name"], "field": r["field"],
        "lat": r["lat"], "lng": r["lng"], "thumb": r["thumb"],
        "url": url_for("detail", bid=r["id"]),
    } for r in rows]
    return render_template(
        "map.html", points=points, focus_id=request.args.get("focus", type=int)
    )


# --------------------------------------------------------------------- קבצים, PWA

@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(media.UPLOAD_DIR, filename, max_age=31536000)


@app.route("/manifest.json")
def manifest():
    return send_from_directory(ROOT, "manifest.json")


@app.route("/sw.js")
def sw():
    return send_from_directory(ROOT, "sw.js")


# ------------------------------------------------------------------------ שגיאות

@app.errorhandler(400)
def bad_request(_e):
    return render_template(
        "error.html", title="הטופס לא נשלח",
        message="תוקף הטופס פג. נא לחזור, לרענן את הדף ולנסות שוב.",
        back=url_for("index"),
    ), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template(
        "error.html", title="העמוד לא נמצא",
        message="ייתכן שהקישור ישן, או שהעמוד נמחק.",
        back=url_for("index"),
    ), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template(
        "error.html", title="הקבצים גדולים מדי",
        message="התמונות שנבחרו גדולות מדי. נא לבחור פחות תמונות, או תמונות קטנות יותר.",
        back=url_for("index"),
    ), 413


if __name__ == "__main__":
    port = int(os.environ.get("MISHELANU_PORT", "5002"))
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in (48, 98, 10048):
            print(f"Port {port} is already in use - the site is probably already"
                  f" running: http://localhost:{port}")
        else:
            raise
