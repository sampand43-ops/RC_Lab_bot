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
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامة بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)

LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامة بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
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
    "• *الأرشفة التاريخية (JSON):* صدّر سجل القناة من Telegram Desktop...\n\n"
    "• *البحث الحر في الخاص:* اكتب اسم الكتاب مباشرة دون أي شرط.\n"
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

# نمط لاستثناء الأرقام التي بين قوسين في نهاية الاسم (مثل (1) أو (٢)) باعتبارها نسخة مكررة وليس جزءاً
BRACKETED_DUPLICATE_PATTERN = re.compile(r'\(\s*[0-9٠-٩]+\s*\)\s*(?:\.pdf|\.epub|\.zip)?$')
TRAILING_NUM_PATTERN = re.compile(r'[\s\-_]([0-9٠-٩])\s*(?:\.pdf|\.epub|\.zip)?$')


def get_title_line(raw_book_name):
    if not raw_book_name:
        return raw_book_name
    first = raw_book_name.split('\n', 1)[0].strip()
    return first if first else raw_book_name


def extract_part_number(filename):
    if not filename:
        return None
    filename = get_title_line(filename)
    
    # إذا كان الرقم بين قوسين في النهاية، فهذا يعني نسخة مكررة وليس جزءاً
    if BRACKETED_DUPLICATE_PATTERN.search(filename):
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
    filename = get_title_line(filename)
    stripped = BRACKETED_DUPLICATE_PATTERN.sub('', filename)
    stripped = PART_PATTERN.sub('', stripped)
    stripped = TRAILING_NUM_PATTERN.sub('', stripped)
    stripped = re.sub(r'\.(pdf|epub|zip|mobi|docx?)$', '', stripped, flags=re.IGNORECASE)
    return stripped.strip()


def strip_al(word):
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
    if not filename:
        return ""
    return EXTENSION_ONLY_PATTERN.sub('', filename).strip()


AUTHOR_REQUEST_PATTERNS = [
    re.compile(r'^(?:اريد|أريد|ابغى|عايز|عاوز|عايزة|عاوزة)\s+(?:كل|جميع)\s+(?:كتب|روايات|مؤلفات|اعمال|أعمال|قصص)\s+(.+)$'),
    re.compile(r'^(?:كل|جميع)\s+(?:كتب|روايات|مؤلفات|اعمال|أعمال|قصص)\s+(.+)$'),
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
    alternates = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        key = normalize_arabic(book_name)
        alternates[key].append((msg_id, source_chat_id))
    return alternates


AUTHOR_SPLIT_PATTERN = re.compile(r'\s+[-–—]\s*|\s*[-–—]\s+')


def get_core_title(raw_book_name):
    if not raw_book_name:
        return ""
    raw_book_name = get_title_line(raw_book_name)
    core_raw = AUTHOR_SPLIT_PATTERN.split(raw_book_name, maxsplit=1)[0].strip()
    core_raw = strip_extension_only(core_raw)
    return normalize_arabic(core_raw)


def build_core_alternates_map(records):
    alternates = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        core = get_core_title(book_name)
        alternates[core].append((msg_id, source_chat_id))
    return alternates


def reduce_to_unique_parts(records, query_norm=""):
    deduped = dedupe_exact(records)
    
    # تجميع حسب العنوان الأساسي (قبل الشرطة التي تفصل اسم المؤلف عادة)
    groups = defaultdict(list)
    for item in deduped:
        book_name = item[0]
        base_key = get_core_title(book_name)
        groups[base_key].append(item)

    final_books = []
    for base_key, items in groups.items():
        if len(items) >= 1:
            # التحقق مما إذا كان الكتاب يحتوي على أجزاء حقيقية (بدون أقواس)
            has_parts = any(extract_part_number(item[0]) is not None for item in items)
            
            if has_parts:
                # إذا وجدنا أجزاء حقيقية، نقوم بترتيبها حسب رقم الجزء والاحتفاظ بكل الأجزاء وعدم دمجها
                sorted_items = sorted(items, key=lambda x: extract_part_number(x[0]) or 0)
                seen_parts = set()
                unique_parts = []
                for item in sorted_items:
                    part_num = extract_part_number(item[0])
                    if part_num is not None:
                        if part_num in seen_parts:
                            continue
                        seen_parts.add(part_num)
                    else:
                        # إذا كان هناك عنصر بدون رقم جزء صريح ضمن مجموعة الأجزاء
                        pass
                    unique_parts.append(item)
                final_books.extend(unique_parts)
            else:
                # الكتب العادية غير متعددة الأجزاء: نكتفي بنسخة واحدة نظيفة لتجنب التكرار
                exact_match_items = [it for it in items if normalize_arabic(get_core_title(it[0])) == query_norm]
                if exact_match_items and len(items) > 1:
                    best_item = min(exact_match_items, key=lambda x: len(x[0]))
                else:
                    best_item = min(items, key=lambda x: len(x[0]))
                final_books.append(best_item)
                
    return final_books


# ==================== فهرس البحث المُخزَّن مؤقتاً ====================

_search_index_cache = {
    "fingerprint": None, "records": [], "norm_names": [], "norm_names_no_ext": [],
    "norm_core_titles": [], "index": {}, "core_index": {}
}


def get_search_index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM archive")
    fingerprint = cursor.fetchone()

    if _search_index_cache["fingerprint"] == fingerprint:
        conn.close()
        c = _search_index_cache
        return (c["records"], c["norm_names"], c["norm_names_no_ext"], c["norm_core_titles"], c["index"], c["core_index"])

    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive GROUP BY msg_id, source_chat_id")
    raw_records = cursor.fetchall()
    conn.close()

    norm_forbidden = [normalize_arabic(p) for p in FORBIDDEN_PREFIXES]

    records, norm_names, norm_names_no_ext, norm_core_titles = [], [], [], []
    index = defaultdict(set)
    core_index = defaultdict(set)

    for book_name, msg_id, source_chat_id in raw_records:
        norm_name_full = normalize_arabic(book_name)
        if any(norm_name_full.startswith(p) for p in norm_forbidden):
            continue

        title_line = get_title_line(book_name)
        norm_name = normalize_arabic(title_line)

        i = len(records)
        records.append((book_name, msg_id, source_chat_id))
        norm_names.append(norm_name)
        norm_names_no_ext.append(normalize_arabic(strip_extension_only(title_line)))
        core_title = get_core_title(book_name)
        norm_core_titles.append(core_title)

        for w in get_words(norm_name):
            index[w].add(i)
        for w in get_words(core_title):
            core_index[w].add(i)

    _search_index_cache.update(
        fingerprint=fingerprint, records=records, norm_names=norm_names,
        norm_names_no_ext=norm_names_no_ext, norm_core_titles=norm_core_titles,
        index=index, core_index=core_index
    )
    return records, norm_names, norm_names_no_ext, norm_core_titles, index, core_index


def find_book_matches_indexed(norm_query, records, norm_names, norm_names_no_ext, norm_core_titles, core_index):
    query_words = get_words(norm_query)

    # مطابقة تامة 100% للعنوان أو العنوان الأساسي
    exact = [
        records[i] for i, nn in enumerate(norm_names_no_ext)
        if nn == norm_query or norm_core_titles[i] == norm_query
    ]
    if exact:
        return exact

    if len(query_words) < 2:
        return []

    startswith_matches = [records[i] for i, nn in enumerate(norm_names) if nn.startswith(norm_query)]
    if startswith_matches:
        return startswith_matches

    word_sets = [core_index.get(qw) for qw in query_words]
    if all(word_sets):
        common = set.intersection(*word_sets)
        if common:
            return [records[i] for i in common]

    cutoff = 0.9 if any(len(qw) < 3 for qw in query_words) else 0.85
    vocabulary = list(core_index.keys())
    per_word_candidates = []
    for qw in query_words:
        if len(qw) < 3:
            if qw not in core_index:
                return []
            word_candidates = set(core_index[qw])
        else:
            close_words = difflib.get_close_matches(qw, vocabulary, n=5, cutoff=cutoff)
            if not close_words:
                return []
            word_candidates = set()
            for w in close_words:
                word_candidates |= core_index.get(w, set())
        per_word_candidates.append(word_candidates)

    common = set.intersection(*per_word_candidates) if per_word_candidates else set()
    return [records[i] for i in common]


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
    if chat.id != GROUP_ID and not is_group_approved(chat.id):
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

    BOT_API_MAX_DOWNLOAD = 20 * 1024 * 1024
    if document.file_size and document.file_size > BOT_API_MAX_DOWNLOAD:
        size_mb = document.file_size / (1024 * 1024)
        await update.message.reply_text(
            f"⚠️ الملف حجمه {size_mb:.1f} ميجابايت، وهذا أكبر من الحد المسموح للبوتات (20 ميجابايت).\n"
            f"يرجى تقسيم الملف وإعادة إرساله.",
            parse_mode="Markdown"
        )
        return

    caption = update.message.caption
    forced_source_chat_id = int(caption.strip()) if caption and caption.strip().lstrip('-').isdigit() else None

    status_msg = await update.message.reply_text("🚀 جاري تحليل ملف التصدير...")

    try:
        file = await context.bot.get_file(document.file_id)
        json_path = os.path.join(DATA_DIR, f"temp_export_{update.message.message_id}.json")
        await file.download_to_drive(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        auto_detected_source_id = None
        raw_json_id = data.get("id")
        if isinstance(raw_json_id, int):
            auto_detected_source_id = int(f"-100{raw_json_id}")

        source_chat_id = forced_source_chat_id or auto_detected_source_id or GROUP_ID

        messages = data.get("messages", [])

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

        batch, BATCH_SIZE = [], 2000
        for msg in messages:
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

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)", batch
            )
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM archive WHERE source_chat_id = ?", (source_chat_id,))
        final_count = cursor.fetchone()[0]
        conn.close()
        os.remove(json_path)

        await status_msg.edit_text(f"✅ تمت الأرشفة بنجاح! إجمالي الكتب: `{final_count}`")
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
    chat_type = update.effective_chat.type
    user_id = update.effective_user.id
    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return
        await update.message.reply_text(f"للبحث: أشِر للبوت `@{BOT_USERNAME} اسم الكتاب` أو رُدّ على رسالته.", parse_mode="Markdown")
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
    await update.message.reply_text("⚙️ *لوحة تحكم الأرشيف*\n\nاختر أحد الخيارات:", parse_mode="Markdown", reply_markup=build_admin_panel_keyboard())


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
            return ''.join(ch for ch in shaped if unicodedata.category(ch) != 'Cf')
        except Exception:
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
    try:
        c.drawRightString(width - 40, y, safe_display(f"فهرس أرشيف الكتب — إجمالي: {len(rows)} كتاباً"))
    except Exception:
        pass
    y -= line_height * 2

    c.setFont(font_name, 11)
    skipped = 0
    for index, (book_name, msg_id, source_chat_id) in enumerate(rows, start=1):
        try:
            c.drawRightString(width - 40, y, safe_display(f"{index}. {book_name}  [msg_id: {msg_id}]"))
        except Exception:
            skipped += 1
        y -= line_height
        if y < margin_bottom:
            c.showPage()
            c.setFont(font_name, 11)
            y = height - margin_top

    c.save()
    return len(rows), skipped


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
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
            text += f"• كروب/قناة ({chat_id}): `{count}`\n"

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))

    elif data == "admin_clear_all":
        await query.edit_message_text(
            "⚠️ *تأكيد الحذف الكامل*\n\nسيُحذف فهرس الأرشيف المحلي فقط. متأكد؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، احذف كل شيء", callback_data="admin_clear_all_confirm")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")],
            ])
        )

    elif data == "admin_clear_all_confirm":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ تم حذف كامل فهرس الأرشيف بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))

    elif data == "admin_export_pdf":
        pdf_path = os.path.join(DATA_DIR, f"archive_export_{query.message.message_id}.pdf")
        try:
            count, _ = await asyncio.to_thread(generate_archive_pdf, pdf_path)
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(chat_id=query.message.chat_id, document=f, filename="archive_books_list.pdf", caption=f"📄 فهرس الأرشيف — {count} كتاباً.")
        except Exception as e:
            await context.bot.send_message(query.message.chat_id, f"❌ خطأ:\n`{e}`", parse_mode="Markdown")
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        await query.edit_message_text("⚙️ *لوحة تحكم الأرشيف*", parse_mode="Markdown", reply_markup=build_admin_panel_keyboard())

    elif data == "admin_delete_count":
        context.user_data['awaiting_delete_count'] = True
        await query.edit_message_text("🔢 أرسل الآن *عدد* الكتب لحذفها (مثال: `50`)", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]]))

    elif data == "admin_raw_search":
        context.user_data['awaiting_raw_search'] = True
        await query.edit_message_text("🔎 أرسل كلمة للبحث الخام في قاعدة البيانات:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]]))

    elif data == "admin_back":
        context.user_data.pop('awaiting_delete_count', None)
        context.user_data.pop('awaiting_raw_search', None)
        await query.edit_message_text("⚙️ *لوحة تحكم الأرشيف*", parse_mode="Markdown", reply_markup=build_admin_panel_keyboard())


# ==================== الإرسال والبحث ====================

THANK_YOU_MESSAGES = [
    "📚 تفضّل، أتمنى لك قراءة ممتعة!",
    "✨ تم إرسال طلبك، استمتع بالقراءة!",
    "🌟 تفضّل كتابك، قراءة ممتعة!",
]


async def send_book_results(update, context, valid_books, alternates_map=None, core_alternates_map=None):
    alternates_map = alternates_map or {}
    core_alternates_map = core_alternates_map or {}
    succeeded, failed = [], []

    request_id = None
    control_msg = None
    if len(valid_books) > 1:
        request_id = uuid.uuid4().hex[:10]
        context.bot_data.setdefault('active_sends', {})[request_id] = {'cancelled': False, 'user_id': update.effective_user.id}
        try:
            control_msg = await update.message.reply_text(
                f"⏳ جاري إرسال {len(valid_books)} ملفاً...",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⛔ إيقاف الطلب", callback_data=f"stopreq_{request_id}")]])
            )
        except Exception:
            pass

    cancelled = False
    for i, (book_name, msg_id, source_chat_id) in enumerate(valid_books):
        if request_id:
            info = context.bot_data.get('active_sends', {}).get(request_id)
            if info and info.get('cancelled'):
                cancelled = True
                break

        key = normalize_arabic(book_name)
        core_key = get_core_title(book_name)

        candidates = [(msg_id, source_chat_id)]
        for alt_msg_id, alt_source in alternates_map.get(key, []):
            if (alt_msg_id, alt_source) not in candidates:
                candidates.append((alt_msg_id, alt_source))
        for alt_msg_id, alt_source in core_alternates_map.get(core_key, []):
            if (alt_msg_id, alt_source) not in candidates:
                candidates.append((alt_msg_id, alt_source))

        if (msg_id, GROUP_ID) not in candidates:
            candidates.append((msg_id, GROUP_ID))

        sent = False
        last_error = None
        for attempt_msg_id, attempt_source in candidates:
            try:
                await context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=attempt_source,
                    message_id=attempt_msg_id
                )
                succeeded.append(book_name)
                sent = True
                break
            except Exception as e:
                last_error = e

        if not sent:
            failed.append((book_name, msg_id, str(last_error)))

    if request_id:
        context.bot_data.get('active_sends', {}).pop(request_id, None)
        if control_msg:
            try:
                await control_msg.edit_text(f"✅ تم إرسال {len(succeeded)} ملفاً.")
            except Exception:
                pass

    if succeeded:
        try:
            await update.message.reply_text(random.choice(THANK_YOU_MESSAGES))
        except Exception:
            pass

    if failed and not succeeded:
        await update.message.reply_text("⚠️ عذراً، الكتاب موجود بالأرشيف ولكن تعذر توفيره حالياً.")

    return succeeded, failed


async def stop_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    request_id = data.split('_', 1)[1] if '_' in data else None
    active = context.bot_data.get('active_sends', {})
    info = active.get(request_id) if request_id else None

    if not info:
        await query.answer("انتهى هذا الطلب بالفعل.", show_alert=True)
        return

    if query.from_user.id != info.get('user_id') and query.from_user.id not in ADMIN_IDS:
        await query.answer("هذا الطلب ليس لك.", show_alert=True)
        return

    info['cancelled'] = True
    await query.answer("⛔ سيتم إيقاف الطلب...")


FILLER_PHRASES = sorted([
    "اريد كتاب", "أريد كتاب", "اريد كتاب ال", "أريد كتاب ال",
    "ابغى", "ابغى كتاب", "ابغى رواية", "ممكن", "ممكن كتاب",
    "عايز", "عايز كتاب", "عاوز", "عاوز كتاب", "هل يوجد",
    "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب",
    "احتاج", "أحتاج", "بدي", "ابي", "أبي", "اريد", "أريد", "كتاب", "رواية"
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

    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_delete_count'):
        context.user_data.pop('awaiting_delete_count', None)
        try:
            n = int(text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM archive ORDER BY id DESC LIMIT ?", (n,))
            ids_to_delete = [row[0] for row in cursor.fetchall()]
            if ids_to_delete:
                cursor.executemany("DELETE FROM archive WHERE id = ?", [(i,) for i in ids_to_delete])
                conn.commit()
            conn.close()
            await update.message.reply_text(f"✅ تم حذف {len(ids_to_delete)} كتاباً.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
        return

    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_raw_search'):
        context.user_data.pop('awaiting_raw_search', None)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive WHERE book_name LIKE ? LIMIT 30", (f"%{text}%",))
        raw_rows = cursor.fetchall()
        conn.close()
        lines = [f"🔎 نتائج ({text}):\n"] + [f"• {r[0]} (msg_id: {r[1]})" for r in raw_rows]
        await update.message.reply_text("\n".join(lines) if raw_rows else "لا توجد نتائج.")
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

    is_author_request, author_query = False, None
    for pattern in AUTHOR_REQUEST_PATTERNS:
        m = pattern.match(clean_query.strip())
        if m:
            is_author_request, author_query = True, m.group(1).strip()
            break

    if is_author_request and author_query:
        norm_query = normalize_arabic(author_query)
    else:
        clean_query = strip_filler_phrases(clean_query)
        if not clean_query:
            clean_query = text
        norm_query = normalize_arabic(clean_query)

    if not norm_query or len(norm_query) < 2:
        return

    try:
        records, norm_names, norm_names_no_ext, norm_core_titles, _, core_index = await asyncio.to_thread(get_search_index)

        if is_author_request:
            results = [records[i] for i, nn in enumerate(norm_names) if norm_query in nn]
            if not results:
                await update.message.reply_text(f"❌ لم يتم العثور على كتب للكاتب ('{author_query}').")
                return
            await send_book_results(update, context, reduce_to_unique_parts(results, norm_query), build_alternates_map(results), build_core_alternates_map(results))
            return

        results = await asyncio.to_thread(
            find_book_matches_indexed, norm_query, records, norm_names, norm_names_no_ext, norm_core_titles, core_index
        )

        if not results:
            await update.message.reply_text(f"❌ عذراً، الكتاب ('{clean_query}') غير موجود في الأرشيف.")
            return

        final_books = reduce_to_unique_parts(results, norm_query)
        await send_book_results(update, context, final_books, build_alternates_map(results), build_core_alternates_map(results))

    except Exception as e:
        print(f"❌ خطأ: {e}")


# ==================== التشغيل ====================

def main():
    print("=" * 60)
    print("🔖 BOT_CODE_VERSION: Complete Parts Handling & Bracketed Duplicate Filtering")
    print("=" * 60)

    init_db()
    migrate_db()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(stop_request_callback, pattern="^stopreq_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
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
