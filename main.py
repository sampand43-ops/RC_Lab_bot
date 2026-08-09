import os
import telebot

TOKEN = os.getenv("TOKEN", "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8")
CHANNEL_ID = "@ReadingCommunity_Library"  # ضع معرف قناتك هنا

bot = telebot.TeleBot(TOKEN)

# قاموس لتخزين اسم الكتاب ومعرف الرسالة الخاص به في القناة
channel_books_archive = {}


@bot.message_handler(commands=["start"])
def send_welcome(message):
  if message.chat.type != "private":
    return
  bot.reply_to(
      message,
      "أهلاً بك يا هندسة! 🚀\nهذا البوت يسحب الكتب مباشرة من القناة.\nللطلب أرسل:"
      " (اريد كتاب + اسم الكتاب).",
  )


# 1. أرشفة الكتب تلقائياً من القناة (يجب أن يكون البوت مشرفاً في القناة)
@bot.channel_post_handler(content_types=["document"])
def archive_from_channel(message):
  file_name = message.document.file_name
  msg_id = message.message_id

  if file_name in channel_books_archive:
    print(f"⚠️ الكتاب ('{file_name}') موجود مسبقاً في أرشيف القناة.")
  else:
    channel_books_archive[file_name] = msg_id
    print(
        f"✅ تم ربط الكتاب ('{file_name}') من القناة بنجاح (Message ID:"
        f" {msg_id})"
    )


# 2. الاستماع لطلبات الكتب وإرسالها مباشرة من القناة للمستخدم
@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  if message.chat.type != "private":
    return

  text = message.text
  if not text or text.startswith("/"):
    return

  text_lower = text.strip().lower()

  # تنظيف النص وحذف كلمات الطلب ليبقى اسم الكتاب الصافي
  query = text_lower
  for prefix in ["اريد كتاب", "أريد كتاب", "اريد رواية", "أريد رواية"]:
    if query.startswith(prefix):
      query = query.replace(prefix, "").strip()
      break

  # البحث عن الكتاب في أرشيف القناة
  found_msg_id = None
  found_name = None
  for name, msg_id in channel_books_archive.items():
    if query in name.lower():
      found_msg_id = msg_id
      found_name = name
      break

  if found_msg_id:
    try:
      # إرسال الكتاب مباشرة عن طريق تحويله من القناة إلى المستخدم
      bot.forward_message(
          chat_id=message.chat.id,
          from_chat_id=CHANNEL_ID,
          message_id=found_msg_id,
      )
    except Exception as e:
      bot.reply_to(
          message,
          "❌ حدث خطأ أثناء محاولة جلب الكتاب من القناة. تأكد أن البوت مشرف"
          " فيها.",
      )
  else:
    bot.reply_to(
        message,
        f"❌ عذراً، لم يتم العثور على كتاب بهذا الاسم ('{query}') في أرشيف"
        " القناة.",
    )


bot.infinity_polling()
