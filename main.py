import os
import telebot

# استدعاء التوكن (يمكن وضعه مباشرة أو عبر متغيرات البيئة في Railway)
TOKEN = os.getenv("TOKEN", "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8")
bot = telebot.TeleBot(TOKEN)

# قاموس لتخزين الأرشيف (اسم الملف -> معرف الملف)
books_archive = {}


# 1. أمر الترحيب للبدء
@bot.message_handler(commands=["start"])
def send_welcome(message):
  if message.chat.type != "private":
    return
  bot.reply_to(
      message,
      "أهلاً بك يا هندسة! 🚀\nأرسل لي أي ملف كتاب (PDF) في المحادثة الخاصة وسأقوم"
      " بأرشفته وتخزينه فوراً.\n\nللطلب: فقط أرسل اسم الكتاب أو جزءاً منه وسأرسله"
      " لك مباشرة.",
  )


# 2. استقبال الملفات، منع التكرار، وإعطاء إشارة نجاح
@bot.message_handler(content_types=["document"])
def handle_document(message):
  if message.chat.type != "private":
    return

  file_name = message.document.file_name
  file_id = message.document.file_id

  # التحقق من وجود الكتاب مسبقاً لمنع التكرار
  if file_name in books_archive:
    bot.reply_to(
        message,
        f"⚠️ الكتاب ('{file_name}') موجود مسبقاً في الأرشيف ولم يتم تخزينه مرة"
        " أخرى.",
    )
    print(f"⚠️ محاولة رفع كتاب مكرر: {file_name}")
  else:
    # تخزين الكتاب وإرسال إشارة نجاح في المحادثة وفي الـ Logs
    books_archive[file_name] = file_id
    bot.reply_to(
        message, f"✅ تم إضافة وتخزين الكتاب ('{file_name}') بنجاح في الأرشيف!"
    )
    print(f"✅ تمت أرشفة الكتاب بنجاح: {file_name}")


# 3. البحث عن الكتاب وإرساله مباشرة عند طلبه
@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  if message.chat.type != "private":
    return

  text = message.text
  if not text or text.startswith("/"):
    return

  query = text.strip().lower()

  # البحث في الأرشيف بناءً على اسم الملف
  found_file_id = None
  found_name = None
  for name, fid in books_archive.items():
    if query in name.lower():
      found_file_id = fid
      found_name = name
      break

  # إرسال الكتاب أو الرد بعدم العثور عليه
  if found_file_id:
    bot.send_document(
        message.chat.id, found_file_id, caption=f"📚 ها هو كتابك: {found_name}"
    )
  else:
    bot.reply_to(
        message,
        f"❌ عذراً، لم يتم العثور على كتاب بهذا الاسم ('{text}') في الأرشيف.",
    )


# تشغيل البوت باستمرار على السيرفر
bot.infinity_polling()
