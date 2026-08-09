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
        "• البوت يسحب الكتب الجديدة من القناة تلقائياً فور نشرها.\n"
        "• للبحث: اكتب (أريد كتاب [اسم الكتاب]) وسأقوم بإعادة توجيهه إليك مباشرة من القناة بدون تكرار!"
    )

# دالة السحب التلقائي من القناة فور نشر أي كتاب جديد (يجب أن يكون البوت مشرفاً في القناة)
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
                pass # الكتاب مسجل مسبقاً، نتجاهله لتجنب التكرار
            finally:
                conn.close()

# دالة البحث وإعادة التوجيه المباشر للمستخدم
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
    # جلب نتيجة واحدة فريدة حصراً بناءً على رقم الرسالة لمنع أي تكرار
    cursor.execute("SELECT book_name, msg_id FROM archive WHERE book_name LIKE ? GROUP BY msg_id LIMIT 1", (f"%{clean_query}%",))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        book_name, msg_id = result
        try:
            # إعادة توجيه الرسالة الأصلية من القناة مباشرة للمستخدم
            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id
            )
        except Exception as e:
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على الرسالة في القناة. تأكد أن البوت مشرف ولديه صلاحيات.")
    else:
        await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    # الاستماع التلقائي لمنشورات القناة
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    # البحث النصي في الخاص وإعادة التوجيه
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, search_and_forward))

    print("بوت السحب التلقائي والتوجيه المباشر يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
