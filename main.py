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
        "• النظام جاهز ومحدث للبحث الدقيق وإرسال الكتب بدون تكرار أو تداخل."
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

# قاموس الأرقام للأجزاء
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

# دالة البحث الذكية المصححة لعدم تداخل الكتب وعلاج مشكلة الأسماء
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
    
    # 1. محاولة البحث أولاً عما يبدأ بنص الطلب تماماً (للدقة العالية مثل "حياة الصحابة" أو "فن الحرب")
    cursor.execute("SELECT book_name, msg_id FROM archive WHERE book_name LIKE ? ORDER BY msg_id ASC", (f"{clean_query}%",))
    results = cursor.fetchall()
    
    # 2. إذا لم يجد بدايات مطابقة، نبحث بالاحتواء الشامل لكن بشرط أن يكون مطبقاً بذكاء
    if not results:
        cursor.execute("SELECT book_name, msg_id FROM archive WHERE book_name LIKE ? ORDER BY msg_id ASC", (f"%{clean_query}%",))
        results = cursor.fetchall()

    conn.close()
    
    if results:
        # تصفية إضافية لمنع تداخل الكتب: إذا كان البحث قصيراً (مثل "فن الحرب")، نتجنب جلب الكتب التي تُعتبر إصدارات أو مؤلفين مختلفين تماماً إلا إذا كانت مطابقة للطلب
        filtered_results = []
        for book_name, msg_id in results:
            # تنظيف اسم الملف للاستدلال
            b_lower = book_name.lower()
            q_lower = clean_query.lower()
            
            # إذا طلب المستخدم "فن الحرب" بحرفيتها، نتخطي النسخ التي تحتوي على اسم مؤلف إضافي مثل "نيكولاس" إلا إذا طلبها بالاسم
            if q_lower == "فن الحرب" and "نيكولاس" in b_lower:
                continue
            filtered_results.append((book_name, msg_id))
            
        if not filtered_results:
            filtered_results = results # العودة للنتائج الأصلية إذا تم استبعاد الكل بالخطأ

        # فلترة برمجية قاطعة لمنع تكرار نفس الملف الحرفي 100%
        seen_exact_names = set()
        unique_results = []
        for book_name, msg_id in filtered_results:
            exact_name = book_name.strip()
            if exact_name not in seen_exact_names:
                seen_exact_names.add(exact_name)
                unique_results.append((book_name, msg_id))

        # ترتيب النتائج حسب الأجزاء
        sorted_results = sorted(unique_results, key=lambda x: extract_part_number(x[0]))

        # إرسال الملفات المطلوبة
        for book_name, msg_id in sorted_results:
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

    print("بوت الأرشيف يعمل بكفاءة تامة ودقة مطلقة...")
    application.run_polling()

if __name__ == "__main__":
    main()
