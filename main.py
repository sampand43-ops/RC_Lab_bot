import telebot

# ضع توكن البوت الخاص بك هنا
TOKEN = 'YOUR_BOT_TOKEN'
bot = telebot.TeleBot(TOKEN)

# قاعدة بيانات مؤقتة لتخزين معلومات الكتب (يمكنك استبدالها بقاعدة بيانات حقيقية لاحقاً)
# المفتاح: اسم الملف أو معرفه، القيمة: file_id الخاص بتليجرام
books_archive = {}

# استقبال الملفات في المحادثة الخاصة فقط
@bot.message_handler(content_types=['document'])
fcn
def handle_document(message):
    # التأكد أن المحادثة خاصة (Private Chat)
    if message.chat.type != 'private':
        return

    file_name = message.document.file_name
    file_id = message.document.file_id

    # التحقق من تكرار الكتاب
    if file_name in books_archive:
        bot.reply_to(message, f"⚠️ الكتاب '{file_name}' موجود مسبقاً في الأرشيف ولم يتم تخزينه مرة أخرى.")
    else:
        # تخزين الكتاب
        books_archive[file_name] = file_id
        bot.reply_to(message, f"✅ تم إضافة الكتاب '{file_name}' بنجاح إلى الأرشيف!")

# أمر للبحث عن كتاب وإرساله مباشرة عند طلبه
@bot.message_handler(commands=['get', 'book', 'بحث'])
def send_book(message):
    if message.chat.type != 'private':
        return

    # استخلاص اسم الكتاب المطلوب بعد الأمر
    query = message.text.replace('/get', '').replace('/book', '').replace('/بحث', '').strip()
    
    if not query:
        bot.reply_to(message, "الرجاء كتابة اسم الكتاب مع الأمر، مثال:\n/book python_guide.pdf", parse_mode='Markdown')
        return

    # البحث عن الكتاب في الأرشيف
    found_file_id = None
    found_name = None
    for name, fid in books_archive.items():
        if query.lower() in name.lower():
            found_file_id = fid
            found_name = name
            break

    if found_file_id:
        bot.send_document(message.chat.id, found_file_id, caption= ها هو كتاب: {found_name} 📚")
    else:
        bot.reply_to(message, "❌ عذراً، لم يتم العثور على كتاب بهذا الاسم في الأرشيف.")

# تشغيل البوت
bot.infinity_polling()
