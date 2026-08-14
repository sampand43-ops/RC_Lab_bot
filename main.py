import os
import json
import sqlite3
import re
import asyncio
import difflib
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

# مسار التخزين الدائم على Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

# معرف قناتك الثابت (يُستخدم كافتراضي عند عدم تحديد مصدر آخر)
CHANNEL_ID = -1004395670008

# قائمة مشرفي البوت المصرح لهم حصراً بإضافته للمجموعات وبالأرشفة اليدوية وإدارة اللوحة
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

ADMIN_HELP_TEXT = (
    "📌 *دليل استخدام البوت وتقسيم الصلاحيات*\n\n"
    "━━━━━━ 👑 *صلاحيات المشرف* ━━━━━━\n\n"
    "• *لوحة التحكم والأزرار:* عند إرسال `/start` في الخاص، تظهر لك لوحة تفاعلية لإدارة الأرشيف والإحصائيات.\n\n"
    "• *تفعيل المجموعات:* يمكنك إضافة البوت لأي مجموعة جديدة لتفعيلها تلقائياً واستخدامها من قِبل الأعضاء.\n\n"
    "• *الأرشفة التاريخية (JSON):* صدّر سجل القناة أو الكروب من Telegram Desktop (Export chat history → JSON)، ثم أرسل ملف `result.json` للبوت في الخاص، مع كتابة معرّف المحادثة (chat_id) كتعليق على الملف. سيقوم البوت بأرشفة كل الكتب الموجودة فيه دفعة واحدة.\n\n"
    "• *الأرشفة الآلية:* بمجرد رفع أي ملف جديد في القناة أو أي كروب معتمد، يتم حفظه وفهرسته في قاعدة البيانات فوراً.\n\n"
    "━━━━━━ 👥 *صلاحيات وإرشادات الأعضاء* ━━━━━━\n\n"
    "• *الاستخدام المقيّد:* يقتصر استخدام الأعضاء للبوت على المجموعات المعتمدة التي قمت بتفعيلها فقط.\n\n"
    "• *طرق البحث المتاحة:* يمكن للعضو البحث داخل المجموعة عن طريق:\n"
    "  1️⃣ الإشارة للبوت: `@RCGivvvv_bot اسم الكتاب`\n"
    "  2️⃣ أو عمل رد (Reply) على أي رسالة للبوت بكتابة اسم الكتاب."
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


# --- استيراد أرشيف تاريخي من ملف result.json ---
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
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")

        batch = []
        BATCH_SIZE = 2000
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
                conn.commit()
                batch.clear()

            percent = int((processed / total_msgs) * 100) if total_msgs else 100
            if percent >= last_reported_percent + 10:
                last_reported_percent = percent
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري الأرشفة... {percent}% ({processed}/{total_msgs})"
                    )
                except Exception:
                    pass

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO archive (book_name, msg_id, source_chat_id) VALUES (?, ?, ?)",
                batch
            )
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM archive WHERE source_chat_id = ?", (source_chat_id,))
        final_count = cursor.fetchone()[0]

        conn.close()
        os.remove(json_path)

        await status_msg.edit_text(
            f"✅ تمت الأرشفة بنجاح!\n"
            f"عدد الرسائل المفحوصة في هذا الملف: `{total_msgs}`\n"
            f"إجمالي الكتب المؤرشفة الآن لهذا المصدر: `{final_count}`"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة:\n`{e}`", parse_mode="Markdown")


# --- واجهة لوحة تحكم الآدمن مع الأزرار التفاعلية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archive")
            total_books = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM allowed_groups")
            total_groups = cursor.fetchone()[0]
            conn.close()

            keyboard = [
                [InlineKeyboardButton("📊 إحصائيات الأرشيف", callback_data="admin_stats")],
                [InlineKeyboardButton("🗑️ حذف عدد معين من الأرشيف", callback_data="admin_ask_delete_count")],
                [InlineKeyboardButton("⚠️ حذف كامل الأرشيف (تفريغ القاعدة)", callback_data="admin_confirm_clear")],
                [InlineKeyboardButton("📌 دليل الاستخدام والمساعدة", callback_data="admin_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            welcome_msg = (
                f"أهلاً بك في لوحة تحكم الآدمن الرئيسية 📚⚙️\n\n"
                f"• إجمالي الكتب المؤرشفة حالياً: `{total_books}` كتاب\n"
                f"• المجموعات المعتمدة المفعلة: `{total_groups}` مجموعة\n\n"
                f"اختر ما تريده من الأزرار أدناه:"
            )
            await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )


# --- معالجة الضغط على أزرار لوحة التحكم ---
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id not in ADMIN_IDS:
        await query.answer("عذراً، هذه الأزرار خاصة بالمشرفين فقط.", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "admin_stats":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM archive")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT source_chat_id, COUNT(*) FROM archive GROUP BY source_chat_id")
        sources = cursor.fetchall()
        conn.close()

        stats_text = f"📊 *إحصائيات قاعدة البيانات الشاملة*\n\n• إجمالي الكتب المؤرشفة: `{total}`\n\n*التوزيع حسب المصدر:* \n"
        for src, count in sources:
            stats_text += f"- القناة/المجموعة (`{src}`): `{count}` كتاب\n"

        keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_home")]]
        await query.edit_message_text(stats_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_home":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM archive")
        total_books = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM allowed_groups")
        total_groups = cursor.fetchone()[0]
        conn.close()

        keyboard = [
            [InlineKeyboardButton("📊 إحصائيات الأرشيف", callback_data="admin_stats")],
            [InlineKeyboardButton("🗑️ حذف عدد معين من الأرشيف", callback_data="admin_ask_delete_count")],
            [InlineKeyboardButton("⚠️ حذف كامل الأرشيف (تفريغ القاعدة)", callback_data="admin_confirm_clear")],
            [InlineKeyboardButton("📌 دليل الاستخدام والمساعدة", callback_data="admin_help")]
        ]
        welcome_msg = (
            f"أهلاً بك في لوحة تحكم الآدمن الرئيسية 📚⚙️\n\n"
            f"• إجمالي الكتب المؤرشفة حالياً: `{total_books}` كتاب\n"
            f"• المجموعات المعتمدة المفعلة: `{total_groups}` مجموعة\n\n"
            f"اختر ما تريده من الأزرار أدناه:"
        )
        await query.edit_message_text(welcome_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_help":
        keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_home")]]
        await query.edit_message_text(ADMIN_HELP_TEXT, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "admin_ask_delete_count":
        context.user_data['waiting_for_delete_count'] = True
        keyboard = [[InlineKeyboardButton("❌ إلغاء", callback_data="admin_home")]]
        await query.edit_message_text(
            "🗑️ *حذف عدد معين من الأرشيف*\n\n"
            "الرجاء كتابة **عدد الكتب** المراد حذفها (مثلاً: `500` أو `1000` من أحدث الكتب المضافة) وإرسالها برقم صحيح في هذه المحادثة.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "admin_confirm_clear":
        keyboard = [
            [InlineKeyboardButton("✅ نعم، متأكد (احذف الكل)", callback_data="admin_do_clear_all")],
            [InlineKeyboardButton("❌ تراجع وإلغاء", callback_data="admin_home")]
        ]
        await query.edit_message_text(
            "⚠️ *تحذير خطير جداً!*\n\n"
            "هل أنت متأكد من رغبتك في تفريغ قاعدة البيانات وحذف **جميع الكتب المؤرشفة بالكامل**؟ لا يمكن التراجع عن هذا الإجراء بعد تنفيذه.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "admin_do_clear_all":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()

        keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_home")]]
        await query.edit_message_text(
            "✅ تم تفريغ الأرشيف وحذف كافة السجلات بنجاح تام.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
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

    return None


def strip_part_pattern(filename):
    stripped = PART_PATTERN.sub('', filename)
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


AUTHOR_REQUEST_PATTERNS = [
    re.compile(r'^(?:اريد|أريد)\s+(?:كل|جميع)\s+كتب\s+(.+)$'),
    re.compile(r'^(?:كل|جميع)\s+كتب\s+(.+)$'),
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


def group_into_series(records):
    groups = defaultdict(list)
    for book_name, msg_id, source_chat_id in records:
        base_key = normalize_arabic(strip_part_pattern(book_name))
        groups[base_key].append((book_name, msg_id, source_chat_id))
    return groups


def find_book_matches(norm_query, all_records):
    query_words = get_words(norm_query)

    base_keys = {}
    for record in all_records:
        book_name = record[0]
        base_keys[book_name] = normalize_arabic(strip_part_pattern(book_name))

    exact = [r for r in all_records if base_keys[r[0]] == norm_query]
    if exact:
        return exact

    if len(query_words) < 2:
        return []

    startswith_matches = [r for r in all_records if base_keys[r[0]].startswith(norm_query)]
    if startswith_matches:
        return startswith_matches

    word_matches = []
    for r in all_records:
        name_words = get_words(base_keys[r[0]])
        if all(qw in name_words for qw in query_words):
            word_matches.append(r)
    if word_matches:
        return word_matches

    fuzzy_matches = []
    for r in all_records:
        name_words = get_words(base_keys[r[0]])
        if all(difflib.get_close_matches(qw, name_words, n=1, cutoff=0.8) for qw in query_words):
            fuzzy_matches.append(r)

    return fuzzy_matches


async def send_book_results(update, context, valid_books):
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

    # معالجة إدخال عدد الكتب المراد حذفها من قبل الآدمن
    if chat_type == 'private' and user_id in ADMIN_IDS:
        if context.user_data.get('waiting_for_delete_count'):
            context.user_data['waiting_for_delete_count'] = False
            try:
                count_to_delete = int(text)
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                # حذف أحدث عدد تم تحديده بناءً على الـ id الأكبر
                cursor.execute(
                    "DELETE FROM archive WHERE id IN (SELECT id FROM archive ORDER BY id DESC LIMIT ?)",
                    (count_to_delete,)
                )
                deleted_rows = cursor.rowcount
                conn.commit()
                conn.close()

                keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_home")]]
                await update.message.reply_text(
                    f"✅ تم بنجاح حذف آخر `{deleted_rows}` كتاب من الأرشيف.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except ValueError:
                keyboard = [[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="admin_home")]]
                await update.message.reply_text(
                    "❌ القيمة المدخلة غير صالحة. يرجى إرسال رقم صحيح (مثال: `100`).",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
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

    filtered_records = [
        r for r in all_records
        if not any(normalize_arabic(r[0]).startswith(p) for p in norm_forbidden)
    ]

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

    results = find_book_matches(norm_query, filtered_records)

    if not results:
        await update.message.reply_text(
            f"❌ عذراً، الاسم ('{clean_query}') غير موجود في أرشيف القناة.\n"
            f"تأكد من كتابة اسم الكتاب بشكل أقرب للعنوان الأصلي، أو حاول باسم مختصر أدق."
        )
        return

    deduped = dedupe_exact(results)
    groups = group_into_series(deduped)

    final_books = []
    for base_key, items in groups.items():
        distinct_parts = {extract_part_number(b) for b, _, _ in items if extract_part_number(b) is not None}
        if len(distinct_parts) >= 2:
            sorted_items = sorted(
                items,
                key=lambda x: (extract_part_number(x[0]) is None, extract_part_number(x[0]) or 0)
            )
            final_books.extend(sorted_items)
        else:
            final_books.append(items[0])

    await send_book_results(update, context, final_books)


def main():
    init_db()
    migrate_db()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))

    application.add_handler(MessageHandler(
        (filters.ChatType.CHANNEL | filters.ChatType.GROUPS) &
        (filters.Document.ALL | filters.AUDIO | filters.VIDEO),
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

    print("البوت جاهز ويعمل بكفاءة مع لوحة تحكم الآدمن والتفقد التفاعلي...")
    application.run_polling()


if __name__ == "__main__":
    main()

