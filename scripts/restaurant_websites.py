# -*- coding: utf-8 -*-
"""Curated restaurant name → official website URL. Used when building data/restaurants.json."""

from __future__ import annotations

# Official or primary sites only where reasonably certain; "" when none / ambiguous.
WEBSITE_BY_NAME: dict[str, str] = {
    "bibo vino": "",
    "PE PE": "",
    "Sins": "",
    "Zink": "https://zinc.co.il/",
    "אבו חסן (טירה)": "",
    "אדמה (זיכרון)": "",
    "אורנה ואלה / רביבה וסיליה": "",
    "אושי אושי": "https://www.oshioshi.co.il/",
    "איוטאיה": "",
    "אייזיס": "https://www.isisbeer.co.il/",
    "אלבית (Albait)": "https://albait.co.il/",
    "אלבמה": "",
    "אנגוס": "",
    "אצל פפו בכרם": "",
    "באגסי": "",
    "בופה (אזור תעשייה כפר סבא)": "",
    "בוקה": "https://www.bucke-cafe.com/",
    "ביסטרו דה כרמל": "https://www.bistrodecarmel.co.il/",
    "בית ליבנה": "",
    "בן זגר": "",
    "בנדיקט": "https://www.benedict.co.il/",
    "בני ציון": "",
    "בר אסייתי": "https://www.asiandeli.co.il/",
    "ג'וז ודניאל": "https://www.goujeanddaniel.co.il/",
    "גוהר": "",
    "גומבה": "https://goomba.co.il/",
    "גלידה יונק": "https://www.glida.com/",
    "גלריה הביתית (שף פרטי)": "",
    "גמני": "",
    "דג דגן (dagdagan)": "",
    "דלאל": "https://dallal.co.il/",
    "האחים באבן גבירול": "https://haachim.co.il/",
    "הדסון": "https://hudson-tlv.com/",
    "הלב הרחב": "https://halev-harahav.co.il/",
    "המקדש": "",
    "הניסים של השף": "",
    "חומוס מלול ובלאדי": "",
    "טאטי": "",
    "לחם יין": "https://www.lechemyain.co.il/",
    "מונטיפיורי (יקב)": "https://www.montefiorewines.net/",
    "מוריס": "https://en.machne.co.il/category/morris",
    "מידס": "",
    "מיט בר": "https://www.meatbar.co.il/",
    "מיתוס": "https://meatos.co.il/",
    "מל ומישל": "",
    "מלון מונטיפיורי": "https://www.montefiore.co.il/",
    "מנטה ריי": "https://www.mantaray.co.il/",
    "מנסורה": "",
    "מסעדה טבעונית (ויצמן)": "https://www.tevahaochel.online/",
    "מסעדת אסתר": "https://www.ester-rest.co.il/",
    "מסעדת הארזים": "",
    "מסעדת מחנה יהודה / מחניודה": "https://www.machneyuda.co.il/",
    "משייה (מלון מנדליי)": "https://www.mashya.co.il/",
    "נונו": "https://nonomimi.com/",
    "נורמן": "https://www.thenorman.com/he/",
    "נישי": "https://nishi.co.il/",
    "סושימוטו": "",
    "סיאטרה / סאן": "",
    "עזורה / פתיליות": "",
    "עליזה — קוסקוס": "",
    "פועה": "",
    "פטגוניה": "",
    "פיאנו / זיגי": "",
    "פלאפל נייד (דוכנים)": "",
    "פסטה וזהו": "",
    "צל תמר": "",
    "קוביה": "",
    "קזן": "https://kazan.co.il/",
    "קיסו": "https://ki-su.co.il/",
    "אוגוסט": "",
    "קפה נואר": "https://www.cafenoir.co.il/",
    "קפה נילי": "https://www.nili-rest.co.il/",
    "ריבר": "https://www.river-bar.co.il/",
    "שגב (הרצליה)": "https://www.segevchef.com/",
    "שוק העיר (מגדל B)": "",
    "תיאו": "",
}


def assign_websites(rows: list[dict], *, log_hints: bool = False) -> int:
    """
    Set each row's ``website`` from WEBSITE_BY_NAME (final display name after merges).
    Returns count of rows with a non-empty website.
    """
    names_in_file = {r["name"] for r in rows}
    unknown = sorted(names_in_file - set(WEBSITE_BY_NAME))
    stale = sorted(set(WEBSITE_BY_NAME) - names_in_file)
    if log_hints:
        if unknown:
            print("Note: add to WEBSITE_BY_NAME (left empty):", ", ".join(unknown))
        if stale:
            print("Note: stale WEBSITE_BY_NAME keys (not in JSON):", ", ".join(stale))

    for r in rows:
        name = r["name"]
        if name in WEBSITE_BY_NAME:
            r["website"] = WEBSITE_BY_NAME[name]
        else:
            r.setdefault("website", "")

    return sum(1 for r in rows if (r.get("website") or "").strip())
