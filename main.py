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

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            file_id TEXT UNIQUE,
            file_type TEXT
        )
    """)
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك يا هندسة في بوت أرشيف المعمل والملفات! 📚🤖\n"
        "• لحفظ الكتب: قم بتحويلها (Forward) من القناة إلى هنا (لن يتم تكرار حفظ الملفات المتطابقة).\n"
        "• للبحث: اكتب اسم الكتاب وسأرسل لك نسخة واحدة فريدة منه فوراً."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    document = message.document or message.video or message.audio
    
    if document:
        file_id = document.file_id
        file_name = document.file_name or "Unknown_File"
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO files (file_name, file_id, file_type) VALUES (?, ?, ?)",
                (file_name, file_id, "document")
            )
            conn.commit()
            await message.reply_text(f"✅ تم حفظ الكتاب في الأرشيف الدائم بنجاح:\n📁 {file_name}")
        except sqlite3.IntegrityError:
            await message.reply_text("ℹ️ هذا الملف موجود مسبقاً في الأرشيف ولا يمكن تكراره.")
        finally:
            conn.close()

async def search_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # جلب النتائج مع استخدام DISTINCT و GROUP BY على file_id لمنع جلب الملفات المكررة نهائياً
    cursor.execute("SELECT file_name, file_id FROM files WHERE file_name LIKE ? GROUP BY file_id LIMIT 1", (f"%{clean_query}%",))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        file_name, file_id = result
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

    print("بوت الأرشيف الذكي (بدون تكرار) يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
