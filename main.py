import os
import telebot

# بيانات البوت والقناة
TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
CHANNEL_ID = "@ReadingCommunity_Library"

bot = telebot.TeleBot(TOKEN)

# قاموس لتخزين الأرشيف
CHANNEL_BOOKS = {}


# 1. أمر البداية للتأكد من أن البوت يعمل
@bot.message_handler(commands=["start"])
def send_welcome(message):
  bot.reply_to(
      message,
      "أهلاً بك! بوت مكتبة Reading Community يعمل الآن وجاهز لتلبية طلباتكم"
      " بالبحث عن الكتب.",
  )


# 2. أرشفة تلقائية لكل ما ينزل في قناتك الخاصة مع إرسال تنبيه في السجلات
@bot.channel_post_handler(func=lambda message: True)
def archive_channel_books(message):
  text = message.text or message.caption
  if text:
    clean_text = text.strip().lower()
    CHANNEL_BOOKS[clean_text] = message.message_id
    first_line = clean_text.split("\n")[0]
    CHANNEL_BOOKS[first_line] = message.message_id
    # تنبيه مؤكد يظهر في Deploy Logs على Railway فور أرشفة الكتاب
    print(f"✅ تمت أرشفة الكتاب بنجاح في الذاكرة: {first_line}")


# 3. الاستماع لطلبات الأعضاء
@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  text = message.text
  if not text:
    return

  text_lower = text.strip().lower()

  prefix = None
  if text_lower.startswith("اريد كتاب"):
    prefix = "اريد كتاب"
  elif text_lower.startswith("اريد رواية"):
    prefix = "اريد رواية"

  if prefix:
    book_name = text_lower.replace(prefix, "").strip()

    if not book_name:
      bot.reply_to(message, "يرجى كتابة اسم الكتاب بعد الطلب.")
      return

    # البحث في الأرشيف
    found_msg_id = None
    for title, msg_id in CHANNEL_BOOKS.items():
      if book_name in title:
        found_msg_id = msg_id
        break

    if found_msg_id:
      try:
        bot.forward_message(
            chat_id=message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=found_msg_id,
        )
      except Exception as e:
        bot.reply_to(
            message, "حدث خطأ أثناء محاولة إرسال الكتاب من القناة."
        )
    else:
      bot.reply_to(
          message,
          f"عذراً، لم أجد كتاباً بهذا الاسم ('{book_name}') في أرشيف القناة"
          " بعد.",
      )


# تشغيل البوت مباشرة
bot.infinity_polling()
