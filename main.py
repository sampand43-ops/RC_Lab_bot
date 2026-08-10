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
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك يا هندسة في بوت أرشيف مجتمع القراءة! 📚🤖\n"
        "• أعمل هنا وفي المجموعات لسحب وإرسال الكتب وأجزائها بالتسلسل بدون أي تكرار.\n"
        "• للبحث: اكتب (أريد كتاب [اسم الكتاب]) وسأقوم بإرسال الأجزاء بدقة فائقة!"
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
            
    num_match = re.search(r'[\s\-_]([0-9٠-٩]+)\s*(?:\.pdf|\.epub|\.zip)?$', filename)
    if num_match:
        val = num_match.group(1).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val.isdigit():
            return int(val)
            
    return 9999

# دالة البحث الذكية والدقيقة مع منع تكرار الأسماء المتطابقة 100%
async def search_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    clean_query = text
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

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # نجلب كل الكتب التي تبدأ بالكلمة المطلوبة
    cursor.execute("SELECT book_name, msg_id FROM archive WHERE book_name LIKE ? GROUP BY msg_id", (f"{clean_query}%",))
    results = cursor.fetchall()
    
    # إذا لم نجد تطابقاً كاملاً في البداية، نبحث عما إذا كان اسم الكتاب يتضمن الكلمة
    if not results:
        cursor.execute("SELECT book_name, msg_id FROM archive WHERE book_name LIKE ? GROUP BY msg_id", (f"%{clean_query}%",))
        all_results = cursor.fetchall()
        forbidden_prefixes = ["صور من", "قصص من", "مختصر", "شرح"]
        results = [
            item for item in all_results 
            if not any(item[0].strip().startswith(prefix) for prefix in forbidden_prefixes)
        ]

    conn.close()
    
    if results:
        sorted_results = sorted(results, key=lambda x: extract_part_number(x[0]))
        valid_books = [item for item in sorted_results if extract_part_number(item[0]) != 9999]
        
        if not valid_books:
            valid_books = [sorted_results[0]]

        # **إضافة حصرية لمنع تكرار إرسال الملفات التي تحمل نفس الاسم حرفياً 100%**
        seen_exact_names = set()
        unique_books_to_send = []
        for book_name, msg_id in valid_books:
            exact_name = book_name.strip()
            if exact_name not in seen_exact_names:
                seen_exact_names.add(exact_name)
                unique_books_to_send.append((book_name, msg_id))

        # إرسال الكتب الفريدة فقط
        for book_name, msg_id in unique_books_to_send:
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
        if update.effective_chat.type == 'private':
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), search_and_forward))

    print("بوت البحث الذكي والمفلتر يعمل الآن بكفاءة...")
    application.run_polling()

if __name__ == "__main__":
    main()
