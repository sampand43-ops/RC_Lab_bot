import os
import sqlite3
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# مسار التخزين الدائم على Railway (لا يُحذف أبداً عند تحديث الكود)
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

# تهيئة قاعدة البيانات الدائمة
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            file_id TEXT,
            file_type TEXT
        )
    """)
    conn.commit()
    conn.close()

# أمر البدء
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك يا هندسة في بوت أرشيف المعمل والملفات! 📚🤖\n"
        "• لحفظ الكتب: قم بتحويلها (Forward) من القناة إلى هنا.\n"
        "• للبحث: اكتب (أريد كتاب [اسم الكتاب]) أو (أريد رواية [اسم الرواية]) وسأحضره لك فوراً."
    )

# دالة استقبال وحفظ الملفات (سواء أرسلتها مباشرة أو حولتها من القناة)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    document = message.document or message.video or message.audio
    
    if document:
        file_id = document.file_id
        file_name = document.file_name or "Unknown_File"
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM files WHERE file_id = ?", (file_id,))
        exists = cursor.fetchone()
        
        if not exists:
            cursor.execute(
                "INSERT INTO files (file_name, file_id, file_type) VALUES (?, ?, ?)",
                (file_name, file_id, "document")
            )
            conn.commit()
            conn.close()
            await message.reply_text(f"✅ تم حفظ الكتاب في الأرشيف الدائم بنجاح:\n📁 {file_name}")
        else:
            conn.close()
            await message.reply_text("ℹ️ هذا الكتاب موجود مسبقاً في الأرشيف الدائم.")

# دالة البحث الذكي (استخراج اسم الكتاب وتجاهل الكلمات الزائدة)
async def search_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # تنظيف النص وإزالة الكلمات الافتتاحية الشائعة لاستخلاص اسم الكتاب الحقيقي فقط
    clean_query = text
    phrases_to_remove = [
        "اريد كتاب", "أريد كتاب", "اريد كتاب ال", "أريد كتاب ال",
        "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب", 
        "اريد", "أريد", "كتاب", "رواية"
    ]
    
    # ترتيب الكلمات تنازلياً حسب الطول لتجنب الأخطاء في الحذف
    phrases_to_remove = sorted(phrases_to_remove, key=len, reverse=True)
    
    for phrase in phrases_to_remove:
        if clean_query.startswith(phrase):
            clean_query = clean_query[len(phrase):].strip()
            break
            
    # إذا لم يبقَ شيء بعد الحذف، نبحث بالنص الأصلي
    if not clean_query:
        clean_query = text

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # البحث المرن بالاسم المستخلص
    cursor.execute("SELECT file_name, file_id FROM files WHERE file_name LIKE ?", (f"%{clean_query}%",))
    results = cursor.fetchall()
    conn.close()
    
    if results:
        for file_name, file_id in results:
            await update.message.reply_document(
                document=file_id, 
                caption=f"✅ إليك المطلوب من الأرشيف الدائم:\n📁 {file_name}"
            )
    else:
        await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_file))

    print("بوت الأرشيف الذكي يعمل الآن...")
    application.run_polling()

if __name__ ==- "__main__":
    main()
