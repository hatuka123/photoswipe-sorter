# PhotoSwipe – מיון תמונות בחצים

| מקש | פעולה |
|---|---|
| ← או A | העברה ל-`delete-queue` (לא נמחק באמת) |
| → או D | העברה ל-`keep-archive` |
| ↑ או W | העברה ל-`starred` |
| ↓ או Z | ביטול הפעולה האחרונה (עד 20 אחורה) |
| רווח | עצירה/המשך של סרטון |
| M | השתקת סרטון |

האותיות עובדות גם כשהמקלדת בעברית. החזקת מקש לא "רצה" על כמה תמונות.

## סרטונים
בחלק העליון אפשר לבחור: תמונות + סרטונים / רק תמונות / רק סרטונים (נשמר ב-`config.json` בשדה `media`: `both` / `photos` / `videos`).
הסרטונים מתנגנים עם קול בתוך החלון, בעזרת VLC מצומצם (`vendor\vlc`) שנכלל בבנייה.
בפעם הראשונה אחרי העתקת התוכנה, הסרטון הראשון עלול להיפתח לאט כי Windows Defender סורק את קבצי VLC.

## איזה קובץ להפעיל
- `dist\PhotoSwipe\PhotoSwipe.exe` – **גרסת תיקייה, מהירה** (1.5–3.5 שניות לפתיחה). העבירו את כל התיקייה `PhotoSwipe` ביחד.
- `dist\PhotoSwipe.exe` – קובץ יחיד, נוח להעברה, אבל נפתח לאט (~10 שניות, עם חלון "Loading").

## הגדרות – `config.json`
נוצר ליד קובץ ה-exe (אם התיקייה חסומה לכתיבה: `%APPDATA%\PhotoSwipe`).

```json
{
  "root_folder": "D:\\Photos",
  "batch_size": 50,
  "delete_dir": "",
  "keep_dir": "",
  "starred_dir": "",
  "log_file": ""
}
```
- תיקיות יעד ריקות = `<root_folder>\PhotoSwipe ממוין\delete-queue` וכו' (אותו כונן = העברה מיידית).
  תיקיות בשם `PhotoSwipe ממוין` לא נסרקות שוב, גם בתוך תת-תיקיות.
- כל הקבצים הממוינים נכנסים ישירות לתיקיית היעד, בלי תת-תיקיות. שם כפול מקבל ` (1)`, ` (2)`...
  ביטול (↓) מחזיר את הקובץ לתת-התיקייה המקורית שלו.
- תיקיית `_PhotoSwipe` מגרסאות קודמות משנה את שמה ל-`PhotoSwipe ממוין` בפעם הבאה שבוחרים את התיקייה, והתוכן שלה משוטח.
- קבצי המידע של Google Takeout (`photo.jpg.json`, `photo.jpg.supplemental-metadata.json`) עוברים יחד עם התמונה
  (ובסרטון של "תמונה חיה" – ה-json של התמונה, אם התמונה כבר לא שם).
- `log_file` ריק = `actions_log.csv` ליד ה-exe (עמודות: זמן, פעולה, מנה, מאיפה, לאן).

## פיתוח
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\python main.py                 # הרצה
.venv\Scripts\python tests\test_app.py       # בדיקה מלאה עם 240 תמונות דמה + סרטונים
.venv\Scripts\python tests\test_folders.py   # תיקיות יעד שטוחות, מעבר מ-_PhotoSwipe
.venv\Scripts\python tests\test_sidecars.py  # קבצי json של Takeout
.venv\Scripts\python tools\make_icon.py      # ציור האייקון מחדש (assets\)
powershell -ExecutionPolicy Bypass -File build.ps1   # בניית שתי גרסאות ה-exe
.venv\Scripts\python tests\verify_exe.py dist\PhotoSwipe\PhotoSwipe.exe <תיקייה ריקה>
```
