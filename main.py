import os
import telebot

# بيانات البوت والقناة المباشرة
TOKEN = "8619586974:AAE9iQg0BBfswqIgBH5do4XSm2HqiiZQWIk"
CHANNEL_ID = "@ReadingCommunity_Library"

bot = telebot.TeleBot(TOKEN)

# قاموس بسيط لتخزين الأرشيف (اسم الكتاب -> معرف الرسالة في القناة)
CHANNEL_BOOKS = {}


# 1. أرشفة تلقائية لكل ما ينزل في قناتك الخاصة (البوت مشرف هنا)
@bot.channel_post_handler(func=lambda message: True)
def archive_channel_books(message):
  text = message.text or message.caption
  if text:
    clean_text = text.strip().lower()
    CHANNEL_BOOKS[clean_text] = message.message_id
    first_line = clean_text.split("\n")[0]
    CHANNEL_BOOKS[first_line] = message.message_id


# 2. الاستماع لطلبات الأعضاء (في المجموعة يكفي أن يكون عضواً عادياً وفي الخاص)
@bot.message_handler(func=lambda message: True)
def handle_book_requests(message):
  text = message.text
  if not text:
    return

  text_lower = text.strip().lower()

  # التحقق من الكلمات المفتاحية المطلوبة
  prefix = None
  if text_lower.startswith("اريد كتاب"):
    prefix = "اريد كتاب"
  elif text_lower.startswith("اريد رواية"):
    prefix = "اريد رواية"

  if prefix:
    # استخراج اسم الكتاب المكتوب بعد الجملة
    book_name = text_lower.replace(prefix, "").strip()

    if not book_name:
      return  # إذا لم يكتب اسم الكتاب، لا تفعل شيئاً

    # البحث في الأرشيف
    found_msg_id = None
    for title, msg_id in CHANNEL_BOOKS.items():
      if book_name in title:
        found_msg_id = msg_id
        break

    # إذا وجدنا الكتاب نقوم بتحويله، وإذا لم نجد لا نرسل أي شيء نهائياً
    if found_msg_id:
      try:
        bot.forward_message(
            chat_id=message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=found_msg_id,
        )
      except Exception as e:
        pass


if  name  == "  main  ":
  print("البوت يعمل الآن ببساطة...")
  bot.infinity_polling()
