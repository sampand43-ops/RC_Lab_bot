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
        "• البوت يسحب الكتب وينسخها من القناة تلقائياً ويحفظها في الأرشيف الدائم.\n"
        "• أرسل اسم الكتاب نصياً للبحث عنه واسترجاعه فوراً."
    )

# دالة الاستماع للمنشورات الجديدة في القناة وحفظها تلقائياً
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message:
        document = message.document or message.video or message.audio
        if document:
            file_id = document.file_id
            file_name = document.file_name or message.caption or "Unknown_File"
            
            # حفظ الملف في قاعدة البيانات الدائمة في الـ Volume
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO files (file_name, file_id, file_type) VALUES (?, ?, ?)",
                (file_name, file_id, "document")
            )
            conn.commit()
            conn.close()

# دالة البحث واسترجاع الكتب للمستخدمين
async def search_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # البحث بمرونة عن اسم الكتاب داخل الأرشيف الدائم
    cursor.execute("SELECT file_name, file_id FROM files WHERE file_name LIKE ?", (f"%{query}%",))
    results = cursor.fetchall()
    conn.close()
    
    if results:
        for file_name, file_id in results:
            await update.message.reply_document(
                document=file_id, 
                caption=f"✅ إليك الكتاب المطلوب من الأرشيف الدائم:\n📁 {file_name}"
            )
    else:
        await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب بهذا الاسم ('{query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    # التقاط المنشورات الجديدة من القنوات التي يكون البوت مشرفاً فيها
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    # البحث في الرسائل الخاصة للمستخدمين
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, search_file))

    print("بوت الأرشيف المتزامن مع القناة يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
