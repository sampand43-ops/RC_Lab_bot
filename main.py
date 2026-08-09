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

# مسار التخزين الدائم الذي قمنا بإنبرئه وربطه في Railway
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

# تهيئة قاعدة البيانات لحفظ الملفات والروابط بشكل دائم
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
        "أرسل أي ملف (كتاب، مستند، إلخ) ليتم حفظه في الأرشيف الدائم."
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

def main():
    # تجهيز قاعدة البيانات عند الإقلاع
    init_db()
    
    # قراءة توكن البوت من متغيرات البيئة في Railway
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("خطأ: يرجى ضبط متغير البيئة BOT_TOKEN في إعدادات Railway.")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # ربط الأوامر والدوال
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_document))

    print("بوت الأرشيف يعمل الآن ومربوط بالتخزين الدائم...")
    application.run_polling()

if __name__ == "__main__":
    main()
