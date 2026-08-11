import os
import sqlite3
import re
import asyncio
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

# معرف قناتك الثابت
CHANNEL_ID = -1004395670008

# قائمة مشرفي البوت المصرح لهم بإضافته للمجموعات
ADMIN_IDS = [7898871921]

# معرف البوت وبيانات المجموعة الرئيسية
BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"
ALLOWED_GROUP_USERNAME = "reading_community_group"  # معرف المجموعة الرئيسية

# نص التقييد والاعتذار
RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # جدول الأرشيف
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            msg_id INTEGER UNIQUE
        )
    """)
    # جدول المجموعات المسموح لها (التي يضيفها المشرف)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

# دالة للتحقق من السماح للمجموعة من قاعدة البيانات أو اليوزرنيم
def is_group_approved(chat_id: int, chat_username: str) -> bool:
    if chat_username and chat_username.lower() == ALLOWED_GROUP_USERNAME.lower():
        return True
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM allowed_groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    
    return bool(row)

# دالة الفحص والمغادرة عند الحاجة
async def is_allowed_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        if is_group_approved(chat.id, chat.username):
            return True
        else:
            # مغادرة المجموعات غير المعتمدة
            try:
                group_leave_text = (
                    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
                    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
                    f"سأقوم بالمغادرة الآن..."
                )
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=group_leave_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                await context.bot.leave_chat(chat.id)
            except Exception:
                pass
            return False
    return True

# التعامل مع إضافة البوت لمجموعة جديدة
async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.message.from_user.id if update.message and update.message.from_user else None

    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            # 1. إذا كانت المجموعة هي الرئيسية
            if chat.username and chat.username.lower() == ALLOWED_GROUP_USERNAME.lower():
                return
            
            # 2. إذا قام المشرف المعتمد بالإضافة
            if user_id in ADMIN_IDS:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO allowed_groups (chat_id, added_by) VALUES (?, ?)", (chat.id, user_id))
                conn.commit()
                conn.close()
                
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="أهلاً بكم! 📚🤖\nتم تفعيل البوت بنجاح لهذه المجموعة بواسطة المشرف."
                )
            # 3. إذا أضافه عضو آخر غير المشرف -> رفض ومغادرة
            else:
                await is_allowed_group(update, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(
                "أهلاً بك يا هندسة في لوحة تحكم البوت! 📚🤖\n"
                "• يمكنك البحث واستعراض الأرشيف هنا بحرية بصفتك المشرف.\n"
                "• يمكنك إضافة البوت لأي مجموعة جديدة وسيعمل فيها تلقائياً."
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

# دالة السحب التلقائي من القناة
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message:
        msg_id = message.message_id
        document = message.document or message.video or message.audio
        
        if document:
            book_name = document.file_name or message.caption or "Unknown_Book"
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO archive (book_name, msg_id) VALUES (?, ?)",
                    (book_name, msg_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()

# قاموس الأرقام
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

# دالة البحث المفلترة والمعالجة
async def search_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    text = update.message.text.strip()

    if text.startswith('/'):
        return

    # 1. المعالجة في المحادثة الخاصة
    if chat_type == 'private':
        if user_id not in ADMIN_IDS:
            await update.message.reply_text(
                RESTRICTED_TEXT, 
                parse_mode="Markdown", 
                disable_web_page_preview=True
            )
            return
        clean_query = text

    # 2. المعالجة داخل المجموعات
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
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    results = []
    
    for book_name, msg_id in all_records:
        norm_name = normalize_arabic(book_name)
        if norm_name.startswith(norm_query):
            results.append((book_name, msg_id))
            
    if not results:
        forbidden_prefixes = ["صور من", "قصص من", "مختصر", "شرح"]
        norm_forbidden = [normalize_arabic(p) for p in forbidden_prefixes]
        
        for book_name, msg_id in all_records:
            norm_name = normalize_arabic(book_name)
            if norm_query in norm_name:
                if not any(norm_name.startswith(p) for p in norm_forbidden):
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
            except Exception as e:
                pass
    else:
        if chat_type == 'private':
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), search_and_forward))

    print("بوت البحث الذكي يعمل؛ صلاحيات الإضافة محصورة بالمشرف فقط...")
    application.run_polling()

if __name__ == "__main__":
    main()

