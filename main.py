import os
import telebot

TOKEN = os.getenv("TOKEN", "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8")
bot = telebot.TeleBot(TOKEN)

books_archive = {}


@bot.message_handler(commands=["start"])
def send_welcome(message):
  if message.chat.type != "private":
    return
  bot.reply_to(
      message,
      "أهلاً بك يا هندسة! 🚀\nأرسل لي أي ملف كتاب وسأقوم بأرشفته.\nللطلب أرسل:"
      " (اريد كتاب + اسم الكتاب).",
  )


@bot.message_handler(content_types=["document"])
def handle_document(message):
  if message.chat.type != "private":
    return

  file_name = message.document.file_name
  file_id = message.document.file_id

  if file_name in books_archive:
    bot.reply_to(message, f"⚠️ الكتاب ('{file_name}') موجود مسبقاً في الأرشيف.")
  else:
    books_archive[file_name] = file_id
    bot.reply_to(
        message, f"✅ تم إضافة وتخزين الكتاب ('{file_name}') بنجاح في الأرشيف!"
    )


@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  if message.chat.type != "private":
    return

  text = message.text
  if not text or text.startswith("/"):
    return

  text_lower = text.strip().lower()

  # تنظيف النص وحذف كلمات الطلب ليبقى اسم الكتاب الصافي فقط
  query = text_lower
  for prefix in ["اريد كتاب", "أريد كتاب", "اريد رواية", "أريد رواية"]:
    if query.startswith(prefix):
      query = query.replace(prefix, "").strip()
      break

  # البحث عن الكتاب في الأرشيف بناءً على جزء من الاسم الصافي
  found_file_id = None
  found_name = None
  for name, fid in books_archive.items():
    if query in name.lower():
      found_file_id = fid
      found_name = name
      break

  if found_file_id:
    bot.send_document(
        message.chat.id, found_file_id, caption=f"📚 ها هو كتابك: {found_name}"
    )
  else:
    bot.reply_to(
        message,
        f"❌ عذراً، لم يتم العثور على كتاب بهذا الاسم ('{query}') في الأرشيف.",
    )


bot.infinity_polling()
