import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تحديد مسار قاعدة البيانات داخل المجلد الدائم Volume
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "bot_database.db")

# تهيئة قاعدة البيانات SQLite
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    conn.commit()
    conn.close()

# أمر البدء /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # حفظ المستخدم في قاعدة البيانات الدائمة
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                   (user.id, user.username))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"أهلاً بك يا هندسة! 🤖\nتم حفظ بياناتك بنجاح في التخزين الدائم على Railway."
    )

def main():
    # تشغيل قاعدة البيانات أولاً
    init_db()
    
    # ضع توكن البوت هنا أو عبر متغيرات البيئة Environment Variables
    TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    
    print("البوت يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
