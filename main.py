import os
import json
import sqlite3
import re
import asyncio
import difflib
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# مسار التخزين الدائم على Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

# معرف قناتك الثابت (يُستخدم كافتراضي عند عدم تحديد مصدر آخر)
CHANNEL_ID = -1004395670008

# قائمة مشرفي البوت المصرح لهم حصراً بإضافته للمجموعات وبالأرشفة اليدوية
ADMIN_IDS = [7898871921, 1937491557]

# معرف البوت وبيانات المجموعة الرئيسية
BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

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
            f"✅ تمت الأرشفة بنجاح!\n"
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
TRAILING_NUM_PATTERN = re.compile(r'[\s\-_]([0-9٠-٩]+)\s*(?:\.pdf|\.epub|\.zip)?$')


def extract_part_number(filename):
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


def find_book_matches(norm_query, all_records):
    """
    بحث دقيق بأولويات صارمة لتفادي إرسال كتب غير مرتبطة بالطلب:
    1) تطابق تام كامل للاسم (بعد حذف الامتداد ورقم الجزء)
    2) (فقط للطلبات متعددة الكلمات) الاسم يبدأ بنص الطلب بالكامل
    3) (فقط للطلبات متعددة الكلمات) كل كلمات الطلب موجودة كاملة داخل اسم الكتاب
    4) (فقط للطلبات متعددة الكلمات) تطابق تقريبي على مستوى كل كلمة (يسمح بأخطاء إملائية بسيطة)
    الطلبات المكوّنة من كلمة واحدة فقط تُقبل حصراً عند التطابق التام،
    لتفادي مشاكل مثل طلب "إدارة" وحده الذي يطابق عشرات العناوين المختلفة.
    """
    query_words = get_words(norm_query)

    base_keys = {}
    for record in all_records:
        book_name = record[0]
        base_keys[book_name] = normalize_arabic(strip_part_pattern(book_name))

    # 1) تطابق تام (على الاسم بعد حذف الامتداد ورقم الجزء)
    exact = [r for r in all_records if base_keys[r[0]] == norm_query]
    if exact:
        return exact

    # الطلبات المكوّنة من كلمة واحدة فقط تتوقف هنا تماماً (لا مطابقة فضفاضة إطلاقاً)
    if len(query_words) < 2:
        return []

    # 2) الاسم يبدأ بنص الطلب بالكامل
    startswith_matches = [r for r in all_records if base_keys[r[0]].startswith(norm_query)]
    if startswith_matches:
        return startswith_matches

    # 3) كل كلمات الطلب موجودة كاملة (بأي ترتيب) داخل اسم الكتاب
    word_matches = []
    for r in all_records:
        name_words = get_words(base_keys[r[0]])
        if all(qw in name_words for qw in query_words):
            word_matches.append(r)
    if word_matches:
        return word_matches

    # 4) تطابق تقريبي على مستوى كل كلمة (يتحمل أخطاء إملائية بسيطة) — لكل كلمات الطلب معاً
    fuzzy_matches = []
    for r in all_records:
        name_words = get_words(base_keys[r[0]])
        if all(difflib.get_close_matches(qw, name_words, n=1, cutoff=0.8) for qw in query_words):
            fuzzy_matches.append(r)

    return fuzzy_matches


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

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id, source_chat_id FROM archive GROUP BY msg_id, source_chat_id")
    all_records = cursor.fetchall()
    conn.close()

    norm_forbidden = [normalize_arabic(p) for p in FORBIDDEN_PREFIXES]

    # نستبعد الملفات ذات البادئات غير المرغوبة (صور من، مختصر...) من كل عمليات البحث
    filtered_records = [
        r for r in all_records
        if not any(normalize_arabic(r[0]).startswith(p) for p in norm_forbidden)
    ]

    # ============= وضع "كل كتب الكاتب" =============
    if is_author_request:
        results = [
            r for r in filtered_records
            if norm_query in normalize_arabic(r[0])
        ]

        if not results:
            await update.message.reply_text(
                f"❌ لم يتم العثور على أي كتب باسم الكاتب ('{author_query}') في أرشيف القناة."
            )
            return

        deduped = dedupe_exact(results)
        await send_book_results(update, context, deduped)
        return

    # ============= وضع البحث العادي عن كتاب/سلسلة واحدة (بحث دقيق ضد التطابق الفضفاض) =============
    results = find_book_matches(norm_query, filtered_records)

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


def main():
    init_db()
    migrate_db()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    # أرشفة تلقائية من القناة أو أي كروب معتمد
    application.add_handler(MessageHandler(
        (filters.ChatType.CHANNEL | filters.ChatType.GROUPS) &
        (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
        handle_new_upload
    ))

    # استيراد أرشيف تاريخي (JSON) من الخاص فقط
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.Document.FileExtension("json"),
        import_json_archive
    ))

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS),
        search_and_forward
    ))

    print("البوت جاهز ويعمل مع المشرفين المعتمدين...")
    application.run_polling()


if __name__ == "__main__":
    main()
