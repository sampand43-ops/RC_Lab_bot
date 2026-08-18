import os
import json
import sqlite3
import re
import asyncio
import difflib
import random
import urllib.request
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
            UNIQUE(msg_id, source_chat_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)
    conn.commit()
    conn.close()


def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(archive)")
    columns = [col[1] for col in cursor.fetchall()]
    if "source_chat_id" not in columns:
        cursor.execute(f"ALTER TABLE archive ADD COLUMN source_chat_id INTEGER DEFAULT {CHANNEL_ID}")
        conn.commit()
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
# لا نسمح بأرقام أطول لأنها غالباً معرّفات عشوائية (IDs) لا علاقة لها بترقيم الأجزاء،
# وقبولها كان يسبب تطابق كتب مختلفة تماماً بالخطأ بعد حذف "الرقم" من نهاية أسمائها.
TRAILING_NUM_PATTERN = re.compile(r'[\s\-_]([0-9٠-٩])\s*(?:\.pdf|\.epub|\.zip)?$')


def extract_part_number(filename):
    if not filename:
        return None
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
    """يحذف امتداد الملف فقط (.pdf مثلاً) دون لمس أي رقم أو نص آخر في الاسم.
    يُستخدم حصراً لحساب 'التطابق التام' الحقيقي، لأن ترك الامتداد ملتصقاً
    (كـ 'فن حرب pdf' بدل 'فن حرب') كان يمنع أي تطابق تام من الأساس،
    ويدفع كل طلب للاعتماد على مرحلة 'يبدأ بـ' الأوسع فيرسل كل الإصدارات المشابهة معاً."""
    if not filename:
        return ""
    return EXTENSION_ONLY_PATTERN.sub('', filename).strip()


AUTHOR_REQUEST_PATTERNS = [
    re.compile(r'^(?:اريد|أريد)\s+(?:كل|جميع)\s+(?:كتب|مؤلفات)\s+(.+)$'),
    re.compile(r'^(?:كل|جميع)\s+(?:كتب|مؤلفات)\s+(.+)$'),
]
FORBIDDEN_PREFIXES = ["صور من", "قصص من", "مختصر", "شرح"]


def dedupe_exact(records):
    seen = set()
    deduped = []
    for book_name, msg_id, source_chat_id in records:
        key = normalize_arabic(book_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((book_name, msg_id, source_chat_id))
    return deduped


def build_alternates_map(records):
    """يبني خريطة (اسم مُطبَّع -> كل النسخ الممكنة له) من نتائج غير مُنقّاة من التكرار،
    تُستخدم لإعادة المحاولة تلقائياً بنسخة بديلة إن فشلت النسخة الأساسية عند الإرسال
    (مثلاً: رسالة محذوفة من القناة، بينما نسخة أخرى بنفس الاسم لا تزال موجودة)."""
    alternates = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        key = normalize_arabic(book_name)
        alternates[key].append((msg_id, source_chat_id))
    return alternates


CORE_TITLE_SPLIT_PATTERN = re.compile(r'\s*[-–]\s+')


def get_core_title(raw_book_name):
    """يستخرج 'العنوان الجوهري' بحذف كل ما بعد أول شرطة (يليها مسافة)، ثم يحذف الامتداد،
    ثم يُطبِّع الناتج. يجب استدعاؤها على الاسم الخام (قبل normalize_arabic)، لأن التطبيع
    يحذف الشرطة نفسها فتفقد إمكانية العثور عليها.
    مثال: 'احببت وغدا - عماد رشاد.pdf' -> 'احببت وغدا'.
    يُستخدم فقط كطبقة احتياطية أخيرة لإعادة المحاولة عند الفشل — وليس للمطابقة
    الأساسية — حتى لا يختلط كتابان مختلفان فعلياً بنفس العنوان الأساسي (مثل
    'فن الحرب' و'فن الحرب - نيكولاس ميكيافيلي' اللذين يُعاملان كنسختين مختلفتين
    عمداً عند الاختيار الأول، لكن كبدائل إعادة محاولة أخيرة هذا مقبول)."""
    core_raw = CORE_TITLE_SPLIT_PATTERN.split(raw_book_name, maxsplit=1)[0].strip()
    core_raw = strip_extension_only(core_raw)
    return normalize_arabic(core_raw)


def build_core_alternates_map(records):
    """خريطة بدائل أوسع مبنية على العنوان الجوهري (بدون اسم المؤلف/الوصف الإضافي)،
    تُستخدم كطبقة أخيرة لإعادة المحاولة بعد استنفاد البدائل الدقيقة (نفس الاسم تماماً)."""
    alternates = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        core = get_core_title(book_name)
        alternates[core].append((msg_id, source_chat_id))
    return alternates


def group_into_series(records):
    groups = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        base_key = normalize_arabic(strip_part_pattern(book_name))
        groups[base_key].append((book_name, msg_id, source_chat_id))
    return groups


# ==================== فهرس البحث المُخزَّن مؤقتاً ====================

_search_index_cache = {"fingerprint": None, "records": [], "norm_names": [], "norm_names_no_ext": [], "index": {}}


def get_search_index():
    """يُرجع (records, norm_names, norm_names_no_ext, index)، ويعيد البناء تلقائياً فقط عند تغيّر الأرشيف.
    - norm_names: الاسم الكامل بعد التطبيع (بما فيه الامتداد كـ'pdf')، يُستخدم في مراحل
      'يبدأ بـ' و'كل الكلمات' و'التقريبي' — ثبت أنها آمنة وموثوقة (كالكود الأصلي المضمون).
    - norm_names_no_ext: نفس الاسم لكن بعد حذف الامتداد فقط (.pdf) دون لمس أي رقم،
      يُستخدم حصراً في مرحلة 'التطابق التام' — لأن ترك الامتداد كان يمنع أي تطابق تام
      من الأصل ويدفع كل طلب لمرحلة أوسع تُرسل كل الإصدارات المشابهة معاً بدل الدقيق منها."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM archive")
    fingerprint = cursor.fetchone()

    if _search_index_cache["fingerprint"] == fingerprint:
        conn.close()
        return (
            _search_index_cache["records"], _search_index_cache["norm_names"],
            _search_index_cache["norm_names_no_ext"], _search_index_cache["index"]
        )

    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive GROUP BY msg_id, source_chat_id")
    raw_records = cursor.fetchall()
    conn.close()

    norm_forbidden = [normalize_arabic(p) for p in FORBIDDEN_PREFIXES]

    records, norm_names, norm_names_no_ext = [], [], []
    index = defaultdict(set)

    for book_name, msg_id, source_chat_id in raw_records:
        norm_name = normalize_arabic(book_name)
        if any(norm_name.startswith(p) for p in norm_forbidden):
            continue

        i = len(records)
        records.append((book_name, msg_id, source_chat_id))
        norm_names.append(norm_name)
        norm_names_no_ext.append(normalize_arabic(strip_extension_only(book_name)))
        for w in get_words(norm_name):
            index[w].add(i)

    _search_index_cache.update(
        fingerprint=fingerprint, records=records, norm_names=norm_names,
        norm_names_no_ext=norm_names_no_ext, index=index
    )
    return records, norm_names, norm_names_no_ext, index


def find_book_matches_indexed(norm_query, records, norm_names, norm_names_no_ext, index):
    """
    بحث دقيق بأولويات صارمة:
    1) تطابق تام كامل للاسم (بعد حذف الامتداد فقط .pdf — وليس رقم الجزء)
    2) (كلمتان فأكثر) الاسم الكامل (بامتداده) يبدأ بنص الطلب بالكامل
    3) (كلمتان فأكثر) كل كلمات الطلب موجودة كاملة (عبر الفهرس)
    4) (كلمتان فأكثر، وكل كلمة 3 أحرف فأكثر) تطابق تقريبي صارم (85%+)
    """
    query_words = get_words(norm_query)

    exact = [records[i] for i, nn in enumerate(norm_names_no_ext) if nn == norm_query]
    if exact:
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE1(exact) -> {[r[0] for r in exact]}")
        return exact

    if len(query_words) < 2:
        print(f"🔎 SEARCH[{norm_query!r}] -> كلمة واحدة، لا تطابق تام -> فارغ")
        return []

    startswith_matches = [records[i] for i, nn in enumerate(norm_names) if nn.startswith(norm_query)]
    if startswith_matches:
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE2(startswith) -> {[r[0] for r in startswith_matches]}")
        return startswith_matches

    word_sets = [index.get(qw) for qw in query_words]
    if all(word_sets):
        common = set.intersection(*word_sets)
        if common:
            result = [records[i] for i in common]
            print(f"🔎 SEARCH[{norm_query!r}] -> STAGE3(all words) -> {[r[0] for r in result]}")
            return result

    if any(len(qw) < 3 for qw in query_words):
        print(f"🔎 SEARCH[{norm_query!r}] -> كلمة قصيرة موجودة، تشابه أكثر صرامة (90%)")
        cutoff = 0.9
    else:
        cutoff = 0.85

    vocabulary = list(index.keys())
    per_word_candidates = []
    for qw in query_words:
        # الكلمات القصيرة جداً (أقل من 3 أحرف) لا تخضع للتقريب إطلاقاً — يجب أن تُطابق بحروفها بالضبط
        # (منع مشاكل مثل مطابقة "فن" مع كلمات أخرى قصيرة غير مرتبطة إطلاقاً)
        if len(qw) < 3:
            if qw not in index:
                print(f"🔎 SEARCH[{norm_query!r}] -> كلمة قصيرة '{qw}' غير موجودة حرفياً -> فارغ")
                return []
            word_candidates = set(index[qw])
        else:
            close_words = difflib.get_close_matches(qw, vocabulary, n=5, cutoff=cutoff)
            if not close_words:
                print(f"🔎 SEARCH[{norm_query!r}] -> لا تشابه لكلمة '{qw}' -> فارغ")
                return []
            word_candidates = set()
            for w in close_words:
                word_candidates |= index.get(w, set())
        per_word_candidates.append(word_candidates)

    common = set.intersection(*per_word_candidates) if per_word_candidates else set()
    result = [records[i] for i in common]
    print(f"🔎 SEARCH[{norm_query!r}] -> STAGE4(تقريبي) -> {[r[0] for r in result]}")
    return result


# ==================== معالجات الكروبات ====================

async def is_allowed_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        if is_group_approved(chat.id):
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
    if chat.id != CHANNEL_ID and not is_group_approved(chat.id):
        return

    document = message.document or message.video or message.audio
    if not document:
        return

    book_name = document.file_name or message.caption or f"Book_{message.message_id}"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)",
            (book_name, message.message_id, chat.id)
        )
        conn.commit()
        print(f"✅ أُرشف تلقائياً: '{book_name}' (msg_id={message.message_id}, chat={chat.id})")
    except sqlite3.IntegrityError:
        print(f"ℹ️ الكتاب '{book_name}' مؤرشف مسبقاً بنفس رقم الرسالة، تم التجاهل.")
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

    caption = update.message.caption
    try:
        source_chat_id = int(caption.strip()) if caption else CHANNEL_ID
    except ValueError:
        source_chat_id = CHANNEL_ID

    status_msg = await update.message.reply_text(
        f"🚀 جاري تحليل ملف التصدير (المصدر: `{source_chat_id}`)...", parse_mode="Markdown"
    )

    try:
        file = await context.bot.get_file(document.file_id)
        json_path = os.path.join(DATA_DIR, f"temp_export_{update.message.message_id}.json")
        await file.download_to_drive(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

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

        for msg in messages:
            processed += 1
            if msg.get("file") or msg.get("media_type"):
                msg_id = msg.get("id")
                if msg_id is not None:
                    book_name = extract_book_name(msg) or f"Book_{msg_id}"
                    batch.append((book_name, msg_id, source_chat_id))

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(
                    "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)", batch
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
                "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)", batch
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

def build_admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات الأرشيف", callback_data="admin_stats")],
        [InlineKeyboardButton("📄 تصدير أسماء الكتب (PDF)", callback_data="admin_export_pdf")],
        [InlineKeyboardButton("🔎 بحث خام (تشخيص)", callback_data="admin_raw_search")],
        [InlineKeyboardButton("🔢 حذف آخر عدد من الكتب", callback_data="admin_delete_count")],
        [InlineKeyboardButton("🗑️ حذف كامل الأرشيف", callback_data="admin_clear_all")],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
        parse_mode="Markdown", reply_markup=build_admin_panel_keyboard()
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
        """يجهّز النص للعرض العربي، ويزيل أي أحرف تحكّم خفية قد يرفضها الخط،
        ويتراجع تلقائياً للنص الخام إن فشلت المعالجة بالكامل لأي سبب."""
        if not font_available:
            return raw_text
        try:
            shaped = get_display(arabic_reshaper.reshape(raw_text))
            # إزالة أي أحرف تحكّم يونيكود خفية (فئة Cf) لا يملك الخط رمزاً مرئياً لها
            cleaned = ''.join(ch for ch in shaped if unicodedata.category(ch) != 'Cf')
            return cleaned
        except Exception:
            # كحل أخير: احذف أي حرف خارج النطاق الأساسي بدل إسقاط السطر بالكامل
            return ''.join(ch for ch in raw_text if ord(ch) < 0x10000)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive ORDER BY book_name COLLATE NOCASE")
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
            # سطر واحد فشل بسبب رمز غريب في اسم الملف — تخطَّه ولا توقف العملية كلها
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
        cursor.execute("SELECT COUNT(*) FROM archive")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT source_chat_id, COUNT(*) FROM archive GROUP BY source_chat_id ORDER BY COUNT(*) DESC")
        by_source = cursor.fetchall()
        conn.close()

        text = f"📊 *إحصائيات الأرشيف*\n\nإجمالي الكتب: `{total}`\n\n*حسب المصدر:*\n"
        for chat_id, count in by_source:
            label = "📚 القناة الرئيسية" if chat_id == CHANNEL_ID else f"👥 كروب ({chat_id})"
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
            parse_mode="Markdown", reply_markup=build_admin_panel_keyboard()
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
            "(SQL LIKE بدون أي منطق ذكي) لأريك النتائج كما هي مخزّنة فعلياً.",
            parse_mode="Markdown", reply_markup=keyboard
        )

    elif data == "admin_back":
        context.user_data.pop('awaiting_delete_count', None)
        context.user_data.pop('awaiting_raw_search', None)
        await query.edit_message_text(
            "⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
            parse_mode="Markdown", reply_markup=build_admin_panel_keyboard()
        )


# ==================== الإرسال والبحث ====================

THANK_YOU_MESSAGES = [
    "📚 تفضّل، أتمنى لك قراءة ممتعة! سعداء دائماً بخدمتك في مجتمع القراءة 🌿",
    "✨ تم إرسال طلبك، استمتع بالقراءة! نورت مجتمع القراءة 📖",
    "🌟 تفضّل كتابك، وبالعافية عليك القراءة! نحن هنا دائماً لأجلك 💚",
    "📖 وصلك الكتاب، قراءة ممتعة إن شاء الله! أهلاً بك دائماً في مجتمعنا 🌸",
]


async def send_book_results(update, context, valid_books, alternates_map=None, core_alternates_map=None):
    """يحوّل الكتب من مصدرها (تظهر 'محوّلة من القناة/الكروب' كما طُلب).
    عند فشل الإرسال، يحاول تلقائياً بنسخ بديلة (بنفس الاسم تماماً أولاً، ثم بنفس
    العنوان الجوهري كطبقة أخيرة) قبل الاستسلام. يُرسل رسالة ودّية بعد النجاح،
    ويُبلغ الأدمن فوراً بأي كتاب تعذّر توفيره."""
    alternates_map = alternates_map or {}
    core_alternates_map = core_alternates_map or {}
    succeeded, failed = [], []

    for book_name, msg_id, source_chat_id in valid_books:
        key = normalize_arabic(book_name)
        core_key = get_core_title(key)

        candidates = [(msg_id, source_chat_id)]
        for alt_msg_id, alt_source in alternates_map.get(key, []):
            if (alt_msg_id, alt_source) not in candidates:
                candidates.append((alt_msg_id, alt_source))
        for alt_msg_id, alt_source in core_alternates_map.get(core_key, []):
            if (alt_msg_id, alt_source) not in candidates:
                candidates.append((alt_msg_id, alt_source))

        last_error = None
        sent = False
        for attempt_msg_id, attempt_source in candidates:
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=attempt_source,
                    message_id=attempt_msg_id
                )
                succeeded.append(book_name)
                sent = True
                await asyncio.sleep(0.4)
                break
            except Exception as e:
                last_error = e
                print(f"⚠️ محاولة فاشلة لـ '{book_name}' (msg_id={attempt_msg_id}, source={attempt_source}): {e}")

        if not sent:
            failed.append((book_name, msg_id, str(last_error)))

    # رسالة ودّية بعد نجاح إرسال كتاب واحد على الأقل
    if succeeded:
        try:
            await update.message.reply_text(random.choice(THANK_YOU_MESSAGES))
        except Exception:
            pass

    if failed:
        chat_type = update.effective_chat.type
        requester_user_id = update.effective_user.id

        # إبلاغ فوري لكل الأدمنية بأي كتاب تعذّر توفيره، أياً كان مصدر الطلب
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
            # لم ينجح أي كتاب إطلاقاً — يجب أن يعرف طالب الكتاب أن هناك خطأ فعلياً
            await update.message.reply_text(
                "⚠️ الكتاب موجود في الأرشيف لكن تعذّر توفيره فعلياً حالياً (قد يكون حُذف من مصدره). "
                "تم إبلاغ الأدمن فوراً وسيُعاد توفيره قريباً بإذن الله."
            )

    return succeeded, failed


async def notify_admins_not_found(context, update, query_text):
    """يُبلغ كل الأدمنية فوراً باسم الكتاب الذي لم يُعثر عليه، ومصدر الطلب وطالبه"""
    chat_type = update.effective_chat.type
    requester_name = update.effective_user.full_name or str(update.effective_user.id)
    chat_label = "الخاص" if chat_type == 'private' else (update.effective_chat.title or str(update.effective_chat.id))
    message = f"🔍 طلب كتاب غير متوفر:\n• الطلب: {query_text}\n• من: {chat_label}\n• بواسطة: {requester_name}"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, message)
        except Exception as e:
            print(f"❌ تعذّر إبلاغ الأدمن {admin_id} بكتاب غير موجود: {e}")


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
            cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive WHERE book_name LIKE ? LIMIT 30", (f"%{text}%",))
            raw_rows = cursor.fetchall()
            cursor.execute("SELECT COUNT(*) FROM archive WHERE book_name LIKE ?", (f"%{text}%",))
            total_matches = cursor.fetchone()[0]
            conn.close()

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
            if not raw_rows:
                # بدون parse_mode إطلاقاً هنا: النص المُدخل من المستخدم قد يحتوي رموز Markdown خاصة
                await update.message.reply_text(f"🔎 لا توجد أي نتيجة تحتوي ('{text}') في القاعدة.", reply_markup=keyboard)
            else:
                # بدون Markdown نهائياً: أسماء الملفات الحقيقية شبه دائماً تحتوي على _  * [ ] وغيرها
                # مما يكسر تنسيق Markdown ويجعل تيليجرام يرفض الرسالة بالكامل بصمت
                lines = [f"🔎 نتائج ({text}) — الإجمالي: {total_matches}\n"]
                for book_name, msg_id, source_chat_id in raw_rows:
                    lines.append(f"• {book_name}\n   msg_id: {msg_id} | المصدر: {source_chat_id}")
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

    # --- استثناء "أريد كل/جميع كتب [الكاتب]" ---
    is_author_request, author_query = False, None
    for pattern in AUTHOR_REQUEST_PATTERNS:
        m = pattern.match(clean_query.strip())
        if m:
            is_author_request, author_query = True, m.group(1).strip()
            break

    if is_author_request and author_query:
        norm_query = normalize_arabic(author_query)
    else:
        phrases_to_remove = sorted([
            "اريد كتاب", "أريد كتاب","ابغى","ابغى كتاب","ابغى رواية"
            , "ممكن","ممكن كتاب","ممكن رواية","احتاج","احتاج كتاب","احتاج رواية","الاقي","الاقي كتاب","الاقي رواية","عايزة"
            ,"عايزة كتاب","عايزة رواية","عايز","عايز كتاب","عايز رواية","عاوزة","عاوزة كتاب"
            ,"عاوزة رواية","عاوز","عاوز كتاب","عاوز رواية", "اريد كتاب ال", "أريد كتاب ال",
            "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب",
            "اريد", "أريد", "كتاب", "رواية"
        ], key=len, reverse=True)
        for phrase in phrases_to_remove:
            if clean_query.startswith(phrase):
                clean_query = clean_query[len(phrase):].strip()
                break
        if not clean_query:
            clean_query = text
        norm_query = normalize_arabic(clean_query)

    if not norm_query or len(norm_query) < 2:
        if chat_type == 'private':
            await update.message.reply_text("⚠️ يرجى كتابة اسم كتاب أو كلمة بحث صالحة.")
        return

    try:
        records, norm_names, norm_names_no_ext, index = await asyncio.to_thread(get_search_index)

        if is_author_request:
            results = [records[i] for i, nn in enumerate(norm_names) if norm_query in nn]
            if not results:
                await update.message.reply_text(f"❌ لم يتم العثور على أي كتب باسم الكاتب ('{author_query}').")
                await notify_admins_not_found(context, update, f"كل كتب: {author_query}")
                return
            alternates_map = build_alternates_map(results)
            core_alternates_map = build_core_alternates_map(results)
            await send_book_results(update, context, dedupe_exact(results), alternates_map, core_alternates_map)
            return

        results = await asyncio.to_thread(
            find_book_matches_indexed, norm_query, records, norm_names, norm_names_no_ext, index
        )

        if not results:
            await update.message.reply_text(
                f"❌ عذراً، الاسم ('{clean_query}') غير موجود في أرشيف القناة.\n"
                f"تأكد من كتابة اسم الكتاب بشكل أقرب للعنوان الأصلي.\n"
                f"تم إبلاغ الأدمن بطلبك ليتم توفيره قريباً بإذن الله."
            )
            await notify_admins_not_found(context, update, clean_query)
            return

        # خريطتا النسخ البديلة (قبل حذف التكرار) — تُستخدمان لإعادة المحاولة تلقائياً
        # إن فشل إرسال نسخة معيّنة (مثلاً: رسالتها محذوفة من القناة):
        # 1) بدائل بنفس الاسم تماماً أولاً
        # 2) ثم كطبقة أخيرة: بدائل بنفس 'العنوان الجوهري' حتى لو اختلف اسم المؤلف/الوصف المرفق
        alternates_map = build_alternates_map(results)
        core_alternates_map = build_core_alternates_map(results)

        deduped = dedupe_exact(results)
        groups = group_into_series(deduped)

        final_books = []
        for base_key, items in groups.items():
            distinct_parts = {extract_part_number(b) for b, _, _ in items if extract_part_number(b) is not None}
            if len(distinct_parts) >= 2:
                sorted_items = sorted(items, key=lambda x: (extract_part_number(x[0]) is None, extract_part_number(x[0]) or 0))
                # إزالة تكرار رقم الجزء نفسه (مثال: جزء 1 مرفوع مرتين بصيغتين مختلفتين قليلاً)
                # نُبقي أول نسخة فقط لكل رقم جزء فريد
                seen_parts = set()
                unique_parts = []
                for item in sorted_items:
                    part_num = extract_part_number(item[0])
                    if part_num in seen_parts:
                        continue
                    seen_parts.add(part_num)
                    unique_parts.append(item)
                final_books.extend(unique_parts)
            else:
                final_books.append(items[0])

        await send_book_results(update, context, final_books, alternates_map, core_alternates_map)

    except Exception as e:
        print(f"❌ خطأ في search_and_forward: {e}")
        try:
            await update.message.reply_text(f"❌ حدث خطأ تقني أثناء البحث. حاول مجدداً.\n`{e}`", parse_mode="Markdown")
        except Exception:
            pass


# ==================== التشغيل ====================

def main():
    print("=" * 60)
    print("🔖 BOT_CODE_VERSION: 2026-08-17-v6-flexible-search-admin-alerts")
    print("=" * 60)

    init_db()
    migrate_db()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    application.add_handler(MessageHandler(
        (filters.ChatType.CHANNEL | filters.ChatType.GROUPS) & (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
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
