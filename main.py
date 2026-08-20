import re
from collections import defaultdict
import telebot

# ضع هنا توكن البوت الخاص بك
TOKEN = 'YOUR_BOT_TOKEN_HERE'
bot = telebot.TeleBot(TOKEN)

# دالة تطبيع النص العربي لإزالة الفروق الإملائية
def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'[\u064b-\u0652]', '', text) # إزالة التشكيل
    return text.strip()

# دالة لإزالة النسخ المكررة تماماً
def dedupe_exact(records):
    seen = set()
    unique_records = []
    for item in records:
        # افتراض أن العنصر عبارة عن (اسم_الكتاب، معرف_الملف/الرسالة، ...)
        name = item[0]
        if name not in seen:
            seen.add(name)
            unique_records.append(item)
    return unique_records

# استخراج العنوان الأساسي للكتاب بإزالة الأجزاء والزوائد
def get_core_title(book_name):
    # إزالة الأجزاء المكتوبة صراحة أو الأرقام في النهاية للتجميع
    cleaned = re.sub(r'(?:الجزء|مجلد|ج\.?)\s*([0-9١-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)', '', book_name, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\s\-]+([0-9١-٩]+)\s*(?:\.pdf)?$', '', cleaned)
    return normalize_arabic(cleaned)

# دالة استخراج رقم الجزء (تدعم الألفاظ، الكلمات، والأرقام المنفصلة في النهاية بدون أقواس)
def extract_part_number(book_name):
    # البحث عن كلمات تدل على الجزء صراحة
    part_word_match = re.search(r'(?:الجزء|مجلد|ج\.?)\s*([0-9١-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)', book_name, re.IGNORECASE)
    if part_word_match:
        val = part_word_match.group(1)
        word_to_num = {
            'الأول': 1, 'الثاني': 2, 'الثالث': 3, 'الرابع': 4, 'الخامس': 5,
            'السادس': 6, 'السابع': 7, 'الثامن': 8, 'التاسع': 9, 'العاشر': 10
        }
        return word_to_num.get(val, int(val) if val.isdigit() else 1)

    # البحث عن رقم في نهاية الاسم بدون أقواس هلالية
    end_num_match = re.search(r'[\s\-]+([0-9١-٩]+)\s*(?:\.pdf)?$', book_name)
    if end_num_match:
        num_str = end_num_match.group(1)
        # التأكد أنه ليس بداخله أقواس مسبقة مثل (1)
        if not re.search(r'\(\s*' + num_str + r'\s*\)', book_name):
            try:
                return int(num_str)
            except ValueError:
                pass
            
    return None

# دالة تصفية النتائج والاحتفاظ بجميع الأجزاء الفريدة ومنع التكرار
def reduce_to_unique_parts(records, query_norm=""):
    deduped = dedupe_exact(records)
    
    groups = defaultdict(list)
    for item in deduped:
        book_name = item[0]
        base_key = get_core_title(book_name)
        groups[base_key].append(item)

    final_books = []
    for base_key, items in groups.items():
        parts_dict = {}
        no_part_items = []
        
        for item in items:
            p_num = extract_part_number(item[0])
            if p_num is not None:
                if p_num not in parts_dict:
                    parts_dict[p_num] = item
                else:
                    # الاحتفاظ بالنسخة ذات الاسم الأقصر أو الأدق إذا تكرر نفس الجزء
                    if len(item[0]) < len(parts_dict[p_num][0]):
                        parts_dict[p_num] = item
            else:
                no_part_items.append(item)
                
        if len(parts_dict) > 0:
            # إذا وجدنا أجزاء متعددة، نقوم بترتيبها تصاعدياً حسب رقم الجزء وإضافتها كلها
            sorted_parts = [parts_dict[p] for p in sorted(parts_dict.keys())]
            final_books.extend(sorted_parts)
            if no_part_items:
                final_books.append(min(no_part_items, key=lambda x: len(x[0])))
        else:
            # للكتب غير متعددة الأجزاء، نختار نسخة واحدة مثالية فقط
            if items:
                best_item = min(items, key=lambda x: len(x[0]))
                final_books.append(best_item)
                
    return final_books

# مثال على معالج الرسائل في البوت عند البحث عن كتاب
@bot.message_handler(func=lambda message: True)
def handle_book_search(message):
    query = message.text.strip()
    query_norm = normalize_arabic(query)
    
    # محاكاة جلب النتائج من قاعدة البيانات أو القناة (كل عنصر عبارة عن [اسم_الكتاب، معرف_الملف])
    # raw_records = database.search(query)
    raw_records = [] # ضع هنا قائمة النتائج المستخرجة من بحثك
    
 تطبيق دالة التصفية الذكية للأجزاء ومنع التكرار
    filtered_books = reduce_to_unique_parts(raw_records, query_norm)
    
    if not filtered_books:
        bot.reply_to(message, "عذراً، لم يتم العثور على كتاب بهذا الاسم.")
        return
        
    # إرسال الكتب أو الأجزاء تباعاً
    for book in filtered_books:
        book_name = book[0]
        file_id = book[1] # معرف الملف على تيليجرام
        
        bot.send_document(message.chat.id, file_id, caption=f"📚 {book_name}\n✨ تفضل، قراءة ممتعة!")

if __name__ == '__main__':
    print("Bot is running...")
    bot.polling(none_stop=True)
