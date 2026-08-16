import os
import json
import sqlite3
import re
import asyncio
import difflib
import urllib.request
import traceback
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
from pyrogram import Client as PyroClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

# مسار التخزين الدائم على Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

# الخط العربي المطلوب لتصدير قائمة الكتب كـ PDF — يُحمَّل تلقائياً عند أول استخدام
# ويُحفظ على القرص الدائم، لا حاجة لرفع أي ملف خط يدوياً للمستودع
FONT_PATH = os.path.join(DATA_DIR, "NotoNaskhArabic-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notonaskharabic/NotoNaskhArabic%5Bwght%5D.ttf"
_font_registered = False


def ensure_arabic_font():
    """يحمّل الخط العربي عند الحاجة (مرة واحدة فقط) ويسجّله لدى reportlab"""
    global _font_registered
    if _font_registered:
        return True
    try:
        if not os.path.exists(FONT_PATH):
            urllib.request.urlretrieve(FONT_URL, FONT_PATH)
        pdfmetrics.registerFont(TTFont("Arabic", FONT_PATH))
        _font_registered = True
        return True
    except Exception as e:
        print(f"⚠️ تعذّر تحميل/تسجيل الخط العربي: {e}")
        return False


TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

# علامة إصدار الكود — تظهر في /panel وفي رسائل الأرشفة، للتأكد القاطع من نشر آخر نسخة فعلياً
CODE_VERSION = "v4-indexed-search-2026-08-15"

# بيانات API لحساب المستخدم (Userbot) المستخدم في البحث الحي داخل القناة
API_ID = 34123643
API_HASH = "12dccc6e1dce1c82853587ba04e9694d"
USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING")  # يُضاف كمتغير بيئة سري في Railway

# معرف قناتك الثابت (يُستخدم كافتراضي عند عدم تحديد مصدر آخر)
CHANNEL_ID = -1004395670008

# قائمة مشرفي البوت المصرح لهم حصراً بإضافته للمجموعات وبالأرشفة اليدوية
ADMIN_IDS = [7898871921, 1937491557]

# معرف البوت وبيانات المجموعة الرئيسية
BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

# عميل حساب المستخدم (Userbot) للبحث الحي داخل القناة — يُهيَّأ فقط إن وُجد USER_SESSION_STRING
user_client = None
if USER_SESSION_STRING:
    user_client = PyroClient(
        "user_search_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=USER_SESSION_STRING,
        in_memory=True,  # لا حاجة لحفظ ملف جلسة على القرص
    )

# النصوص
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
    "💡 للحصول على دليل التعليمات وتقسيم الصلاحيات التفصيلي، أرسل الأمر: /help\n\n"
    "البوت قيد التشغيل وجاهز لخدمتك ✨"
)

ADMIN_HELP_TEXT = (
    "📌 *دليل استخدام البوت وتقسيم الصلاحيات*\n\n"
    "━━━━━━ 👑 *صلاحيات المشرف* ━━━━━━\n\n"
    "• *تفعيل المجموعات:* يمكنك إضافة البوت لأي مجموعة جديدة لتفعيلها تلقائياً واستخدامها من قِبل الأعضاء.\n\n"
    "• *الأرشفة التاريخية (JSON):* صدّر سجل القناة أو الكروب من Telegram Desktop (Export chat history → JSON)، ثم أرسل ملف `result.json` للبوت في الخاص، مع كتابة معرّف المحادثة (chat_id) كتعليق على الملف. سيقوم البوت بأرشفة كل الكتب الموجودة فيه دفعة واحدة، حتى القديمة منها.\n\n"
    "• *الأرشفة الآلية:* بمجرد رفع أي ملف جديد في القناة أو أي كروب معتمد، يتم حفظه وفهرسته في قاعدة البيانات فوراً.\n\n"
    "• *لوحة تحكم الأرشيف:* أرسل الأمر `/panel` للحصول على أزرار تحكم تفاعلية (إحصائيات الأرشيف، حذف آخر عدد من الكتب، أو حذف الأرشيف بالكامل).\n\n"
    "• *البحث الحر في الخاص:* يمكنك البحث واستخراج أي كتاب مباشرة من محادثة البوت الخاصة دون أي قيود.\n\n"
    "━━━━━━ 👥 *صلاحيات وإرشادات الأعضاء* ━━━━━━\n\n"
    "• *الاستخدام المقيّد:* يقتصر استخدام الأعضاء للبوت على المجموعات المعتمدة التي قمت بتفعيلها فقط.\n\n"
    "• *طرق البحث المتاحة:* يمكن للعضو البحث داخل المجموعة عن طريق:\n"
    "  1️⃣ الإشارة للبوت: `@RCGivvvv_bot اسم الكتاب`\n"
    "  2️⃣ أو عمل رد (Reply) على أي رسالة للبوت بكتابة اسم الكتاب.\n\n"
    "• *المنع التلقائي:* لا يمكن للأعضاء استخدام البوت في المحادثات الخاصة أو إضافته لمجموعات خارجية، وسيقوم البوت باعتذار ومغادرة تلقائية."
)


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
    """يضيف عمود source_chat_id إذا كانت قاعدة البيانات من نسخة قديمة لا تحتويه"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(archive)")
    columns = [col[1] for col in cursor.fetchall()]
    if "source_chat_id" not in columns:
        cursor.execute(
            f"ALTER TABLE archive ADD COLUMN source_chat_id INTEGER DEFAULT {CHANNEL_ID}"
        )
        conn.commit()
    conn.close()


def is_group_approved(chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM allowed_groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)


async def is_allowed_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        if is_group_approved(chat.id):
            return True
        else:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=LEAVE_TEXT,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
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
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text="أهلاً بكم! 📚🤖\nتم تفعيل البوت بنجاح لهذه المجموعة بواسطة المشرف."
                    )
                except Exception:
                    pass
            else:
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=LEAVE_TEXT,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
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


# --- أرشفة تلقائية لأي ملف جديد يُرفع في القناة أو أي كروب معتمد ---
async def handle_new_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.message
    if not message:
        return

    chat = update.effective_chat
    if chat is None:
        return

    # اسمح فقط بالقناة الرئيسية أو الكروبات المعتمدة مسبقاً
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
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


# --- استيراد أرشيف تاريخي من ملف result.json المُصدَّر عبر Telegram Desktop ---
async def import_json_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type != 'private' or user_id not in ADMIN_IDS:
        return

    document = update.message.document
    if not document or not document.file_name.endswith('.json'):
        return

    # حدد مصدر الرسائل عبر التعليق (caption) المرفق مع الملف، وإلا استخدم القناة كافتراضي
    caption = update.message.caption
    try:
        source_chat_id = int(caption.strip()) if caption else CHANNEL_ID
    except ValueError:
        source_chat_id = CHANNEL_ID

    status_msg = await update.message.reply_text(
        f"🚀 جاري تحليل ملف التصدير وأرشفة الملفات (المصدر: `{source_chat_id}`)...",
        parse_mode="Markdown"
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
        # تسريع الكتابة على القرص أثناء الاستيراد الضخم
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")

        batch = []
        BATCH_SIZE = 2000
        inserted_total = 0
        processed = 0
        last_reported_percent = -1

        def extract_book_name(msg):
            book_name = msg.get("file_name")
            if not book_name:
                text_field = msg.get("text")
                if isinstance(text_field, list):
                    book_name = "".join(
                        part if isinstance(part, str) else part.get("text", "")
                        for part in text_field
                    ).strip()
                elif isinstance(text_field, str):
                    book_name = text_field.strip()
            return book_name

        for msg in messages:
            processed += 1

            # نتجاهل أي رسالة لا تحتوي ملفاً مرفقاً
            if msg.get("file") or msg.get("media_type"):
                msg_id = msg.get("id")
                if msg_id is not None:
                    book_name = extract_book_name(msg) or f"Book_{msg_id}"
                    batch.append((book_name, msg_id, source_chat_id))

            if len(batch) >= BATCH_SIZE:
                cursor.executemany(
                    "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)",
                    batch
                )
                inserted_total += cursor.rowcount if cursor.rowcount != -1 else len(batch)
                conn.commit()
                batch.clear()

            # تحديث تقرير التقدّم كل 10% لتفادي إغراق تيليجرام بالتعديلات
            percent = int((processed / total_msgs) * 100) if total_msgs else 100
            if percent >= last_reported_percent + 10:
                last_reported_percent = percent
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري الأرشفة... {percent}% ({processed}/{total_msgs})"
                    )
                except Exception:
                    pass  # تجاهل أخطاء تعديل الرسالة (مثل: نفس المحتوى)

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)",
                batch
            )
            conn.commit()

        # عدد السجلات الفعلي المضاف = الفرق قبل وبعد (أدق من الاعتماد على rowcount مع OR IGNORE)
        cursor.execute("SELECT COUNT(*) FROM archive WHERE source_chat_id = ?", (source_chat_id,))
        final_count = cursor.fetchone()[0]

        conn.close()
        os.remove(json_path)

        await status_msg.edit_text(
            f"✅ تمت الأرشفة بنجاح! (إصدار الكود: `{CODE_VERSION}`)\n"
            f"عدد الرسائل المفحوصة في هذا الملف: `{total_msgs}`\n"
            f"إجمالي الكتب المؤرشفة الآن لهذا المصدر: `{final_count}`\n\n"
            f"💡 إذا كان لديك أجزاء أخرى من نفس المكتبة، أرسلها الآن واحداً تلو الآخر."
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة:\n`{e}`", parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(
                ADMIN_WELCOME_TEXT,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    else:
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ إشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل (رد/Reply) على أي رسالة للبوت وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ إشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل (رد/Reply) على أي رسالة للبوت وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )
    elif chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(
                ADMIN_HELP_TEXT,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )


ARABIC_NUM_WORDS = {
    'الأول': 1, 'اول': 1, '1': 1,
    'الثاني': 2, 'ثاني': 2, '2': 2,
    'الثالث': 3, 'ثالث': 3, '3': 3,
    'الرابع': 4, 'رابع': 4, '4': 4,
    'الخامس': 5, 'خامس': 5, '5': 5,
    'السادس': 6, 'سادس': 6, '6': 6,
    'السابع': 7, 'سابع': 7, '7': 7,
    'الثامن': 8, 'ثامن': 8, '8': 8,
    'التاسع': 9, 'تاسع': 9, '9': 9,
    'العاشر': 10, 'عاشر': 10, '10': 10,
}


PART_PATTERN = re.compile(
    r'(الجزء|المجلد|جـ?|مجلد|part|vol)\s*([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)',
    re.IGNORECASE
)
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

    return None  # لا يوجد رقم جزء/مجلد في الاسم


def strip_part_pattern(filename):
    """يزيل إشارة الجزء/المجلد من الاسم للحصول على 'الاسم الأساسي' للسلسلة"""
    if not filename:
        return ""
    stripped = PART_PATTERN.sub('', filename)
    stripped = TRAILING_NUM_PATTERN.sub('', stripped)
    stripped = re.sub(r'\.(pdf|epub|zip|mobi|docx?)$', '', stripped, flags=re.IGNORECASE)
    return stripped.strip()


def strip_al(word):
    """يوحّد الكلمات بإزالة (ال) التعريف من بدايتها، مثل: الشرقاوي -> شرقاوي"""
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
    """يُرجع الكلمات ذات الدلالة فقط (يتجاهل الكلمات القصيرة جداً مثل حروف الجر)"""
    return [w for w in normalized_text.split() if len(w) >= 2]


# أنماط استثناء طلب "كل كتب فلان" — تُرجع اسم الكاتب المستخرج إن وُجدت المطابقة
AUTHOR_REQUEST_PATTERNS = [
    re.compile(r'^(?:اريد|أريد)\s+(?:كل|جميع)\s+كتب\s+(.+)$'),
    re.compile(r'^(?:كل|جميع)\s+كتب\s+(.+)$'),
]

FORBIDDEN_PREFIXES = ["صور من", "قصص من", "مختصر", "شرح"]


def dedupe_exact(records):
    """يحذف أي تكرار حرفي لنفس اسم الكتاب (نفس المحتوى بالضبط)، يبقي أول نسخة فقط"""
    seen = set()
    deduped = []
    for book_name, msg_id, source_chat_id in records:
        key = normalize_arabic(book_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((book_name, msg_id, source_chat_id))
    return deduped


def group_into_series(records):
    """يجمع السجلات حسب 'الاسم الأساسي' (بدون رقم الجزء) لتمييز أجزاء نفس الكتاب"""
    groups = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        base_key = normalize_arabic(strip_part_pattern(book_name))
        groups[base_key].append((book_name, msg_id, source_chat_id))
    return groups


# ==================== فهرس البحث المُخزَّن مؤقتاً (Search Index Cache) ====================
# بدل مسح كامل الأرشيف (قد يصل لمئات الآلاف من الكتب) مع كل رسالة بحث، نبني فهرساً
# مرة واحدة فقط ونعيد استخدامه، ونعيد بناءه تلقائياً فقط عند تغيّر الأرشيف فعلياً.
_search_index_cache = {"fingerprint": None, "records": [], "base_keys": [], "index": {}}


def get_search_index():
    """يُرجع (records, base_keys, index) من الذاكرة المؤقتة، ويعيد البناء فقط عند تغيّر الأرشيف"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM archive")
    fingerprint = cursor.fetchone()

    if _search_index_cache["fingerprint"] == fingerprint:
        conn.close()
        return _search_index_cache["records"], _search_index_cache["base_keys"], _search_index_cache["index"]

    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive GROUP BY msg_id, source_chat_id")
    raw_records = cursor.fetchall()
    conn.close()

    norm_forbidden = [normalize_arabic(p) for p in FORBIDDEN_PREFIXES]

    records = []
    base_keys = []
    index = defaultdict(set)

    for book_name, msg_id, source_chat_id in raw_records:
        norm_name = normalize_arabic(book_name)
        if any(norm_name.startswith(p) for p in norm_forbidden):
            continue  # استبعاد نهائي للبادئات غير المرغوبة (صور من، مختصر...)

        base_key = normalize_arabic(strip_part_pattern(book_name))
        i = len(records)
        records.append((book_name, msg_id, source_chat_id))
        base_keys.append(base_key)
        for w in get_words(base_key):
            index[w].add(i)

    _search_index_cache["fingerprint"] = fingerprint
    _search_index_cache["records"] = records
    _search_index_cache["base_keys"] = base_keys
    _search_index_cache["index"] = index

    return records, base_keys, index


def find_book_matches_indexed(norm_query, records, base_keys, index):
    """
    بحث دقيق وسريع (يعتمد على فهرس مبني مسبقاً بدل مسح كل السجلات):
    1) تطابق تام كامل للاسم (بعد حذف الامتداد ورقم الجزء)
    2) (فقط للطلبات متعددة الكلمات) الاسم يبدأ بنص الطلب بالكامل
    3) (فقط للطلبات متعددة الكلمات) كل كلمات الطلب موجودة كاملة — عبر الفهرس مباشرة (سريع جداً)
    4) (فقط للطلبات متعددة الكلمات، وكل كلمة 3 أحرف فأكثر) تطابق تقريبي صارم (تشابه 85%+)
    الطلبات المكوّنة من كلمة واحدة فقط تُقبل حصراً عند التطابق التام.
    """
    query_words = get_words(norm_query)

    # 1) تطابق تام
    exact = [records[i] for i, bk in enumerate(base_keys) if bk == norm_query]
    if exact:
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE 1 (exact) -> {[r[0] for r in exact]}")
        return exact

    if len(query_words) < 2:
        print(f"🔎 SEARCH[{norm_query!r}] -> كلمة واحدة بدون تطابق تام -> لا نتائج")
        return []

    # 2) الاسم يبدأ بنص الطلب بالكامل (مقارنة نصية بسيطة، سريعة حتى مع مئات الآلاف من السجلات)
    startswith_matches = [records[i] for i, bk in enumerate(base_keys) if bk.startswith(norm_query)]
    if startswith_matches:
        print(f"🔎 SEARCH[{norm_query!r}] -> STAGE 2 (startswith) -> {[r[0] for r in startswith_matches]}")
        return startswith_matches

    # 3) كل كلمات الطلب موجودة كاملة — عبر تقاطع مجموعات الفهرس مباشرة (O(1) لكل كلمة تقريباً)
    word_sets = [index.get(qw) for qw in query_words]
    if all(word_sets):
        common = set.intersection(*word_sets)
        if common:
            result = [records[i] for i in common]
            print(f"🔎 SEARCH[{norm_query!r}] -> STAGE 3 (كل الكلمات موجودة) -> {[r[0] for r in result]}")
            return result

    # 4) تطابق تقريبي صارم — يُستبعد تماماً إن كانت أي كلمة من الطلب أقصر من 3 أحرف
    # (كلمات قصيرة مثل "فن" خطيرة جداً في المطابقة التقريبية وتسبب نتائج غير منطقية)
    if any(len(qw) < 3 for qw in query_words):
        print(f"🔎 SEARCH[{norm_query!r}] -> تجاهل المرحلة التقريبية (كلمة قصيرة جداً) -> لا نتائج")
        return []

    vocabulary = list(index.keys())
    per_word_candidates = []
    for qw in query_words:
        close_words = difflib.get_close_matches(qw, vocabulary, n=5, cutoff=0.85)
        if not close_words:
            print(f"🔎 SEARCH[{norm_query!r}] -> STAGE 4: لا تشابه كافٍ للكلمة '{qw}' -> لا نتائج")
            return []
        word_candidates = set()
        for w in close_words:
            word_candidates |= index.get(w, set())
        per_word_candidates.append(word_candidates)

    common = set.intersection(*per_word_candidates) if per_word_candidates else set()
    result = [records[i] for i in common]
    print(f"🔎 SEARCH[{norm_query!r}] -> STAGE 4 (تقريبي صارم) -> {[r[0] for r in result]}")
    return result


def build_admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات الأرشيف", callback_data="admin_stats")],
        [InlineKeyboardButton("📄 تصدير أسماء الكتب (PDF)", callback_data="admin_export_pdf")],
        [InlineKeyboardButton("🔎 بحث خام (تشخيص)", callback_data="admin_raw_search")],
        [InlineKeyboardButton("🔢 حذف آخر عدد من الكتب", callback_data="admin_delete_count")],
        [InlineKeyboardButton("🗑️ حذف كامل الأرشيف", callback_data="admin_clear_all")],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض لوحة تحكم تفاعلية للأدمن لإدارة الأرشيف (إحصائيات، حذف)"""
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return

    await update.message.reply_text(
        "⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
        parse_mode="Markdown",
        reply_markup=build_admin_panel_keyboard()
    )


def generate_archive_pdf(output_path):
    """
    يُولّد ملف PDF يحتوي على كل أسماء الكتب المؤرشفة حالياً (اسم الكتاب + رقم الرسالة + المصدر)،
    مرتبة أبجدياً، لأغراض المراجعة والتشخيص.
    """
    font_available = ensure_arabic_font()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT book_name, msg_id, source_chat_id FROM archive ORDER BY book_name COLLATE NOCASE"
    )
    rows = cursor.fetchall()
    conn.close()

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    font_name = "Arabic" if font_available else "Helvetica"
    font_size = 11
    line_height = 16
    margin_top = 40
    margin_bottom = 40
    y = height - margin_top

    c.setFont(font_name, 14)
    title = f"فهرس أرشيف الكتب — إجمالي: {len(rows)} كتاباً"
    if font_available:
        title = get_display(arabic_reshaper.reshape(title))
    c.drawRightString(width - 40, y, title)
    y -= line_height * 2

    c.setFont(font_name, font_size)
    for index, (book_name, msg_id, source_chat_id) in enumerate(rows, start=1):
        line = f"{index}. {book_name}  [msg_id: {msg_id}]"
        if font_available:
            line = get_display(arabic_reshaper.reshape(line))

        c.drawRightString(width - 40, y, line)
        y -= line_height

        if y < margin_bottom:
            c.showPage()
            c.setFont(font_name, font_size)
            y = height - margin_top

    c.save()
    return len(rows)


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل ضغطات أزرار لوحة تحكم الأدمن"""
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
        cursor.execute(
            "SELECT source_chat_id, COUNT(*) FROM archive GROUP BY source_chat_id ORDER BY COUNT(*) DESC"
        )
        by_source = cursor.fetchall()
        conn.close()

        text = f"📊 *إحصائيات الأرشيف*\n\nإصدار الكود: `{CODE_VERSION}`\nإجمالي الكتب المؤرشفة: `{total}`\n\n*حسب المصدر:*\n"
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
            "⚠️ *تأكيد الحذف الكامل*\n\n"
            "سيتم حذف *كامل فهرس الأرشيف المحلي* نهائياً (أسماء الكتب وأرقام رسائلها فقط).\n"
            "لن يتأثر أي ملف فعلي داخل القناة أو الكروبات — الملفات تبقى كما هي.\n\n"
            "هذا الإجراء *لا يمكن التراجع عنه*. هل أنت متأكد؟",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif data == "admin_clear_all_confirm":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        await query.edit_message_text(
            "✅ تم حذف كامل فهرس الأرشيف بنجاح.",
            reply_markup=keyboard
        )

    elif data == "admin_export_pdf":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM archive")
        total = cursor.fetchone()[0]
        conn.close()

        if total == 0:
            await query.edit_message_text(
                "⚠️ الأرشيف فارغ حالياً، لا يوجد ما يُصدَّر.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
            )
            return

        await query.edit_message_text(f"⏳ جاري توليد ملف PDF لـ {total} كتاباً، الرجاء الانتظار...")

        pdf_path = os.path.join(DATA_DIR, f"archive_export_{query.message.message_id}.pdf")
        try:
            # توليد PDF عملية تستهلك المعالج، تُنفَّذ في Thread منفصل حتى لا تُجمّد البوت أثناء التوليد
            count = await asyncio.to_thread(generate_archive_pdf, pdf_path)

            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename="archive_books_list.pdf",
                    caption=f"📄 فهرس الأرشيف الحالي — {count} كتاباً."
                )
        except Exception as e:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ حدث خطأ أثناء توليد الملف:\n`{e}`",
                parse_mode="Markdown"
            )
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
            parse_mode="Markdown",
            reply_markup=build_admin_panel_keyboard()
        )

    elif data == "admin_delete_count":
        context.user_data['awaiting_delete_count'] = True
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]])
        await query.edit_message_text(
            "🔢 أرسل الآن *عدد* الكتب التي تريد حذفها.\n\n"
            "سيتم حذف آخر عدد تمت أرشفته (الأحدث إضافةً للأرشيف).\n"
            "مثال: أرسل `50` لحذف آخر 50 كتاباً أُضيفت.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif data == "admin_raw_search":
        context.user_data['awaiting_raw_search'] = True
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]])
        await query.edit_message_text(
            "🔎 *بحث خام (تشخيصي)*\n\n"
            "أرسل الآن أي كلمة أو جزءاً من اسم كتاب.\n"
            "سيتم البحث *مباشرة* في قاعدة البيانات بدون أي منطق ذكي "
            "(بحث نصي خام SQL LIKE)، وستظهر لك كل النتائج المطابقة "
            "مع أرقام رسائلها بالضبط كما هي مخزّنة.\n\n"
            "مفيد للتأكد من وجود كتاب معين فعلياً في الأرشيف.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif data == "admin_back":
        context.user_data.pop('awaiting_delete_count', None)
        context.user_data.pop('awaiting_raw_search', None)
        await query.edit_message_text(
            "⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:",
            parse_mode="Markdown",
            reply_markup=build_admin_panel_keyboard()
        )


async def live_search_channel(query, limit=80):
    """
    بحث حي مباشر داخل القناة عبر حساب المستخدم (Userbot)، يُستخدم فقط كخطة احتياطية
    عندما لا يُعثر على الكتاب في الأرشفة المحلية — يغطي الملفات القديمة جداً
    التي رُفعت قبل انضمام البوت، دون الحاجة لأي أرشفة مسبقة.
    """
    if not user_client or not query:
        return []

    results = []
    try:
        async for msg in user_client.search_messages(CHANNEL_ID, query=query, limit=limit):
            document = msg.document or msg.video or msg.audio
            if not document:
                continue
            book_name = document.file_name or (msg.caption or f"Book_{msg.id}")
            results.append((book_name, msg.id, CHANNEL_ID))
    except Exception:
        # أي خطأ (فقدان اتصال الـ userbot، حد الطلبات، إلخ) لا يجب أن يوقف البوت
        return []

    return results


async def send_book_results(update, context, valid_books):
    """يحوّل قائمة الكتب من القناة مباشرة (يظهر 'محوّلة من القناة' مع الوصف الأصلي كاملاً)"""
    for book_name, msg_id, source_chat_id in valid_books:
        try:
            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=source_chat_id,
                message_id=msg_id
            )
            await asyncio.sleep(0.4)
        except Exception:
            pass


async def search_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    text = update.message.text.strip()

    # معالجة إدخال عدد الحذف إن كان الأدمن قد اختار "حذف آخر عدد من الكتب" من لوحة التحكم
    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_delete_count'):
        context.user_data.pop('awaiting_delete_count', None)

        if text.isdigit() and int(text) > 0:
            n = int(text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM archive ORDER BY id DESC LIMIT ?", (n,))
            ids_to_delete = [row[0] for row in cursor.fetchall()]
            if ids_to_delete:
                cursor.executemany(
                    "DELETE FROM archive WHERE id = ?",
                    [(i,) for i in ids_to_delete]
                )
                conn.commit()
            conn.close()

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_back")]])
            await update.message.reply_text(
                f"✅ تم حذف `{len(ids_to_delete)}` كتاباً (آخر ما تمت أرشفته).",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text("⚠️ الرجاء إرسال رقم صحيح فقط (مثال: 50).")
        return

    # معالجة إدخال كلمة البحث الخام إن كان الأدمن قد اختار "بحث خام" من لوحة التحكم
    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_raw_search'):
        context.user_data.pop('awaiting_raw_search', None)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT book_name, msg_id, source_chat_id FROM archive WHERE book_name LIKE ? LIMIT 30",
            (f"%{text}%",)
        )
        raw_rows = cursor.fetchall()
        cursor.execute(
            "SELECT COUNT(*) FROM archive WHERE book_name LIKE ?",
            (f"%{text}%",)
        )
        total_matches = cursor.fetchone()[0]
        conn.close()

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_back")]])

        if not raw_rows:
            await update.message.reply_text(
                f"🔎 لا توجد أي نتيجة تحتوي على النص ('{text}') في قاعدة البيانات إطلاقاً.",
                reply_markup=keyboard
            )
        else:
            lines = [f"🔎 نتائج البحث الخام عن ('{text}') — الإجمالي: {total_matches}\n"]
            for book_name, msg_id, source_chat_id in raw_rows:
                lines.append(f"• `{book_name}`\n   msg_id: `{msg_id}` | المصدر: `{source_chat_id}`")
            message_text = "\n".join(lines)
            if len(message_text) > 3900:
                message_text = message_text[:3900] + "\n\n... (تم اقتصاص القائمة، النتائج كثيرة)"
            await update.message.reply_text(message_text, parse_mode="Markdown", reply_markup=keyboard)
        return

    if text.startswith('/'):
        return

    if chat_type == 'private':
        if user_id not in ADMIN_IDS:
            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
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

    # --- الكشف عن استثناء "أريد كل/جميع كتب [الكاتب]" أولاً ---
    is_author_request = False
    author_query = None
    for pattern in AUTHOR_REQUEST_PATTERNS:
        m = pattern.match(clean_query.strip())
        if m:
            is_author_request = True
            author_query = m.group(1).strip()
            break

    if is_author_request and author_query:
        norm_query = normalize_arabic(author_query)
    else:
        phrases_to_remove = [
            "اريد كتاب", "أريد كتاب", "اريد كتاب ال", "أريد كتاب ال",
            "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب",
            "اريد", "أريد", "كتاب", "رواية"
        ]
        phrases_to_remove = sorted(phrases_to_remove, key=len, reverse=True)

        for phrase in phrases_to_remove:
            if clean_query.startswith(phrase):
                clean_query = clean_query[len(phrase):].strip()
                break

        if not clean_query:
            clean_query = text

        norm_query = normalize_arabic(clean_query)

    if not norm_query or len(norm_query) < 2:
        if chat_type == 'private':
            await update.message.reply_text("⚠️ يرجى كتابة اسم كتاب أو كلمة بحث صالحة تحتوي على أحرف.")
        return

    try:
        records, base_keys, index = await asyncio.to_thread(get_search_index)

        # ============= وضع "كل كتب الكاتب" =============
        if is_author_request:
            results = [
                records[i] for i, bk in enumerate(base_keys)
                if norm_query in bk
            ]

            # خطة احتياطية: بحث حي داخل القناة لتغطية الكتب القديمة غير المؤرشفة محلياً بعد
            if user_client:
                live_results = await live_search_channel(author_query, limit=100)
                for r in live_results:
                    if norm_query in normalize_arabic(r[0]):
                        results.append(r)

            if not results:
                await update.message.reply_text(
                    f"❌ لم يتم العثور على أي كتب باسم الكاتب ('{author_query}') في أرشيف القناة."
                )
                return

            deduped = dedupe_exact(results)
            await send_book_results(update, context, deduped)
            return

        # ============= وضع البحث العادي عن كتاب/سلسلة واحدة (بحث دقيق ضد التطابق الفضفاض) =============
        results = await asyncio.to_thread(find_book_matches_indexed, norm_query, records, base_keys, index)

        # خطة احتياطية: إن لم يُعثر على الكتاب محلياً، ابحث عنه حياً داخل القناة مباشرة
        # (يغطي الملفات القديمة جداً التي رُفعت قبل انضمام البوت، دون حاجة لأرشفة يدوية)
        if not results and user_client:
            live_candidates = await live_search_channel(clean_query, limit=80)
            live_base_keys = [normalize_arabic(strip_part_pattern(r[0])) for r in live_candidates]
            live_index = defaultdict(set)
            for i, bk in enumerate(live_base_keys):
                for w in get_words(bk):
                    live_index[w].add(i)
            results = find_book_matches_indexed(norm_query, live_candidates, live_base_keys, live_index)

        if not results:
            await update.message.reply_text(
                f"❌ عذراً، الاسم ('{clean_query}') غير موجود في أرشيف القناة.\n"
                f"تأكد من كتابة اسم الكتاب بشكل أقرب للعنوان الأصلي، أو حاول باسم مختصر أدق."
            )
            return

        # حذف التكرار الحرفي أولاً
        deduped = dedupe_exact(results)

        # تجميع النتائج حسب السلسلة (الاسم الأساسي بدون رقم الجزء)
        groups = group_into_series(deduped)

        # نختار المجموعة الأكثر تطابقاً مع طلب المستخدم:
        # إن كانت كل النتائج تنتمي لنفس السلسلة، نرسلها كاملة (كل الأجزاء).
        # إن كانت هناك عدة كتب مختلفة مطابقة (بحث عام)، نرسل كل مجموعة على حدة.
        final_books = []
        for base_key, items in groups.items():
            distinct_parts = {extract_part_number(b) for b, _, _ in items if extract_part_number(b) is not None}
            if len(distinct_parts) >= 2:
                # سلسلة متعددة الأجزاء: أرسل كل الأجزاء مرتبة
                sorted_items = sorted(
                    items,
                    key=lambda x: (extract_part_number(x[0]) is None, extract_part_number(x[0]) or 0)
                )
                final_books.extend(sorted_items)
            else:
                # كتاب واحد فقط لهذه المجموعة: أرسل أول نسخة غير مكررة فقط
                final_books.append(items[0])

        await send_book_results(update, context, final_books)

    except Exception as e:
        # أي خطأ غير متوقع يجب أن يصل للمستخدم كرسالة واضحة، وليس صمتاً تاماً
        print(f"❌ خطأ في search_and_forward: {e}")
        try:
            await update.message.reply_text(
                f"❌ حدث خطأ تقني أثناء البحث. حاول مجدداً، وإن تكرر أبلغ الأدمن.\n`{e}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def post_init(application):
    """يبدأ تشغيل حساب البحث الحي (Userbot) مع بدء تشغيل البوت، إن وُجد الإعداد اللازم"""
    if user_client:
        try:
            await user_client.start()
            print("✅ عميل البحث الحي (Userbot) متصل بنجاح.")
        except Exception as e:
            print(f"⚠️ تعذّر تشغيل عميل البحث الحي: {e}")
    else:
        print("ℹ️ USER_SESSION_STRING غير مُعرَّف — البحث الحي للملفات القديمة معطّل، سيعتمد البوت على الأرشفة المحلية فقط.")


async def post_shutdown(application):
    """يوقف عميل البحث الحي بأمان عند إيقاف البوت"""
    if user_client and user_client.is_connected:
        await user_client.stop()


def main():
    print("=" * 60)
    print("🔖 BOT_CODE_VERSION: 2026-08-15-v4-indexed-search-strict")
    print("=" * 60)
    init_db()
    migrate_db()

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    # أرشفة تلقائية من القناة أو أي كروب معتمد
    application.add_handler(MessageHandler(
        (filters.ChatType.CHANNEL | filters.ChatType.GROUPS) &
        (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
        handle_new_upload
    ))

    # استيراد أرشيف تاريخي (JSON) من الخاص فقط — اختياري الآن، البحث الحي يغطي الملفات القديمة تلقائياً
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("json"),
        import_json_archive
    ))

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS),
        search_and_forward
    ))

    print(f"البوت جاهز ويعمل مع المشرفين المعتمدين... [إصدار الكود: {CODE_VERSION}]")
    application.run_polling()


if __name__ == "__main__":
    main()
