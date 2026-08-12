import os
import sqlite3
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from pyrogram import Client

# مسار التخزين الدائم على Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

API_ID = 34123643
API_HASH = "12dccc6e1dce1c82853587ba04e9694d"
TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

# معرف قناتك
CHANNEL_ID = -1004395670008
ADMIN_IDS = [7898871921, 1937491557]

BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)

LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
    f"سأقوم بالمغادرة الآن..."
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            msg_id INTEGER UNIQUE
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
                await context.bot.send_message(chat_id=chat.id, text=LEAVE_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
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
                await context.bot.send_message(chat_id=chat.id, text="أهلاً بكم! 📚🤖\nتم تفعيل البوت بنجاح لهذه المجموعة بواسطة المشرف.")
            else:
                await context.bot.send_message(chat_id=chat.id, text=LEAVE_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
                await context.bot.leave_chat(chat.id)

async def on_bot_left_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.left_chat_member:
        if update.message.left_chat_member.id == context.bot.id:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM allowed_groups WHERE chat_id = ?", (update.effective_chat.id,))
            conn.commit()
            conn.close()

# --- لوحة التحكم والأزرار للمشرف ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup'] and not await is_allowed_group(update, context):
        return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            keyboard = [
                [InlineKeyboardButton("⚡ أرشفة القناة بالكامل (الأسماء فقط)", callback_data="sync_channel")],
                [InlineKeyboardButton("📊 عرض الإحصائيات السريعة", callback_data="stats")],
                [InlineKeyboardButton("🗑️ حذف الأرشيف بالكامل", callback_data="clear_archive")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "أهلاً بك في لوحة تحكم البوت 📚⚙️\n\n"
                "• يتم تخزين أسماء الكتب ومعرفاتها فقط لعدم استهلاك مساحة السيرفر.\n"
                "• اختر إحدى العمليات أدناه من الأزرار:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ إشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل (رد/Reply) على أي رسالة للبوت وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )

# --- معالجة الضغط على الأزرار ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return

    data = query.data

    if data == "stats":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT msg_id) FROM archive")
        count = cursor.fetchone()[0]
        conn.close()
        await query.message.reply_text(f"📊 إحصائيات الأرشيف الحالية:\nعدد الكتب المسجلة: `{count}` كتاباً.", parse_mode="Markdown")

    elif data == "clear_archive":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()
        await query.message.reply_text("🗑️ تم تفريغ الأرشيف بالكامل بنجاح.")

    elif data == "sync_channel":
        status_msg = await query.message.reply_text("🚀 جاري الاتصال بالقناة وسحب أسماء الملفات فقط...")
        try:
            count = 0
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # حل مشكلة الـ Peer عن طريق جلب معلومات القناة أولاً داخل الجلسة
            async with Client("archive_bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN) as app:
                chat = await app.get_chat(CHANNEL_ID)
                async for message in app.get_chat_history(chat.id):
                    document = message.document or message.video or message.audio
                    if document:
                        book_name = document.file_name or message.caption or f"Book_{message.id}"
                        try:
                            cursor.execute("INSERT INTO archive (book_name, msg_id) VALUES (?, ?)", (book_name, message.id))
                            count += 1
                        except sqlite3.IntegrityError:
                            pass
            conn.commit()
            conn.close()
            await status_msg.edit_text(f"✅ تمت أرشفة أسماء الملفات بنجاح!\nتم إضافة `{count}` كتاباً جديداً دون استهلاك مساحة السيرفر.", parse_mode="Markdown")
        except Exception as e:
            await status_msg.edit_text(f"❌ حدث خطأ أثناء الأرشفة:\n`{e}`", parse_mode="Markdown")

# --- تخزين اسم الملف للرسائل الجديدة فور نشرها في القناة ---
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message:
        document = message.document or message.video or message.audio
        if document:
            book_name = document.file_name or message.caption or "Unknown_Book"
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO archive (book_name, msg_id) VALUES (?, ?)", (book_name, message.message_id))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()

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

def extract_part_number(filename):
    match = re.search(r'(الجزء|المجلد|جـ?|مجلد|part|vol)\s*([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)', filename, re.IGNORECASE)
    if match:
        val = match.group(2)
        if val in ARABIC_NUM_WORDS:
            return ARABIC_NUM_WORDS[val]
        val_en = val.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val_en.isdigit():
            return int(val_en)
    num_match = re.search(r'[\s\-_]([0-9٠-٩]+|\d+)\s*(?:\.pdf|\.epub|\.zip)?$', filename)
    if num_match:
        val = num_match.group(1).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val.isdigit():
            return int(val)
    return 9999

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
    return text.strip().lower()

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

    phrases_to_remove = ["اريد كتاب", "أريد كتاب", "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب", "اريد", "أريد", "كتاب", "رواية"]
    for phrase in sorted(phrases_to_remove, key=len, reverse=True):
        if clean_query.startswith(phrase):
            clean_query = clean_query[len(phrase):].strip()
            break
            
    if not clean_query:
        clean_query = text

    norm_query = normalize_arabic(clean_query)
    if not norm_query or len(norm_query) < 2:
        if chat_type == 'private':
            await update.message.reply_text("⚠️ يرجى كتابة اسم كتاب صالح للبحث.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    results = []
    for book_name, msg_id in all_records:
        norm_name = normalize_arabic(book_name)
        if norm_name.startswith(norm_query):
            results.append((book_name, msg_id))
            
    if not results:
        for book_name, msg_id in all_records:
            norm_name = normalize_arabic(book_name)
            if norm_query in norm_name:
                results.append((book_name, msg_id))
    
    if results:
        sorted_results = sorted(results, key=lambda x: extract_part_number(x[0]))
        valid_books = [item for item in sorted_results if extract_part_number(item[0]) != 9999]
        if not valid_books:
            valid_books = [sorted_results[0]]

        for book_name, msg_id in valid_books:
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception:
                pass
    else:
        if chat_type == 'private':
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), search_and_forward))

    print("البوت يعمل بكفاءة تامة مع الأزرار ولوحة التحكم...")
    application.run_polling()

if __name__ == "__main__":
    main()

