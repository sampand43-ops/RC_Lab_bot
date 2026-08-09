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

# مسار التخزين الدائم على Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

# تهيئة قاعدة البيانات لحفظ الملفات بشكل دائم
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
        "• أرسل أي ملف (كتاب، مستند) ليتم حفظه في الأرشيف الدائم.\n"
        "• أو أرسل اسم الكتاب نصياً للبحث عنه واسترجاعه فوراً."
    )

# دالة استقبال الملفات وحفظها في قاعدة البيانات الدائمة
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    document = message.document or message.video or message.audio
    
    if document:
        file_id = document.file_id
        file_name = document.file_name or "Unknown_File"
        
        # حفظ بيانات الملف في قاعدة البيانات الموجودة في Volume
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO files (file_name, file_id, file_type) VALUES (?, ?, ?)",
            (file_name, file_id, "document")
        )
        conn.commit()
        conn.close()
        
        await message.reply_text(f"تم حفظ الملف الآتي في الأرشيف الدائم بنجاح:\n📁 {file_name}")

# دالة البحث عن الملفات عند إرسال اسم الكتاب نصياً
async def search_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # البحث عن الملفات التي تحتوي على النص المدخل
    cursor.execute("SELECT file_name, file_id FROM files WHERE file_name LIKE ?", (f"%{query}%",))
    results = cursor.fetchall()
    conn.close()
    
    if results:
        for file_name, file_id in results:
            await update.message.reply_document(
                document=file_id, 
                caption=f"✅ إليك الملف المطلوب من الأرشيف الدائم:\n📁 {file_name}"
            )
    else:
        await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب بهذا الاسم ('{query}') في الأرشيف.")

def main():
    # تجهيز قاعدة البيانات عند الإقلاع
    init_db()
    
    # التوكن الخاص بك
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    
    application = ApplicationBuilder().token(TOKEN).build()

    # ربط الأوامر والدوال
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_file))

    print("بوت الأرشيف يعمل الآن مع ميزة البحث والتخزين الدائم...")
    application.run_polling()

if __name__ == "__main__":
    main()
