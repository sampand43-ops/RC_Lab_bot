import os
import re
from collections import defaultdict
import telebot
from telebot import types

# ضع توكن البوت الخاص بك هنا
TOKEN = 'YOUR_BOT_TOKEN_HERE'
bot = telebot.TeleBot(TOKEN)

# هنا يفترض أنك تقوم بربط قاعدة البيانات أو القائمة الخاصة بالكتب (مثلاً قائمة tuple تحتوي على الاسم والملف)
# مثال: books_database = [("كتاب كليلة ودمنة الجزء الأول", "file_id_1"), ...]
books_database = [] 

def normalize_arabic(text):
    """توحيد الحروف العربية لتسهيل عملية البحث ومطابقة العناوين"""
    if not text:
        return ""
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'[\u064b-\u0652]', '', text)  # إزالة التشكيل
    return text.strip()

def get_core_title(book_name):
    """استخراج العنوان الأساسي للكتاب مع إزالة أرقام الأجزاء أو النسخ المتطرفة"""
    # إزالة الأرقام بين قوسين هلالية مثل (1) في النهاية
    clean_name = re.sub(r'\s*\(\d+\)\s*$', '', book_name)
    # إزالة عبارات الأجزاء الشائعة لتجميعها معاً إذا لزم الأمر، أو الاحتفاظ بالاسم الأساسي
    return clean_name.strip()

def extract_part_number(book_name):
    """استخراج رقم الجزء إذا وجد في اسم الكتاب (سواء بجانبه رقم أو كلمة جزء/مجلد)"""
    # البحث عن نمط مثل "الجزء الأول"، "ج2"، أو رقم في نهاية الاسم بدون أقواس
    match_word = re.search(r'(?:الجزء|المجلد|ج)\s*([0-9٠-ي]+)', book_name)
    if match_word:
        part_str = match_word.group(1)
        # تحويل الأرقام العربية المشرقية إن وجدت إلى أرقام عادية
        return convert_arabic_numbers(part_str)
    
    # البحث عن رقم في نهاية الاسم بدون أقواس هلالية (مثل: كتاب الفلاحة 2)
    match_trailing = re.search(r'\b(?:الجز[ءأ]|ج)?\s*([0-9٠-ي]+)\s*$', book_name)
    if match_trailing:
        part_str = match_trailing.group(1)
        return convert_arabic_numbers(part_str)
        
    return None

def convert_arabic_numbers(text):
    """تحويل الأرقام الهندية/المشرقية إلى إنجليزية"""
    arabic_to_eng = {'٠':'0', '١':'1', '٢':'2', '٣':'3', '٤':'4', '٥':'5', '٦':'6', '٧':'7', '٨':'8', '٩':'9'}
    for ar, en in arabic_to_eng.items():
        text = text.replace(ar, en)
    try:
        return int(text)
    except ValueError:
        return None

def dedupe_exact(records):
    """إزالة النسخ المتطابقة تماماً"""
    seen = set()
    unique_list = []
    for item in records:
        # نفترض أن العنصر عبارة عن (اسم الكتاب، معرف الملف أو الرابط)
        identifier = (item[0], item[1])
        if identifier not in seen:
            seen.add(identifier)
            unique_list.append(item)
    return unique_list

def reduce_to_unique_parts(records, query_norm=""):
    """تصفية ذكية: الاحتفاظ بجميع الأجزاء للكتب متعددة الأجزاء، واستبعاد النسخ المكررة"""
    deduped = dedupe_exact(records)
    
    # تجميع حسب العنوان الأساسي
    groups = defaultdict(list)
    for item in deduped:
        book_name = item[0]
        base_key = get_core_title(book_name)
        groups[base_key].append(item)

    final_books = []
    for base_key, items in groups.items():
        if len(items) >= 1:
            # فحص ما إذا كان الكتاب يحتوي على أجزاء حقيقية متعددة
            has_parts = any(extract_part_number(item[0]) is not None for item in items)
            
            if has_parts:
                # إذا كان الكتاب متعدد الأجزاء، نقوم بترتيبها حسب رقم الجزء والاحتفاظ بكل الأجزاء المختلفة
                sorted_items = sorted(items, key=lambda x: extract_part_number(x[0]) or 0)
                seen_parts = set()
                unique_parts = []
                for item in sorted_items:
                    part_num = extract_part_number(item[0])
                    if part_num is not None:
                        if part_num in seen_parts:
                            continue
                        seen_parts.add(part_num)
                    unique_parts.append(item)
                final_books.extend(unique_parts)
            else:
                # للكتب العادية (غير متعددة الأجزاء)، نتخلص من النسخ المكررة ونختار نسخة واحدة مثالية
                exact_match_items = [it for it in items if normalize_arabic(get_core_title(it[0])) == query_norm]
                if exact_match_items and len(items) > 1:
                    best_item = min(exact_match_items, key=lambda x: len(x[0]))
                else:
                    best_item = min(items, key=lambda x: len(x[0]))
                final_books.append(best_item)
                
    return final_books

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في بوت مجتمع القراءة 📚\nأرسل اسم الكتاب للبحث عنه وسأقوم بإرساله لك.")

@bot.message_handler(func=lambda message: True)
def search_books(message):
    query = message.text.strip()
    query_norm = normalize_arabic(query)
    
    # محاكاة البحث في قاعدة البيانات (استبدل هذا بمنطق البحث الخاص بك)
    matched_records = []
    for book in books_database:
        book_title_norm = normalize_arabic(book[0])
        if query_norm in book_title_norm:
            matched_records.append(book)
            
    if not matched_records:
        bot.reply_to(message, "عذراً، لم أجد كتاباً بهذا الاسم 🔍")
        return

    # تطبيق الدالة الذكية المحدثة
    final_results = reduce_to_unique_parts(matched_records, query_norm)
    
    bot.reply_to(message, f"تم إرسال طلبك، استمتع بالقراءة! ✨")
    
    # إرسال النتائج للمستخدم
    for item in final_results:
        book_name = item[0]
        file_id = item[1] # قد يكون رابط أو معرف ملف تلغرام
        # bot.send_document(message.chat.id, file_id, caption=book_name)
        # كمثال نصي أو إرسال ملف حسب طبيعة مشروعك:
        bot.send_message(message.chat.id, f"📖 {book_name}")

if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling()
