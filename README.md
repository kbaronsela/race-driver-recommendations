# אתר המלצות מקבוצת וואטסאפ

## הפעלה

1. **יצירת הנתונים** (פעם אחת, או אחרי עדכון ה־zip):
   ```bash
   cd /Users/hagaisela/dnai
   python3 scripts/extract_and_parse.py
   ```
   הקובץ `whatsapp test bck.zip` צריך להיות בתיקיית ההורדות.

2. **הרצת האתר** (עם שרת – לעריכה והוספת אנשי קשר):
   ```bash
   cd /Users/hagaisela/dnai/website
   pip install -r requirements.txt
   python3 server.py
   ```
   לפתוח בדפדפן: http://localhost:5001

   בלי שרת (רק צפייה): `python3 -m http.server 8080` ואז http://localhost:8080 (אין עריכה/הוספה).

## פריסה ב-Render (גישה מכל מחשב/טלפון)

1. **דחוף את הפרויקט ל-GitHub** (אם עדיין לא שם).

2. **היכנס ל-[render.com](https://render.com)** והתחבר עם GitHub.

3. **New → Web Service**, בחר את ה-repo. הגדר:
   - **Root Directory:** `website`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn server:app --bind 0.0.0.0:$PORT`

4. **Environment:** הוסף משתנים (כדי לאפשר התחברות ועריכה):
   - `RENDER_USER` = שם המשתמש (למשל admin)
   - `RENDER_PASSWORD` = הסיסמה

5. **Deploy.** אחרי הסיום תקבל כתובת כמו `https://recommendations-xxxx.onrender.com`.

**הערה:** בחשבון החינמי של Render האתר "נרדם" אחרי כ־15 דקות ללא גישה – הפעלה ראשונה אחרי שינה יכולה לקחת כמה שניות. בנוסף, קבצי הנתונים (`user_data.json`, `config.json`) לא נשמרים בין הפעלות – הוספות ועריכות עלולות לאבד אחרי redeploy. לשמירה קבועה אפשר להוסיף Render Disk (בתשלום) או לחבר מסד נתונים.

## התחברות ועריכה

- **הגדרת משתמש וסיסמה** (פעם אחת – כדי שיופיעו אפשרויות עריכה):
  ```bash
  cd website
  python3 scripts/set_password.py
  ```
  אחרי ההגדרה יופיעו באתר שדה "משתמש" וכפתור "התחבר". אחרי התחברות: עריכה (תחום, "מהמושב") על כל רשומה.

- **בלי משתמש מוגדר**: כולם יכולים רק להוסיף אנשי קשר (אין עריכה).

## הוספת איש קשר

- כפתור "הוסף איש קשר": שם, טלפון, תחום עיסוק (רשימה מוגדרת + אפשרות "אחר – הזן ידנית"), סימון "מהמושב".

## חיפוש

- חיפוש חופשי בעברית: שם, תחום עיסוק, או מספר טלפון.
