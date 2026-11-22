# -*- coding: utf-8 -*-
"""טיפול בתמונות שמועלות: בדיקה, כיווץ ויצירת תמונה ממוזערת."""
import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_SIDE = 1600
THUMB_SIDE = 560


class ImageError(ValueError):
    """תמונה שלא ניתן לשמור. ההודעה מוצגת למשתמש."""


def save_image(file_storage):
    """שומר תמונה שהועלתה ומחזיר (שם קובץ, שם תמונה ממוזערת). זורק ImageError אם היא לא תקינה.

    התמונה נשמרת מחדש כ-JPEG מכווץ, וכך גם יורדים ממנה נתוני ה-EXIF (לרבות מיקום ה-GPS).
    """
    if not file_storage.filename:
        raise ImageError("לא נבחר קובץ.")
    data = file_storage.read()
    if not data:
        raise ImageError("הקובץ שנבחר ריק.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("תמונה גדולה מדי — עד 12MB לתמונה.")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ImageError("הקובץ אינו תמונה בפורמט נתמך (JPEG, PNG, WebP).")

    name = None
    try:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "PA"):
            rgba = img.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, (255, 255, 255))
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            img = flattened
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.info.pop("exif", None)
        img.thumbnail((MAX_SIDE, MAX_SIDE))

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(12)
        img.save(UPLOAD_DIR / f"{name}.jpg", "JPEG", quality=85, optimize=True)
        thumb = img.copy()
        thumb.thumbnail((THUMB_SIDE, THUMB_SIDE))
        thumb.save(UPLOAD_DIR / f"{name}_t.jpg", "JPEG", quality=80, optimize=True)
    except ImageError:
        raise
    except Exception:
        if name:
            delete_image_files([f"{name}.jpg"])  # the file may not have been written yet
        raise ImageError("שמירת התמונה נכשלה. נא לנסות תמונה אחרת.")

    return f"{name}.jpg", f"{name}_t.jpg"


def delete_image_files(file_names):
    """מוחק מהדיסק תמונה ואת התמונה הממוזערת שלה."""
    for file_name in file_names or []:
        if not file_name:
            continue
        for candidate in (file_name, f"{Path(file_name).stem}_t.jpg"):
            try:
                (UPLOAD_DIR / candidate).unlink()
            except OSError:
                pass
