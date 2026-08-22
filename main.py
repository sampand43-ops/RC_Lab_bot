import os
import json
import sqlite3
import re
import asyncio
import difflib
import random
import uuid
import urllib.request
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ==================== الإعدادات الأساسية ====================

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

CHANNEL_ID = -1004395670008

# الكروب الرئيسي — مصدر ثانٍ ثابت للكتب بجانب القناة، دائماً معتمد بغض النظر عن حالة قاعدة البيانات
GROUP_ID = -1002066990968
ADMIN_IDS = [7898871921, 1937491557]
BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

# الخط العربي المطلوب لتصدير قائمة الكتب كـ PDF — يُحمَّل تلقائياً عند أول استخدام فقط
FONT_PATH = os.path.join(DATA_DIR, "NotoNaskhArabic-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notonaskharabic/NotoNaskhArabic%5Bwght%5D.ttf"
_font_registered = False


def ensure_arabic_font():
    """يحمّل الخط العربي عند الحاجة فقط (أول ضغطة على زر تصدير PDF)، وليس عند بدء التشغيل"""
    global _font_registered
    if _font_registered:
        return True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        if not os.path.exists(FONT_PATH):
            urllib.request.urlretrieve(FONT_URL, FONT_PATH)
        pdfmetrics.registerFont(TTFont("Arabic", FONT_PATH))
        _font_registered = True
        return True
    except Exception as e:
        print(f"⚠️ تعذّر تحميل/تسجيل الخط العربي: {e}")
        return False


# ==================== النصوص ====================

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)

LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
    f"سأقوم بالمغادرة الآن..."
)

ADMIN_WELCOME_TEXT = (
    "أهلاً بك في لوحة تحكم البوت 📚⚙️\n\n"
    "بصفتك مشرفاً رئيسياً للنظام، تتوفر لك الصلاحيات الكاملة لجميع الخصائص.\n\n"
    "💡 للحصول على دليل التعليمات، أرسل: /help\n"
    "⚙️ للوحة التحكم التفاعلية (إحصائيات، حذف، بحث تشخيصي)، أرسل: /panel\n\n"
    "البوت قيد التشغيل وجاهز لخدمتك ✨"
)

ADMIN_HELP_TEXT = (
    "📌 *دليل استخدام البوت*\n\n"
    "━━━━━━ 👑 *صلاحيات المشرف* ━━━━━━\n\n"
    "• *تفعيل المجموعات:* أضف البوت لأي مجموعة جديدة لتفعيلها تلقائياً.\n\n"
    "• *الأرشفة التاريخية (JSON):* صدّر سجل القناة من Telegram Desktop "
    "(⋮ ← Export chat history ← عطّل كل أنواع الوسائط ← Format: JSON)، "
    "ثم أرسل ملف `result.json` للبوت في الخاص.\n\n"
    "• *الأرشفة الآلية:* أي ملف جديد يُرفع في القناة أو كروب معتمد يُحفظ فوراً.\n\n"
    "• *منع التكرار:* أي كتاب مكرر (بفارق تشكيل، فاصلة، اسم مؤلف، أو رقم نسخة بين "
    "قوسين) يُتجاهل تلقائياً عند الأرشفة ولا يُخزَّن مرتين.\n\n"
    "• *لوحة التحكم:* أرسل `/panel` لأزرار الإحصائيات والحذف والبحث التشخيصي.\n\n"
    "• *البحث الحر في الخاص:* اكتب اسم الكتاب مباشرة دون أي شرط.\n\n"
    "━━━━━━ 👥 *للأعضاء* ━━━━━━\n\n"
    "• داخل الكروب: أشِر للبوت `@" + BOT_USERNAME + " اسم الكتاب` أو رُدّ على رسالته."
)


# ==================== قاعدة البيانات ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            msg_id INTEGER,
            source_chat_id INTEGER DEFAULT -1004395670008,
            dedup_key TEXT,
            part_number INTEGER DEFAULT 0,
            UNIQUE(msg_id, source_chat_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


# رقم إصدار خوارزمية dedup_key — يُرفع كل مرة يتغيّر فيها compute_dedup_fields
# جوهرياً، ليعرف migrate_db أنه يجب إعادة حساب dedup_key لكل السجلات القديمة
# (وليس فقط الجديدة/الناقصة)، لأن القيم المحسوبة بالخوارزمية القديمة صارت خاطئة.
DEDUP_ALGO_VERSION = "2"


def migrate_db():
    """يضيف الأعمدة الناقصة لقواعد بيانات قديمة، ثم (لمرة واحدة فقط عند أول إقلاع
    بعد أي تغيير بخوارزمية dedup_key، أو لأي سجل ناقص المفتاح) يحسب dedup_key و
    part_number، يحذف التكرارات المكتشفة، وأخيراً يُنشئ فهرس UNIQUE يمنع أي تكرار
    جديد من الدخول للأرشيف من الأساس مستقبلاً."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(archive)")
    columns = [col[1] for col in cursor.fetchall()]

    if "source_chat_id" not in columns:
        cursor.execute(f"ALTER TABLE archive ADD COLUMN source_chat_id INTEGER DEFAULT {CHANNEL_ID}")
        conn.commit()
    if "dedup_key" not in columns:
        cursor.execute("ALTER TABLE archive ADD COLUMN dedup_key TEXT")
        conn.commit()
    if "part_number" not in columns:
        cursor.execute("ALTER TABLE archive ADD COLUMN part_number INTEGER DEFAULT 0")
        conn.commit()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.commit()

    cursor.execute("SELECT value FROM bot_settings WHERE key = 'dedup_algo_version'")
    row = cursor.fetchone()
    stored_version = row[0] if row else None

    if stored_version != DEDUP_ALGO_VERSION:
        # تغيّرت خوارزمية حساب dedup_key — يجب إعادة حسابها لكل السجلات (وليس فقط
        # الناقصة)، فنمسح القيم القديمة أولاً ونحذف الفهرس القديم قبل إعادة البناء.
        print(f"🔧 تغيّرت خوارزمية منع التكرار (v{stored_version} -> v{DEDUP_ALGO_VERSION})، إعادة حساب كل السجلات...")
        cursor.execute("DROP INDEX IF EXISTS idx_archive_dedup")
        cursor.execute("UPDATE archive SET dedup_key = NULL")
        conn.commit()

    cursor.execute("SELECT COUNT(*) FROM archive WHERE dedup_key IS NULL")
    pending = cursor.fetchone()[0]
    conn.close()

    if pending > 0:
        _backfill_and_deduplicate(pending)
    else:
        _ensure_dedup_unique_index()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO bot_settings (key, value) VALUES ('dedup_algo_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (DEDUP_ALGO_VERSION,)
    )
    conn.commit()
    conn.close()


def _backfill_and_deduplicate(pending_count):
    """يُشغَّل تلقائياً مرة واحدة فقط (عند أول إقلاع بعد هذا التحديث، أو على أي سجلات
    جديدة نادراً ما تصل بدون المفتاح لأي سبب): يحسب dedup_key و part_number لكل سجل
    ينقصه، ثم يحذف التكرارات (يُبقي سجلاً واحداً فقط لكل توليفة كتاب+جزء، ويُفضّل
    أطول اسم لأنه غالباً الأكثر اكتمالاً/يحتوي اسم المؤلف)، وأخيراً يُفعّل فهرس
    UNIQUE يمنع دخول أي تكرار جديد مستقبلاً من الأساس دون أي فحص وقت البحث."""
    print(f"🔧 ترحيل لمرة واحدة: حساب مفاتيح عدم التكرار لـ {pending_count} سجلاً...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, book_name FROM archive WHERE dedup_key IS NULL")
    rows = cursor.fetchall()

    updates = []
    for row_id, book_name in rows:
        dedup_key, part_number = compute_dedup_fields(book_name or "")
        updates.append((dedup_key, part_number, row_id))

    cursor.executemany("UPDATE archive SET dedup_key = ?, part_number = ? WHERE id = ?", updates)
    conn.commit()
    print("✅ تم حساب المفاتيح لجميع السجلات.")

    cursor.execute(
        "SELECT dedup_key, part_number, id, book_name FROM archive "
        "WHERE dedup_key IS NOT NULL ORDER BY dedup_key, part_number"
    )
    all_rows = cursor.fetchall()

    grouped = defaultdict(list)
    for dedup_key, part_number, row_id, book_name in all_rows:
        grouped[(dedup_key, part_number)].append((row_id, book_name or ""))

    ids_to_delete = []
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: len(x[1]), reverse=True)  # أطول اسم = الأكثر اكتمالاً، نُبقيه
        for row_id, _ in items[1:]:
            ids_to_delete.append(row_id)

    if ids_to_delete:
        print(f"🗑️ حذف {len(ids_to_delete)} سجلاً مكرراً من أصل {len(all_rows)}...")
        CHUNK = 500
        for i in range(0, len(ids_to_delete), CHUNK):
            chunk = ids_to_delete[i:i + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cursor.execute(f"DELETE FROM archive WHERE id IN ({placeholders})", chunk)
            conn.commit()
        print("✅ تم حذف التكرارات.")
    else:
        print("ℹ️ لا توجد تكرارات لحذفها.")

    conn.close()
    _ensure_dedup_unique_index()


def _ensure_dedup_unique_index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_dedup ON archive(dedup_key, part_number)"
        )
        conn.commit()
        print("✅ فهرس منع التكرار (dedup_key, part_number) فعّال الآن — لن يدخل أي تكرار جديد للأرشيف.")
    except sqlite3.IntegrityError as e:
        # نادراً قد تبقى تكرارات (مثلاً عدة سجلات بلا اسم صالح إطلاقاً) — لا نوقف
        # تشغيل البوت بسببها، فقط نُبلغ بالسجلات لمراجعتها يدوياً لاحقاً إن لزم
        print(f"⚠️ تعذّر تفعيل فهرس منع التكرار بالكامل بسبب تكرارات متبقية: {e}")
    finally:
        conn.close()


def is_group_approved(chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM allowed_groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)


# ==================== أدوات معالجة النصوص العربية ====================

ARABIC_NUM_WORDS = {
    'الأول': 1, 'اول': 1, '1': 1, 'الثاني': 2, 'ثاني': 2, '2': 2,
    'الثالث': 3, 'ثالث': 3, '3': 3, 'الرابع': 4, 'رابع': 4, '4': 4,
    'الخامس': 5, 'خامس': 5, '5': 5, 'السادس': 6, 'سادس': 6, '6': 6,
    'السابع': 7, 'سابع': 7, '7': 7, 'الثامن': 8, 'ثامن': 8, '8': 8,
    'التاسع': 9, 'تاسع': 9, '9': 9, 'العاشر': 10, 'عاشر': 10, '10': 10,
}

PART_PATTERN = re.compile(
    r'(الجزء|المجلد|جـ?|مجلد|part|vol)\s*([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)',
    re.IGNORECASE
)
# مهم جداً: رقم واحد فقط (1-9) في نهاية الاسم يُعتبر "رقم جزء محتمل".
# لا نسمح بأرقام أطول لأنها غالباً معرّفات عشوائية (IDs) لا علاقة لها بترقيم الأجزاء.
TRAILING_NUM_PATTERN = re.compile(r'[\s\-_]([0-9٠-٩])\s*(?:\.pdf|\.epub|\.zip)?$')

# رقم بين قوسين هلالية في نهاية الاسم (مثال: "الكتاب (2).pdf") يُعتبر "علامة تكرار/نسخة"
# فقط (رفعة ثانية لنفس الكتاب) — وليس رقم جزء إطلاقاً. يُحذف تماماً قبل أي معالجة أخرى
# حتى لا يمنع اعتبار "الكتاب" و"الكتاب (2)" نفس الكتاب.
TRAILING_PAREN_NUM_PATTERN = re.compile(
    r'\s*\(\s*[0-9٠-٩]+\s*\)\s*(?:\.pdf|\.epub|\.zip|\.mobi|\.docx?)?$',
    re.IGNORECASE
)


def get_title_line(raw_book_name):
    """يأخذ السطر الأول فقط من اسم الكتاب المخزَّن (بعض الكتب أُرشفت من كابشن طويل:
    عنوان بالسطر الأول ثم وصف بالأسطر التالية)."""
    if not raw_book_name:
        return raw_book_name
    first = raw_book_name.split('\n', 1)[0].strip()
    return first if first else raw_book_name


def strip_duplicate_marker(text):
    """يحذف رقم النسخة بين قوسين هلالية من نهاية الاسم (علامة تكرار فقط، ليس جزءاً)."""
    if not text:
        return text
    return TRAILING_PAREN_NUM_PATTERN.sub('', text).strip()


def extract_part_number(filename):
    if not filename:
        return None
    filename = get_title_line(filename)
    filename = strip_duplicate_marker(filename)
    match = PART_PATTERN.search(filename)
    if match:
        val = match.group(2)
        if val in ARABIC_NUM_WORDS:
            return ARABIC_NUM_WORDS[val]
        val_en = val.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val_en.isdigit():
            return int(val_en)
    num_match = TRAILING_NUM_PATTERN.search(filename)
    if num_match:
        val = num_match.group(1).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val.isdigit():
            return int(val)
    return None


def strip_part_pattern(filename):
    if not filename:
        return ""
    filename = get_title_line(filename)
    filename = strip_duplicate_marker(filename)
    stripped = PART_PATTERN.sub('', filename)
    stripped = TRAILING_NUM_PATTERN.sub('', stripped)
    stripped = re.sub(r'\.(pdf|epub|zip|mobi|docx?)$', '', stripped, flags=re.IGNORECASE)
    return stripped.strip()


def strip_al(word):
    """يوحّد الكلمات بإزالة (ال) التعريف: الشرقاوي -> شرقاوي"""
    if len(word) > 3 and word.startswith('ال'):
        return word[2:]
    return word


def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r'[\u064b-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    words = [strip_al(w) for w in text.strip().lower().split()]
    return ' '.join(words)


def get_words(normalized_text):
    return [w for w in normalized_text.split() if len(w) >= 2]


EXTENSION_ONLY_PATTERN = re.compile(r'\.(pdf|epub|zip|mobi|docx?|rar|txt)$', re.IGNORECASE)


def strip_extension_only(filename):
    """يحذف امتداد الملف فقط (.pdf مثلاً) دون لمس أي رقم أو نص آخر في الاسم."""
    if not filename:
        return ""
    return EXTENSION_ONLY_PATTERN.sub('', filename).strip()


def compute_dedup_fields(raw_book_name):
    """يحسب (dedup_key, part_number) لكتاب معيّن — يُستدعى مرة واحدة فقط وقت
    الأرشفة (رفعة جديدة أو استيراد JSON)، وليس عند كل بحث.

    dedup_key = السطر الأول من الاسم بعد حذف: علامة رقم النسخة بين قوسين، اسم/رقم
    الجزء، الامتداد، ثم تطبيع النص (حذف التشكيل والفواصل وتوحيد الحروف). بهذا فإن
    'الكتاب.pdf' و'الكتاب (2).pdf' (فرق تشكيل/فاصلة/رقم نسخة فقط) يُعتبران نفس
    الكتاب.

    ملاحظة مهمة: لا نحذف اسم المؤلف (كل ما بعد الشرطة) من dedup_key، خلافاً لإصدار
    سابق من هذه الدالة. السبب: بعض الملفات مخزَّنة بصيغة 'العنوان - المؤلف' وأخرى
    بصيغة 'المؤلف - العنوان' (مؤلف أولاً)، ولا توجد طريقة موثوقة لتمييز الصيغتين
    تلقائياً. حذف 'كل ما بعد أول شرطة' بشكل أعمى كان يحذف العنوان الحقيقي فعلياً
    في حالة 'المؤلف - العنوان' ويُبقي اسم المؤلف وحده كمفتاح — وهذا بالضبط ما كان
    يجعل كتابة اسم المؤلف فقط تُطابق وتُرسل كتبه. الاحتفاظ بالسطر كاملاً يحل هذا
    نهائياً؛ الأثر الجانبي الوحيد هو أن 'الكتاب' و'الكتاب - المؤلف' لم يعودا
    يُعتبران تكراراً تلقائياً (يُؤرشفان كسجلّين منفصلين إن وصلا فعلاً بصيغتين
    مختلفتين)، وهذا أفضل من فقدان عنوان كتاب حقيقي أو دمج مؤلف بكل كتبه بالخطأ.

    part_number = رقم الجزء الحقيقي إن وُجد صراحة في الاسم (0 يعني لا يوجد جزء).
    'الكتاب الجزء الأول' و'الكتاب الجزء الثاني' يُعطيان نفس dedup_key لكن
    part_number مختلف، فيبقيان سجلّين منفصلين — وهذا هو الاستثناء المطلوب للأجزاء."""
    part_number = extract_part_number(raw_book_name) or 0
    title_no_part = strip_part_pattern(raw_book_name)
    core = strip_extension_only(title_no_part)
    dedup_key = normalize_arabic(core)
    return dedup_key, part_number


FORBIDDEN_PREFIXES = ["صور من", "قصص من", "مختصر", "شرح"]


# ==================== فهرس البحث المُخزَّن مؤقتاً ====================
# ملاحظة مهمة: بما أن التكرار أصبح مستحيلاً على مستوى قاعدة البيانات (فهرس UNIQUE
# على dedup_key + part_number)، فإن الفهرس هنا يُبنى مباشرة حسب dedup_key: كل مفتاح
# فريد = كتاب واحد، وكل أجزائه (إن وُجدت) مرتبة ومجمّعة معه سلفاً. لا حاجة بعد الآن
# لأي منطق حذف تكرار أو "تجميع سلسلة" وقت البحث — البيانات نظيفة من مصدرها.

_search_index_cache = {
    "fingerprint": None, "keys": [], "groups": {},
    "norm_names": [], "norm_names_no_ext": [], "core_index": {}
}


def get_search_index():
    """يُرجع (keys, groups, norm_names, norm_names_no_ext, core_index).
    - keys: قائمة dedup_key الفريدة.
    - groups[key]["parts"]: كل (book_name, msg_id, source_chat_id, part_number) لهذا الكتاب.
    - groups[key]["display_name"]: أطول اسم بين أجزائه (للعرض والبحث بالاسم+المؤلف).
    - norm_names / norm_names_no_ext: الاسم التمثيلي مطبّعاً، بحسب ترتيب keys.
    - core_index: كلمة -> مجموعة مواضع (indices في keys) من dedup_key نفسه."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM archive")
    fingerprint = cursor.fetchone()

    if _search_index_cache["fingerprint"] == fingerprint:
        conn.close()
        c = _search_index_cache
        return (c["keys"], c["groups"], c["norm_names"], c["norm_names_no_ext"], c["core_index"])

    cursor.execute(
        "SELECT book_name, msg_id, source_chat_id, dedup_key, part_number FROM archive "
        "WHERE dedup_key IS NOT NULL ORDER BY dedup_key, part_number"
    )
    rows = cursor.fetchall()
    conn.close()

    norm_forbidden = [normalize_arabic(p) for p in FORBIDDEN_PREFIXES]

    keys = []
    groups = {}
    for book_name, msg_id, source_chat_id, dedup_key, part_number in rows:
        norm_full = normalize_arabic(book_name)
        if any(norm_full.startswith(p) for p in norm_forbidden):
            continue
        if dedup_key not in groups:
            groups[dedup_key] = {"parts": [], "display_name": book_name}
            keys.append(dedup_key)
        elif len(book_name) > len(groups[dedup_key]["display_name"]):
            groups[dedup_key]["display_name"] = book_name
        groups[dedup_key]["parts"].append((book_name, msg_id, source_chat_id, part_number))

    norm_names, norm_names_no_ext = [], []
    core_index = defaultdict(set)
    for i, k in enumerate(keys):
        title_line = get_title_line(groups[k]["display_name"])
        norm_names.append(normalize_arabic(title_line))
        norm_names_no_ext.append(normalize_arabic(strip_extension_only(title_line)))
        for w in get_words(k):
            core_index[w].add(i)

    _search_index_cache.update(
        fingerprint=fingerprint, keys=keys, groups=groups,
        norm_names=norm_names, norm_names_no_ext=norm_names_no_ext, core_index=core_index
    )
    return keys, groups, norm_names, norm_names_no_ext, core_index


def find_book_matches_indexed(norm_query, keys, norm_names, norm_names_no_ext, core_index):
    """
    بحث دقيق بأولويات صارمة، يُرجع قائمة dedup_key المطابقة:
    1) تطابق تام للاسم التمثيلي (بدون امتداد) أو لـ dedup_key نفسه — يعمل حتى بكلمة واحدة.
    2) (كلمتان فأكثر) الاسم التمثيلي الكامل (يشمل اسم المؤلف) يبدأ بنص الطلب بالكامل.
    3) (كلمتان فأكثر) كل كلمات الطلب موجودة داخل dedup_key (العنوان الجوهري فقط، بدون
       اسم المؤلف) — يمنع طلب اسم المؤلف وحده من مطابقة كل كتبه بالخطأ.
    4) (كلمتان فأكثر، وكل كلمة 3 أحرف فأكثر) تطابق تقريبي صارم على dedup_key فقط.
    """
    query_words = get_words(norm_query)

    exact_idx = set(i for i, nn in enumerate(norm_names_no_ext) if nn == norm_query)
    exact_idx |= set(i for i, k in enumerate(keys) if k == norm_query)
    if exact_idx:
        result = [keys[i] for i in exact_idx]
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE1(exact) -> {result}")
        return result

    if len(query_words) < 2:
        print(f"🔎 SEARCH[{norm_query!r}] -> كلمة واحدة، لا تطابق تام -> فارغ")
        return []

    # STAGE2: يشترط أن يبدأ الاسم الكامل (يشمل المؤلف) بنص الطلب، *و* أن تتقاطع كلمات
    # الطلب مع كلمات dedup_key (العنوان فقط، بدون المؤلف). هذا الشرط الإضافي ضروري
    # لأن بعض الملفات مخزَّنة بصيغة "المؤلف - العنوان" (مؤلف أولاً)، فبدونه كان طلب
    # يحتوي اسم المؤلف فقط (بدون أي كلمة من العنوان الفعلي) يمرّ من "يبدأ بـ" بالخطأ
    # ويُرجع كل كتب ذلك المؤلف — وهذا مسموح فقط عبر صيغة "أريد كل كتب/مؤلفات فلان".
    startswith_idx = []
    for i, nn in enumerate(norm_names):
        if not nn.startswith(norm_query):
            continue
        key_words = set(get_words(keys[i]))
        if any(qw in key_words for qw in query_words):
            startswith_idx.append(i)
    if startswith_idx:
        result = [keys[i] for i in startswith_idx]
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE2(startswith+title-overlap) -> {result}")
        return result

    word_sets = [core_index.get(qw) for qw in query_words]
    if all(word_sets):
        common = set.intersection(*word_sets)
        if common:
            result = [keys[i] for i in common]
            print(f"🔎 SEARCH[{norm_query!r}] -> STAGE3(all words in dedup_key) -> {result}")
            return result

    cutoff = 0.9 if any(len(qw) < 3 for qw in query_words) else 0.85

    vocabulary = list(core_index.keys())
    per_word_candidates = []
    for qw in query_words:
        if len(qw) < 3:
            if qw not in core_index:
                print(f"🔎 SEARCH[{norm_query!r}] -> كلمة قصيرة '{qw}' غير موجودة حرفياً -> فارغ")
                return []
            word_candidates = set(core_index[qw])
        else:
            close_words = difflib.get_close_matches(qw, vocabulary, n=5, cutoff=cutoff)
            if not close_words:
                print(f"🔎 SEARCH[{norm_query!r}] -> لا تشابه لكلمة '{qw}' -> فارغ")
                return []
            word_candidates = set()
            for w in close_words:
                word_candidates |= core_index.get(w, set())
        per_word_candidates.append(word_candidates)

    common = set.intersection(*per_word_candidates) if per_word_candidates else set()
    result = [keys[i] for i in common]
    print(f"🔎 SEARCH[{norm_query!r}] -> STAGE4(تقريبي) -> {result}")
    return result


def flatten_matched_keys(matched_keys, groups):
    """يحوّل قائمة dedup_key مطابقة إلى قائمة (book_name, msg_id, source_chat_id)
    جاهزة للإرسال، بحيث تكون أجزاء كل كتاب مرتبة تصاعدياً حسب part_number المخزَّن
    فعلياً بقاعدة البيانات (رقم ثابت، وليس محسوباً لحظياً) — فلا يعود ترتيب
    الأجزاء عرضة للاختلال بين طلب وآخر."""
    out = []
    for k in matched_keys:
        parts = sorted(groups.get(k, {}).get("parts", []), key=lambda p: p[3])
        out.extend((bn, mid, src) for (bn, mid, src, _pn) in parts)
    return out


# ==================== معالجات الكروبات ====================

async def is_allowed_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        if chat.id == GROUP_ID or is_group_approved(chat.id):
            return True
        try:
            await context.bot.send_message(chat.id, LEAVE_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            pass
        finally:
            try:
                await context.bot.leave_chat(chat.id)
            except Exception:
                pass
        return False
    return True


async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ['group', 'supergroup']:
        return
    user_id = update.message.from_user.id if update.message and update.message.from_user else None

    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            if user_id in ADMIN_IDS:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO allowed_groups (chat_id, added_by) VALUES (?, ?)", (chat.id, user_id))
                conn.commit()
                conn.close()
                try:
                    await context.bot.send_message(chat.id, "أهلاً بكم! 📚🤖\nتم تفعيل البوت بنجاح لهذه المجموعة.")
                except Exception:
                    pass
            else:
                try:
                    await context.bot.send_message(chat.id, LEAVE_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
                except Exception:
                    pass
                finally:
                    try:
                        await context.bot.leave_chat(chat.id)
                    except Exception:
                        pass


async def on_bot_left_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.left_chat_member:
        if update.message.left_chat_member.id == context.bot.id:
            chat_id = update.effective_chat.id
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM allowed_groups WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()


# ==================== أرشفة الملفات ====================

async def handle_new_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.message
    if not message:
        return
    chat = update.effective_chat
    if chat is None:
        return
    if context.bot_data.get('bot_paused'):
        return
    # المصادر المعتمدة للأرشفة التلقائية: الكروب الرئيسي، القناة الرئيسية، وأي
    # كروب آخر يُضاف ويُعتمد يدوياً عبر allowed_groups.
    if chat.id not in (GROUP_ID, CHANNEL_ID) and not is_group_approved(chat.id):
        return

    document = message.document or message.video or message.audio
    if not document:
        return

    book_name = document.file_name or message.caption or f"Book_{message.message_id}"
    dedup_key, part_number = compute_dedup_fields(book_name)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # تحقق مسبق: هل يوجد كتاب آخر مؤرشف مسبقاً بنفس (dedup_key, part_number)؟ إن
    # وُجد واسمه مختلف فعلياً عن الاسم الجديد (وليس فرق تشكيل/فاصلة فقط)، فقد يكون
    # كتاباً مختلفاً حقيقةً بنفس العنوان بالصدفة (مثال: "المنشق" و"المنشق - مؤلف
    # آخر") — لا نخسره بصمت، بل نُبلغ الأدمن ليقرر يدوياً.
    cursor.execute(
        "SELECT book_name FROM archive WHERE dedup_key = ? AND part_number = ? LIMIT 1",
        (dedup_key, part_number)
    )
    existing_row = cursor.fetchone()

    try:
        cursor.execute(
            "INSERT INTO archive (book_name, msg_id, source_chat_id, dedup_key, part_number) VALUES (?, ?, ?, ?, ?)",
            (book_name, message.message_id, chat.id, dedup_key, part_number)
        )
        conn.commit()
        print(f"✅ أُرشف تلقائياً: '{book_name}' (msg_id={message.message_id}, chat={chat.id})")
    except sqlite3.IntegrityError as e:
        print(f"ℹ️ '{book_name}' مكرر (رسالة أو محتوى) ولم يُخزَّن مرة أخرى: {e}")
        if existing_row:
            existing_name = existing_row[0]
            if normalize_arabic(get_title_line(existing_name)) != normalize_arabic(get_title_line(book_name)):
                warn_text = (
                    f"⚠️ *تنبيه: تعارض عناوين محتمل*\n\n"
                    f"وصل الآن ملف باسم:\n`{book_name}`\n\n"
                    f"لكن يوجد بالأرشيف مسبقاً كتاب بنفس العنوان الأساسي باسم:\n`{existing_name}`\n\n"
                    f"لم يُحفظ الملف الجديد لأن البوت اعتبره تكراراً لنفس الكتاب.\n"
                    f"إن كانا فعلاً *كتابين مختلفين* (نفس العنوان، مؤلف مختلف)، عدّل اسم/كابشن "
                    f"الملف الجديد ليكون مميزاً أكثر (مثلاً أضف اسم المؤلف بوضوح) وأعد رفعه."
                )
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(admin_id, warn_text, parse_mode="Markdown")
                    except Exception:
                        pass
    except Exception as e:
        print(f"❌ فشلت أرشفة '{book_name}' تلقائياً: {e}")
    finally:
        conn.close()


async def import_json_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    if chat_type != 'private' or user_id not in ADMIN_IDS:
        return

    document = update.message.document
    if not document or not document.file_name.endswith('.json'):
        return

    BOT_API_MAX_DOWNLOAD = 20 * 1024 * 1024
    if document.file_size and document.file_size > BOT_API_MAX_DOWNLOAD:
        size_mb = document.file_size / (1024 * 1024)
        await update.message.reply_text(
            f"⚠️ الملف حجمه {size_mb:.1f} ميجابايت، وهذا أكبر من الحد الذي يسمح تيليجرام "
            f"للبوتات (وليس المستخدمين) بتحميله عبر الـ Bot API، وهو *20 ميجابايت فقط* — "
            f"هذا قيد من تيليجرام نفسه ولا علاقة له بإعدادات البوت أو Railway.\n\n"
            f"📌 *الحل:* أعد تصدير سجل القناة من Telegram Desktop، وفي نافذة التصدير فعّل "
            f"خيار *\"Size limit for one file\"* واجعله مثلاً 15 ميجابايت. سيقوم تيليجرام "
            f"تلقائياً بتقسيم الأرشفة إلى عدة ملفات (result.json, result2.json, ...)، "
            f"وكل ملف سيكون أصغر من الحد المسموح.\n\n"
            f"أرسل لي بعدها كل ملف على حدة (واحداً تلو الآخر) وسأؤرشف كل جزء تلقائياً.",
            parse_mode="Markdown"
        )
        return

    caption = update.message.caption
    forced_source_chat_id = None
    if caption:
        try:
            forced_source_chat_id = int(caption.strip())
        except ValueError:
            forced_source_chat_id = None

    status_msg = await update.message.reply_text("🚀 جاري تحليل ملف التصدير...")

    try:
        try:
            file = await context.bot.get_file(document.file_id)
        except Exception as e:
            if "too big" in str(e).lower() or "file is too big" in str(e).lower():
                await status_msg.edit_text(
                    "⚠️ الملف أكبر من 20 ميجابايت (الحد الأقصى الذي تسمح به تيليجرام لتحميل "
                    "الملفات عبر البوتات تحديداً). أعد تصدير الأرشيف مقسّماً لملفات أصغر "
                    "(خيار \"Size limit for one file\" أثناء التصدير من Telegram Desktop) "
                    "وأرسلها لي واحداً تلو الآخر."
                )
                return
            raise
        json_path = os.path.join(DATA_DIR, f"temp_export_{update.message.message_id}.json")
        await file.download_to_drive(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        auto_detected_source_id = None
        raw_json_id = data.get("id")
        if isinstance(raw_json_id, int):
            auto_detected_source_id = int(f"-100{raw_json_id}")

        if forced_source_chat_id is not None:
            source_chat_id = forced_source_chat_id
            source_note = f"مصدر مفروض يدوياً عبر الكابشن: `{source_chat_id}`"
        elif auto_detected_source_id is not None:
            source_chat_id = auto_detected_source_id
            source_note = f"تم اكتشاف المصدر تلقائياً من الملف: `{source_chat_id}`"
        else:
            source_chat_id = GROUP_ID
            source_note = f"تعذّر اكتشاف المصدر من الملف، تم استخدام الكروب (المصدر الوحيد المعتمد) افتراضياً: `{source_chat_id}`"

        try:
            await status_msg.edit_text(f"🚀 {source_note}\nجاري الأرشفة...", parse_mode="Markdown")
        except Exception:
            pass

        messages = data.get("messages", [])
        total_msgs = len(messages)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")

        def extract_book_name(msg):
            book_name = msg.get("file_name")
            if not book_name:
                text_field = msg.get("text")
                if isinstance(text_field, list):
                    book_name = "".join(
                        part if isinstance(part, str) else part.get("text", "") for part in text_field
                    ).strip()
                elif isinstance(text_field, str):
                    book_name = text_field.strip()
            return book_name

        batch, BATCH_SIZE, processed, last_percent = [], 2000, 0, -1
        skipped_duplicates = 0

        for msg in messages:
            processed += 1
            if msg.get("file") or msg.get("media_type"):
                msg_id = msg.get("id")
                if msg_id is not None:
                    book_name = extract_book_name(msg) or f"Book_{msg_id}"
                    dedup_key, part_number = compute_dedup_fields(book_name)
                    batch.append((book_name, msg_id, source_chat_id, dedup_key, part_number))

            if len(batch) >= BATCH_SIZE:
                cursor.execute("SELECT changes()")
                before = cursor.fetchone()[0]
                cursor.executemany(
                    "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id, dedup_key, part_number) "
                    "VALUES (?, ?, ?, ?, ?)", batch
                )
                conn.commit()
                batch.clear()

            percent = int((processed / total_msgs) * 100) if total_msgs else 100
            if percent >= last_percent + 10:
                last_percent = percent
                try:
                    await status_msg.edit_text(f"⏳ جاري الأرشفة... {percent}% ({processed}/{total_msgs})")
                except Exception:
                    pass

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id, dedup_key, part_number) "
                "VALUES (?, ?, ?, ?, ?)", batch
            )
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM archive WHERE source_chat_id = ?", (source_chat_id,))
        final_count = cursor.fetchone()[0]
        conn.close()
        os.remove(json_path)

        await status_msg.edit_text(
            f"✅ تمت الأرشفة بنجاح!\n"
            f"الرسائل المفحوصة: `{total_msgs}`\n"
            f"إجمالي الكتب المؤرشفة الآن لهذا المصدر: `{final_count}`\n\n"
            f"💡 أي كتاب مكرر (بفارق تشكيل/فاصلة/اسم مؤلف/رقم نسخة بين قوسين، أو حتى "
            f"مكرر من مصدر آخر) تم تجاوزه تلقائياً ولم يُخزَّن مرتين.\n\n"
            f"💡 لديك أجزاء أخرى؟ أرسلها الآن واحداً تلو الآخر."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ أثناء المعالجة:\n`{e}`", parse_mode="Markdown")


# ==================== أوامر أساسية ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(ADMIN_WELCOME_TEXT, parse_mode="Markdown")
        else:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث: أشِر للبوت `@{BOT_USERNAME} اسم الكتاب` أو رُدّ على رسالته.",
            parse_mode="Markdown"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return
        await update.message.reply_text(
            f"للبحث: أشِر للبوت `@{BOT_USERNAME} اسم الكتاب` أو رُدّ على رسالته.", parse_mode="Markdown"
        )
    elif chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode="Markdown")
        else:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)


# ==================== لوحة تحكم الأدمن ====================

def build_admin_panel_keyboard(paused=False):
    pause_label = "▶️ تشغيل البوت" if paused else "⏸️ إيقاف البوت مؤقتاً"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات الأرشيف", callback_data="admin_stats")],
        [InlineKeyboardButton("🔄 تحديث الأرشيف", callback_data="admin_refresh")],
        [InlineKeyboardButton("📄 تصدير أسماء الكتب (PDF)", callback_data="admin_export_pdf")],
        [InlineKeyboardButton("🔎 بحث خام (تشخيص)", callback_data="admin_raw_search")],
        [InlineKeyboardButton("🔢 حذف آخر عدد من الكتب", callback_data="admin_delete_count")],
        [InlineKeyboardButton("🗑️ حذف كامل الأرشيف", callback_data="admin_clear_all")],
        [InlineKeyboardButton("⛔ إيقاف كل الإرسالات الجارية", callback_data="admin_stop_all_sends")],
        [InlineKeyboardButton(pause_label, callback_data="admin_toggle_pause")],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return
    paused = bool(context.bot_data.get('bot_paused'))
    status_line = "\n\n⏸️ *ملاحظة: البوت متوقف مؤقتاً حالياً.*" if paused else ""
    await update.message.reply_text(
        f"⚙️ *لوحة تحكم الأرشيف*{status_line}\n\nاختر أحد الخيارات:",
        parse_mode="Markdown", reply_markup=build_admin_panel_keyboard(paused)
    )


def generate_archive_pdf(output_path):
    import unicodedata
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    font_available = ensure_arabic_font()
    if font_available:
        import arabic_reshaper
        from bidi.algorithm import get_display

    def safe_display(raw_text):
        if not font_available:
            return raw_text
        try:
            shaped = get_display(arabic_reshaper.reshape(raw_text))
            cleaned = ''.join(ch for ch in shaped if unicodedata.category(ch) != 'Cf')
            return cleaned
        except Exception:
            return ''.join(ch for ch in raw_text if ord(ch) < 0x10000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive ORDER BY dedup_key, part_number")
    rows = cursor.fetchall()
    conn.close()

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    font_name = "Arabic" if font_available else "Helvetica"
    line_height, margin_top, margin_bottom = 16, 40, 40
    y = height - margin_top

    c.setFont(font_name, 14)
    title = safe_display(f"فهرس أرشيف الكتب — إجمالي: {len(rows)} كتاباً")
    try:
        c.drawRightString(width - 40, y, title)
    except Exception:
        pass
    y -= line_height * 2

    c.setFont(font_name, 11)
    skipped = 0
    for index, (book_name, msg_id, source_chat_id) in enumerate(rows, start=1):
        raw_line = f"{index}. {book_name}  [msg_id: {msg_id}]"
        line = safe_display(raw_line)
        try:
            c.drawRightString(width - 40, y, line)
        except Exception:
            skipped += 1
            try:
                c.drawRightString(width - 40, y, f"{index}. [تعذّر عرض هذا الاسم] [msg_id: {msg_id}]")
            except Exception:
                pass
        y -= line_height
        if y < margin_bottom:
            c.showPage()
            c.setFont(font_name, 11)
            y = height - margin_top

    c.save()
    return len(rows), skipped


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("عذراً، هذه اللوحة مخصصة للمشرفين فقط.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "admin_stats":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT dedup_key) FROM archive")
        total, unique_books = cursor.fetchone()
        cursor.execute("SELECT source_chat_id, COUNT(*) FROM archive GROUP BY source_chat_id ORDER BY COUNT(*) DESC")
        by_source = cursor.fetchall()
        conn.close()

        text = (
            f"📊 *إحصائيات الأرشيف*\n\n"
            f"إجمالي السجلات: `{total}`\n"
            f"عدد الكتب الفريدة (بعد استبعاد التكرار): `{unique_books}`\n\n"
            f"*حسب المصدر:*\n"
        )
        for chat_id, count in by_source:
            label = "📚 القناة الرئيسية" if chat_id == CHANNEL_ID else (
                "👥 الكروب الرئيسي" if chat_id == GROUP_ID else f"👥 كروب ({chat_id})"
            )
            text += f"• {label}: `{count}`\n"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "admin_clear_all":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، احذف كل شيء", callback_data="admin_clear_all_confirm")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")],
        ])
        await query.edit_message_text(
            "⚠️ *تأكيد الحذف الكامل*\n\nسيُحذف فهرس الأرشيف المحلي فقط (لن تتأثر الملفات الفعلية في القناة). "
            "هذا الإجراء *لا يمكن التراجع عنه*. متأكد؟",
            parse_mode="Markdown", reply_markup=keyboard
        )

    elif data == "admin_clear_all_confirm":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        await query.edit_message_text("✅ تم حذف كامل فهرس الأرشيف بنجاح.", reply_markup=keyboard)

    elif data == "admin_export_pdf":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM archive")
        total = cursor.fetchone()[0]
        conn.close()

        if total == 0:
            await query.edit_message_text(
                "⚠️ الأرشيف فارغ حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
            )
            return

        await query.edit_message_text(f"⏳ جاري توليد PDF لـ {total} كتاباً...")
        pdf_path = os.path.join(DATA_DIR, f"archive_export_{query.message.message_id}.pdf")
        try:
            count, skipped = await asyncio.to_thread(generate_archive_pdf, pdf_path)
            caption = f"📄 فهرس الأرشيف — {count} كتاباً."
            if skipped:
                caption += f"\n⚠️ تعذّر عرض {skipped} اسماً بسبب رموز غير مدعومة فيها (لا يزال رقم رسالتها ظاهراً)."
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id, document=f,
                    filename="archive_books_list.pdf", caption=caption
                )
        except Exception as e:
            await context.bot.send_message(query.message.chat_id, f"❌ خطأ أثناء التوليد:\n`{e}`", parse_mode="Markdown")
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

        await context.bot.send_message(
            query.message.chat_id, "⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
            parse_mode="Markdown", reply_markup=build_admin_panel_keyboard(bool(context.bot_data.get('bot_paused')))
        )

    elif data == "admin_delete_count":
        context.user_data['awaiting_delete_count'] = True
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]])
        await query.edit_message_text(
            "🔢 أرسل الآن *عدد* الكتب لحذفها (آخر ما تمت أرشفته). مثال: `50`",
            parse_mode="Markdown", reply_markup=keyboard
        )

    elif data == "admin_raw_search":
        context.user_data['awaiting_raw_search'] = True
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]])
        await query.edit_message_text(
            "🔎 *بحث خام (تشخيصي)*\n\nأرسل أي كلمة، وسأبحث مباشرة في قاعدة البيانات "
            "(SQL LIKE بدون أي منطق ذكي) لأريك النتائج كما هي مخزّنة فعلياً، مع مفتاح "
            "عدم التكرار ورقم الجزء المحسوبين لكل سجل.",
            parse_mode="Markdown", reply_markup=keyboard
        )

    elif data == "admin_refresh":
        # يفرض إعادة بناء فهرس البحث فوراً (بدل انتظار أول عملية بحث)، ويُعيد حساب
        # dedup_key/part_number لأي سجل وصل بشكل استثنائي بدونهما، ثم يحذف أي تكرار
        # نتج عن ذلك. ملاحظة مهمة: لا يستطيع البوت "سحب" رسائل قديمة فاتته من
        # تيليجرام (لا توجد صلاحية كهذه للبوتات) — هذا الزر يُحدّث فقط بناءً على ما
        # وصل للبوت فعلياً وهو يعمل. لو كتاب رُفع أثناء توقف البوت، الحل هو تصدير
        # ملف JSON جديد يغطي تلك الفترة واستيراده، أو إعادة رفع الكتاب الآن بعد
        # تفعيل الأرشفة من القناة والكروب معاً.
        await query.edit_message_text("🔄 جاري تحديث الأرشيف...")
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archive WHERE dedup_key IS NULL")
            pending = cursor.fetchone()[0]
            conn.close()
            if pending > 0:
                await asyncio.to_thread(_backfill_and_deduplicate, pending)
            else:
                await asyncio.to_thread(_ensure_dedup_unique_index)
            _search_index_cache["fingerprint"] = None  # إجبار إعادة بناء فهرس البحث بالطلب القادم
            get_search_index()

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT dedup_key) FROM archive")
            total, unique_books = cursor.fetchone()
            conn.close()

            result_text = (
                f"✅ *تم تحديث الأرشيف*\n\n"
                f"إجمالي السجلات الآن: `{total}`\n"
                f"عدد الكتب الفريدة: `{unique_books}`\n\n"
                f"ℹ️ ملاحظة: هذا التحديث يعالج فقط ما وصل للبوت فعلياً. إن كان كتاب "
                f"رُفع أثناء توقف البوت عن العمل، أعد رفعه الآن أو استورد ملف JSON يغطي تلك الفترة."
            )
        except Exception as e:
            result_text = f"❌ خطأ أثناء التحديث:\n`{e}`"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        await context.bot.send_message(query.message.chat_id, result_text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "admin_stop_all_sends":
        active = context.bot_data.get('active_sends', {})
        count = len(active)
        for info in active.values():
            info['cancelled'] = True
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        if count:
            text = f"⛔ تم إرسال أمر إيقاف لكل عمليات الإرسال الجارية ({count})، ستتوقف خلال لحظات. البوت يبقى يستقبل طلبات جديدة بشكل طبيعي بعدها."
        else:
            text = "ℹ️ لا توجد عمليات إرسال جارية حالياً لإيقافها."
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "admin_toggle_pause":
        currently_paused = bool(context.bot_data.get('bot_paused'))
        new_state = not currently_paused
        context.bot_data['bot_paused'] = new_state

        if new_state:
            # أوقف فوراً أي عمليات إرسال جارية حالياً (مثلاً استخدام خاطئ من عضو)
            active = context.bot_data.get('active_sends', {})
            for info in active.values():
                info['cancelled'] = True
            status_text = "⏸️ تم *إيقاف البوت* مؤقتاً. أي إرسال جارٍ حالياً سيتوقف خلال لحظات، ولن يستجيب لطلبات الأعضاء العاديين حتى تُعيد تشغيله."
        else:
            status_text = "▶️ تم *تشغيل البوت* من جديد، وهو الآن يستقبل طلبات الأعضاء بشكل طبيعي."

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        await query.edit_message_text(status_text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "admin_back":
        context.user_data.pop('awaiting_delete_count', None)
        context.user_data.pop('awaiting_raw_search', None)
        paused = bool(context.bot_data.get('bot_paused'))
        status_line = "\n\n⏸️ *ملاحظة: البوت متوقف مؤقتاً حالياً.*" if paused else ""
        await query.edit_message_text(
            f"⚙️ *لوحة تحكم الأرشيف*{status_line}\n\nاختر أحد الخيارات:",
            parse_mode="Markdown", reply_markup=build_admin_panel_keyboard(paused)
        )


# ==================== الإرسال والبحث ====================

THANK_YOU_MESSAGES = [
    "📚 تفضّل، أتمنى لك قراءة ممتعة! سعداء دائماً بخدمتك في مجتمع القراءة 🌿",
    "✨ تم إرسال طلبك، استمتع بالقراءة! نورت مجتمع القراءة 📖",
    "🌟 تفضّل كتابك، وبالعافية عليك القراءة! نحن هنا دائماً لأجلك 💚",
    "📖 وصلك الكتاب، قراءة ممتعة إن شاء الله! أهلاً بك دائماً في مجتمعنا 🌸",
]

# --- رد ودّي على رسائل الشكر/المجاملة، بدل معاملتها كطلب بحث فاشل ---
GRATITUDE_TRIGGERS = [
    "شكرا", "شكرا لك", "شكرا جزيلا", "شكرا كتير", "شكرا كثير",
    "اشكرك", "أشكرك", "شكرا الك", "تسلم", "تسلم ايدك", "تسلمي",
    "يعطيك العافيه", "يعطيك العافية", "الله يعطيك العافيه", "الله يعطيك العافية",
    "جزاك الله خيرا", "جزاكم الله خيرا", "مشكور", "مشكوره", "مشكورة",
    "ممنون", "ممنونه", "ممنونة", "تسلمين", "يسلمو",
]
GRATITUDE_TRIGGERS_NORM = [normalize_arabic(t) for t in GRATITUDE_TRIGGERS]

GRATITUDE_REPLIES = [
    "🌿 العفو، وحياك الله! دايماً في خدمتك بمجتمع القراءة 📚",
    "💚 لا شكر على واجب، تشرفنا نخدمك! قراءة ممتعة 📖",
    "🌸 العفو يا غالي، أهلاً بيك دائماً 🌟",
    "✨ حياك الله، ونتمنى لك قراءة ممتعة دائماً! 📚",
]


def is_gratitude_message(clean_query):
    """يتحقق إن كانت الرسالة مجرد شكر/مجاملة قصيرة (وليست طلب بحث حقيقي يبدأ
    بكلمة قريبة من 'شكراً' بالصدفة) — نحصر التحقق برسائل قصيرة (6 كلمات فأقل)
    حتى لا يُساء فهم عنوان كتاب حقيقي طويل يبدأ بكلمة مشابهة."""
    norm = normalize_arabic(clean_query)
    if not norm:
        return False
    if len(norm.split()) > 6:
        return False
    return any(norm == t or norm.startswith(t + ' ') for t in GRATITUDE_TRIGGERS_NORM)


def _send_is_cancelled(context, request_id):
    if not request_id:
        return False
    info = context.bot_data.get('active_sends', {}).get(request_id)
    return bool(info and info.get('cancelled'))


async def _wait_or_cancel(context, request_id, seconds):
    """ينتظر seconds ثانية، لكن يتحقق من ضغط زر 'إيقاف الطلب' كل ثانية بدل الانتظار
    الأعمى — فلا يبقى الزر عالقاً بلا استجابة أثناء انتظار طويل بسبب تحكم الفيضان.
    يُرجع False فوراً إن أُلغي الطلب أثناء الانتظار."""
    waited = 0
    while waited < seconds:
        if _send_is_cancelled(context, request_id):
            return False
        await asyncio.sleep(1)
        waited += 1
    return True


MAX_FLOOD_RETRIES = 5


async def send_book_results(update, context, valid_books):
    """يرسل الكتب من مصدرها بنسخ (copy_message) بدل التحويل (forward_message) — فلا
    يظهر 'محوّلة من' على الرسالة الواصلة للطالب، ويُرسَل الملف بدون أي وصف/كابشن
    أصلي مرفق به. عند اصطدام تيليجرام بحدّ الفيضان (RetryAfter) — وهو ما كان يسبب
    إرسال بعض الأجزاء فقط أو بترتيب مختلط سابقاً — ننتظر بالضبط المدة التي يطلبها
    تيليجرام ثم نُعيد إرسال *نفس* الملف (لا ننتقل لملف آخر ونتركه مفقوداً)."""
    succeeded, failed = [], []

    request_id = None
    control_msg = None
    if len(valid_books) > 1:
        request_id = uuid.uuid4().hex[:10]
        context.bot_data.setdefault('active_sends', {})[request_id] = {
            'cancelled': False, 'user_id': update.effective_user.id
        }
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⛔ إيقاف الطلب", callback_data=f"stopreq_{request_id}")]])
        try:
            control_msg = await update.message.reply_text(
                f"⏳ جاري إرسال {len(valid_books)} ملفاً...", reply_markup=keyboard
            )
        except Exception:
            control_msg = None

    cancelled = False
    for i, (book_name, msg_id, source_chat_id) in enumerate(valid_books):
        if _send_is_cancelled(context, request_id):
            cancelled = True
            break

        candidates = [(msg_id, source_chat_id)]
        if source_chat_id != GROUP_ID:
            candidates.append((msg_id, GROUP_ID))

        last_error = None
        sent = False
        for attempt_msg_id, attempt_source in candidates:
            attempts_left = MAX_FLOOD_RETRIES
            while attempts_left > 0:
                if _send_is_cancelled(context, request_id):
                    cancelled = True
                    break
                try:
                    await context.bot.copy_message(
                        chat_id=update.effective_chat.id,
                        from_chat_id=attempt_source,
                        message_id=attempt_msg_id,
                        caption=""  # إزالة أي وصف/كابشن أصلي مرفق بالملف
                    )
                    succeeded.append(book_name)
                    sent = True
                    break
                except RetryAfter as e:
                    wait_time = int(e.retry_after) + 1
                    print(f"⏳ Flood control لـ '{book_name}': الانتظار {wait_time} ثانية ثم إعادة المحاولة...")
                    if not await _wait_or_cancel(context, request_id, wait_time):
                        cancelled = True
                        break
                    attempts_left -= 1
                    last_error = e
                    continue
                except Exception as e:
                    last_error = e
                    print(f"⚠️ محاولة فاشلة لـ '{book_name}' (msg_id={attempt_msg_id}, source={attempt_source}): {e}")
                    break
            if sent or cancelled:
                break

        if cancelled:
            break

        if not sent:
            failed.append((book_name, msg_id, str(last_error)))

        if i < len(valid_books) - 1:
            await asyncio.sleep(0.75)

    if request_id:
        context.bot_data.get('active_sends', {}).pop(request_id, None)
        if control_msg:
            try:
                if cancelled:
                    await control_msg.edit_text(f"⛔ تم إيقاف الطلب — أُرسل {len(succeeded)} من {len(valid_books)}.")
                else:
                    await control_msg.edit_text(f"✅ تم إرسال {len(succeeded)} ملفاً.")
            except Exception:
                pass

    if succeeded:
        try:
            await update.message.reply_text(random.choice(THANK_YOU_MESSAGES))
        except Exception:
            pass

    if failed:
        chat_type = update.effective_chat.type
        requester_user_id = update.effective_user.id
        requester_name = update.effective_user.full_name or str(requester_user_id)
        chat_label = "الخاص" if chat_type == 'private' else (update.effective_chat.title or str(update.effective_chat.id))
        admin_lines = [f"⚠️ تعذّر توفير {len(failed)} كتاب/كتب طُلبت من {chat_label} بواسطة {requester_name}:"]
        for book_name, msg_id, err in failed:
            admin_lines.append(f"• {book_name} (msg_id: {msg_id})\n   السبب: {err}")
        admin_report = "\n".join(admin_lines)
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, admin_report)
            except Exception as e:
                print(f"❌ تعذّر إبلاغ الأدمن {admin_id}: {e}")

        if not succeeded:
            await update.message.reply_text(
                "⚠️ الكتاب موجود في الأرشيف لكن تعذّر توفيره فعلياً حالياً (قد يكون حُذف من مصدره). "
                "تم إبلاغ الأدمن فوراً وسيُعاد توفيره قريباً بإذن الله."
            )

    return succeeded, failed


async def stop_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    request_id = data.split('_', 1)[1] if '_' in data else None
    active = context.bot_data.get('active_sends', {})
    info = active.get(request_id) if request_id else None

    if not info:
        await query.answer("⏳ انتهى هذا الطلب بالفعل أو تم إرساله بالكامل.", show_alert=True)
        return

    if query.from_user.id != info.get('user_id') and query.from_user.id not in ADMIN_IDS:
        await query.answer("هذا الطلب ليس لك.", show_alert=True)
        return

    info['cancelled'] = True
    await query.answer("⛔ سيتم إيقاف الطلب بعد الملف الحالي...")


async def notify_admins_not_found(context, update, query_text):
    chat_type = update.effective_chat.type
    requester_name = update.effective_user.full_name or str(update.effective_user.id)
    chat_label = "الخاص" if chat_type == 'private' else (update.effective_chat.title or str(update.effective_chat.id))
    message = f"🔍 طلب كتاب غير متوفر:\n• الطلب: {query_text}\n• من: {chat_label}\n• بواسطة: {requester_name}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, message)
        except Exception as e:
            print(f"❌ تعذّر إبلاغ الأدمن {admin_id} بكتاب غير موجود: {e}")


FILLER_PHRASES = sorted([
    "اريد كتاب", "أريد كتاب", "اريد كتاب ال", "أريد كتاب ال",
    "ابغى", "ابغى كتاب", "ابغى رواية",
    "ممكن", "ممكن كتاب", "ممكن رواية",
    "متوفر", "متوفر كتاب", "متوفر رواية",
    "عايز", "عايز كتاب", "عايز رواية",
    "عاوز", "عاوز كتاب", "عاوز رواية",
    "عايزة", "عايزة كتاب", "عايزة رواية",
    "عاوزة", "عاوزة كتاب", "عاوزة رواية",
    "هل يوجد", "هل يوجد كتاب", "هل يوجد لديك كتاب", "هل يوجد رواية", "هل يوجد لديك رواية",
    "هل توجد", "هل توجد لديك", "هل توجد لديك رواية",
    "اريد رواية", "أريد رواية",
    "اعطني كتاب", "أعطني كتاب",
    "احتاج الى", "احتاج إلى", "أحتاج الى", "أحتاج إلى",
    "احتاج كتاب", "أحتاج كتاب", "احتاج رواية", "أحتاج رواية",
    "احتاج", "أحتاج",
    "بدي كتاب", "بدي رواية", "بدي",
    "ابي كتاب", "أبي كتاب", "ابي رواية", "أبي رواية", "ابي", "أبي",
    "لو سمحت", "من فضلك", "ياريت", "لو تكرمت",
    "اريد", "أريد", "كتاب", "رواية",
    "سلسلة","اريد سلسلة",
], key=len, reverse=True)


def strip_filler_phrases(query_text):
    cleaned = query_text
    changed = True
    while changed:
        changed = False
        for phrase in FILLER_PHRASES:
            if cleaned.startswith(phrase):
                cleaned = cleaned[len(phrase):].strip()
                changed = True
                break
    return cleaned


async def search_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    text = update.message.text.strip()

    # --- استقبال عدد الحذف (من لوحة التحكم) ---
    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_delete_count'):
        context.user_data.pop('awaiting_delete_count', None)
        try:
            if text.isdigit() and int(text) > 0:
                n = int(text)
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM archive ORDER BY id DESC LIMIT ?", (n,))
                ids_to_delete = [row[0] for row in cursor.fetchall()]
                if ids_to_delete:
                    cursor.executemany("DELETE FROM archive WHERE id = ?", [(i,) for i in ids_to_delete])
                    conn.commit()
                conn.close()
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
                await update.message.reply_text(f"✅ تم حذف {len(ids_to_delete)} كتاباً.", reply_markup=keyboard)
            else:
                await update.message.reply_text("⚠️ أرسل رقماً صحيحاً فقط (مثال: 50).")
        except Exception as e:
            print(f"❌ خطأ في حذف العدد: {e}")
            try:
                await update.message.reply_text(f"❌ حدث خطأ أثناء الحذف: {e}")
            except Exception:
                pass
        return

    # --- استقبال كلمة البحث الخام (من لوحة التحكم) ---
    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_raw_search'):
        context.user_data.pop('awaiting_raw_search', None)
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT book_name, msg_id, source_chat_id, dedup_key, part_number FROM archive "
                "WHERE book_name LIKE ? LIMIT 30", (f"%{text}%",)
            )
            raw_rows = cursor.fetchall()
            cursor.execute("SELECT COUNT(*) FROM archive WHERE book_name LIKE ?", (f"%{text}%",))
            total_matches = cursor.fetchone()[0]
            conn.close()

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
            if not raw_rows:
                await update.message.reply_text(f"🔎 لا توجد أي نتيجة تحتوي ('{text}') في القاعدة.", reply_markup=keyboard)
            else:
                lines = [f"🔎 نتائج ({text}) — الإجمالي: {total_matches}\n"]
                for book_name, msg_id, source_chat_id, dedup_key, part_number in raw_rows:
                    lines.append(
                        f"• {book_name}\n   msg_id: {msg_id} | المصدر: {source_chat_id} "
                        f"| dedup: {dedup_key} | جزء: {part_number}"
                    )
                msg_text = "\n".join(lines)
                if len(msg_text) > 3900:
                    msg_text = msg_text[:3900] + "\n\n... (تم الاقتصاص)"
                await update.message.reply_text(msg_text, reply_markup=keyboard)
        except Exception as e:
            print(f"❌ خطأ في البحث الخام: {e}")
            try:
                await update.message.reply_text(f"❌ حدث خطأ أثناء البحث: {e}")
            except Exception:
                pass
        return

    if text.startswith('/'):
        return

    if chat_type == 'private':
        if user_id not in ADMIN_IDS:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
            return
        clean_query = text

    elif chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return
        is_reply_to_bot = (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        mention_pattern = rf'@{re.escape(BOT_USERNAME)}'
        has_mention = bool(re.search(mention_pattern, text, re.IGNORECASE))
        if not (is_reply_to_bot or has_mention):
            return
        clean_query = re.sub(mention_pattern, '', text, flags=re.IGNORECASE).strip()
    else:
        return

    # البوت متوقف مؤقتاً من قِبل الأدمن — نصل هنا فقط لما الرسالة موجَّهة فعلاً
    # للبوت (خاص-أدمن، أو منشن/رد بالكروب)، فلا نُزعج بقية دردشة الكروب العادية
    if context.bot_data.get('bot_paused') and user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 البوت متوقف مؤقتاً حالياً من قِبل الإدارة، يرجى المحاولة لاحقاً.")
        return

    # --- رد ودّي على رسائل الشكر بدل معاملتها كطلب بحث فاشل (ومزعج للأدمن) ---
    if is_gratitude_message(clean_query):
        await update.message.reply_text(random.choice(GRATITUDE_REPLIES))
        return

    clean_query = strip_filler_phrases(clean_query)
    if not clean_query:
        clean_query = text
    norm_query = normalize_arabic(clean_query)

    if not norm_query or len(norm_query) < 2:
        if chat_type == 'private':
            await update.message.reply_text("⚠️ يرجى كتابة اسم كتاب أو كلمة بحث صالحة.")
        return

    try:
        keys, groups, norm_names, norm_names_no_ext, core_index = await asyncio.to_thread(get_search_index)

        matched_keys = await asyncio.to_thread(
            find_book_matches_indexed, norm_query, keys, norm_names, norm_names_no_ext, core_index
        )

        if not matched_keys:
            await update.message.reply_text(
                f"❌ عذراً، الاسم ('{clean_query}') غير موجود في أرشيف القناة.\n"
                f"تأكد من كتابة اسم الكتاب بشكل أقرب للعنوان الأصلي.\n"
                f"تم إبلاغ الأدمن بطلبك ليتم توفيره قريباً بإذن الله."
            )
            await notify_admins_not_found(context, update, clean_query)
            return

        # كل أجزاء الكتاب (إن وُجدت) مُجمَّعة سلفاً تحت نفس dedup_key ومرتبة حسب
        # part_number المخزَّن — لا حاجة لأي بحث إضافي عن "بقية الأجزاء" هنا.
        final_books = flatten_matched_keys(matched_keys, groups)
        await send_book_results(update, context, final_books)

    except Exception as e:
        print(f"❌ خطأ في search_and_forward: {e}")
        try:
            await update.message.reply_text(f"❌ حدث خطأ تقني أثناء البحث. حاول مجدداً.\n`{e}`", parse_mode="Markdown")
        except Exception:
            pass


# ==================== التشغيل ====================

def main():
    print("=" * 60)
    print("🔖 BOT_CODE_VERSION: 2026-08-21-v13-dedup-at-source")
    print("=" * 60)

    init_db()
    migrate_db()

    # concurrent_updates=True ضروري: بدونها تعالج المكتبة كل تحديث (رسالة أو ضغطة
    # زر) بالتسلسل، فأي ضغطة على "إيقاف الطلب" أو "إيقاف البوت" تبقى بالطابور ولا
    # تُنفَّذ إطلاقاً إلا بعد انتهاء عملية إرسال الكتب الجارية بالكامل — وهذا كان
    # سبب عدم استجابة الزرّين أثناء الإرسال.
    application = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(stop_request_callback, pattern="^stopreq_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    application.add_handler(MessageHandler(
        (filters.ChatType.GROUPS | filters.ChatType.CHANNEL) & (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
        handle_new_upload
    ))
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("json"),
        import_json_archive
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS),
        search_and_forward
    ))

    print("✅ البوت جاهز ويعمل...")
    application.run_polling()


if __name__ == "__main__":
    main()
