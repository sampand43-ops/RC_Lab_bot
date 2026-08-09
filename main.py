import os
import sqlite3
import telebot

TOKEN = os.getenv("TOKEN", "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8")
CHANNEL_ID = "@ReadingCommunity_Library"

bot = telebot.TeleBot(TOKEN)

# --- مسار التخزين الدائم للبيانات على Railway ---
if os.path.exists("/app/data"):
  DB_PATH = "/app/data/books_archive.db"
elif os.path.exists("/data"):
  DB_PATH = "/data/books_archive.db"
else:
  DB_PATH = "books_archive.db"


# --- تهيئة قاعدة البيانات ---
def init_db():
  conn = sqlite3.connect(DB_PATH)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT UNIQUE,
            msg_id INTEGER
        )
    """)
  conn.commit()
  conn.close()


init_db()


def add_book_to_db(file_name, msg_id):
  conn = sqlite3.connect(DB_PATH)
  cursor = conn.cursor()
  try:
    cursor.execute(
        "INSERT OR IGNORE INTO books (file_name, msg_id) VALUES (?, ?)",
        (file_name, msg_id),
    )
    conn.commit()
  except Exception as e:
    print(f"خطأ: {e}")
  finally:
    conn.close()


def search_book_in_db(query):
  conn = sqlite3.connect(DB_PATH)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT file_name, msg_id FROM books WHERE file_name LIKE ?",
      (f"%{query}%",),
  )
  result = cursor.fetchone()
  conn.close()
  return result


# --- تعديل تجريبي في رسالة الـ start للتأكد من حدوث Redeploy لاحقاً ---
@bot.message_handler(commands=["start"])
def send_welcome(message):
  bot.reply_to(
      message,
      " أهلاً بك يا هندسة! هذا (الكود التجريبي) للتأكد من استقرار قاعدة"
      " البيانات الدائمة.\nأرسل اسم أي كتاب للبحث عنه.",
  )


# --- أرشفة الكتب من القناة ---
@bot.channel_post_handler(content_types=["document"])
def archive_from_channel(message):
  if message.document and message.document.file_name:
    file_name = message.document.file_name
    msg_id = message.message_id
    add_book_to_db(file_name, msg_id)
    print(f"✅ تم حفظ الكتاب تجريبياً: {file_name}")


# --- استقبال الطلبات والبحث ---
@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  text = message.text
  if not text or text.startswith("/"):
    return

  query = text.strip().lower()
  for prefix in ["اريد كتاب", "أريد كتاب", "اريد رواية", "أريد رواية"]:
    if query.startswith(prefix):
      query = query.replace(prefix, "").strip()
      break

  if not query:
    return

  book_result = search_book_in_db(query)

  if book_result:
    found_name, found_msg_id = book_result
    try:
      bot.forward_message(
          chat_id=message.chat.id,
          from_chat_id=CHANNEL_ID,
          message_id=found_msg_id,
      )
    except Exception as e:
      bot.reply_to(
          message, "❌ حدث خطأ في جلب الكتاب، تأكد أن البوت مشرف في القناة."
      )
  else:
    bot.reply_to(message, f"❌ عذراً، الكتاب ('{query}') غير موجود في الأرشيف.")


bot.infinity_polling()
