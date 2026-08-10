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
        "• النظام يعمل الآن بكفاءة عالية وبدون أي تكرار."
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
    match = re.search(r'(الجزء|المجلد|مجلد|جـ?[\.\-\s]*)([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)', filename, re.IGNORECASE)
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
            
    return 0

# دالة تنظيف النص الأساسية والمعدلة لاستثناء التشكيل والرموز بدقة
def normalize_arabic(text):
    if not text:
        return ""
    # إزالة التشكيل والحركات بالكامل
    text = re.sub(r'[\u064b-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    # استبدال الرموز والفواصل والشرطات بمسافات لضمان عدم تداخل الكلمات
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

# دالة البحث الذكية الخالية من التكرار (بنفس المنطق المفضل لديك)
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
    # جلب السجلات الفريدة تماماً من قاعدة البيانات
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    norm_query = normalize_arabic(clean_query)
    results = []
    
    forbidden_prefixes = ["صور من", "قصص من", "مختصر", "شرح"]
    
    for book_name, msg_id in all_records:
        norm_name = normalize_arabic(book_name)
        
        if any(norm_name.startswith(normalize_arabic(prefix)) for prefix in forbidden_prefixes):
            continue
            
        if norm_query in norm_name:
            results.append((book_name, msg_id))

    if results:
        # ترتيب النتائج تصاعدياً حسب الأجزاء
        sorted_results = sorted(results, key=lambda x: extract_part_number(x[0]))

        # منع التكرار القاطع (بناءً على تطابق معرف الرسالة وأيضاً تطابق اسم الملف بالحرف الواحد)
        seen_msg_ids = set()
        seen_file_names = set()
        unique_books_to_send = []
        
        for book_name, msg_id in sorted_results:
            clean_name_key = book_name.strip().lower()
            if msg_id not in seen_msg_ids and clean_name_key not in seen_file_names:
                seen_msg_ids.add(msg_id)
                seen_file_names.add(clean_name_key)
                unique_books_to_send.append((book_name, msg_id))

        for book_name, msg_id in unique_books_to_send:
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error forwarding message {msg_id}: {e}")
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

    print("بوت البحث الذكي يعمل الآن بكفاءة وبدون تكرار...")
    application.run_polling()

if __name__ == "__main__":
    main()
