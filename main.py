import os
import sqlite3
import re
import time
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "8894946170:AAGaFTsSs1WXB_6Fio-SzzG03wTLVsfh8oM"
CHANNEL_ID = -1004395670008

# معرف الحساب الخاص بك كمشرف
ADMIN_IDS = [7898871921]

# بيانات المجموعة
GROUP_NAME = "مجتمع القراءة"
GROUP_LINK = "https://t.me/reading_community_group"

DATA_DIR = "/app/data"
if os.path.exists(DATA_DIR):
    DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")
else:
    DB_PATH = "archive_bot.db"

bot = telebot.TeleBot(TOKEN)

# قاموس لحفظ الكتب المحددة للحذف لكل مشرف
user_selections = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            part_num INTEGER,
            msg_id INTEGER UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            norm_name TEXT UNIQUE,
            original_name TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def normalize_name(text):
    if not text:
        return ""
    text = re.sub(r'\.(pdf|epub|zip|rar|txt|doc|docx)$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\u064b-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

ARABIC_NUM_WORDS = {
    'الأول': 1, 'اول': 1, '1': 1,
    'الثاني': 2, 'ثاني': 2, '2': 2,
    'الثالث': 3, 'ثالث': 3, '3': 3,
    'الرابع': 4, 'رابع': 4, '4': 4,
    'الخامس': 5, 'خامس': 5, '5': 5,
    'السادس': 6, 'سادس': 6, '6': 6,
    'السابع': 7, 'سابع': 7, '7': 7,
    'الثامن': 8, 'ثامن': 8, '8': 8,
    'التاسع': 9, 'تاسع': 9, '9': 9,
    'العاشر': 10, 'عاشر': 10, '10': 10,
}

def extract_part_number(filename):
    match = re.search(r'(الجزء|المجلد|جـ?|مجلد|part|vol)\s*([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)', filename, re.IGNORECASE)
    if match:
        val = match.group(2)
        if val in ARABIC_NUM_WORDS:
            return ARABIC_NUM_WORDS[val]
        val_en = val.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val_en.isdigit():
            return int(val_en)
            
    num_match = re.search(r'[\s\-_]([0-9٠-٩]+|\d+)\s*(?:\.pdf|\.epub|\.zip)?$', filename)
    if num_match:
        val = num_match.group(1).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        if val.isdigit():
            return int(val)
            
    return 1

# --- لوحة تحكم المشرفين الرئيسية ---
def get_admin_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    btn_list = InlineKeyboardButton("قائمة المستثنيات", callback_data="btn_allowed_list")
    btn_add = InlineKeyboardButton("إضافة كتاب مستثنى", callback_data="btn_allow")
    btn_del = InlineKeyboardButton("إدارة وحذف الأرشيف", callback_data="btn_del_book")
    
    markup.add(btn_list, btn_add)
    markup.add(btn_del)
    return markup

# --- بناء لوحة الحذف المتعدد للأرشيف ---
def build_archive_del_keyboard(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(id), book_name FROM archive GROUP BY book_name ORDER BY MIN(id) DESC LIMIT 30")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None, "الأرشيف فارغ حالياً، لا توجد كتب مخزنة."

    selected_set = user_selections.get(user_id, set())
    markup = InlineKeyboardMarkup(row_width=1)

    for b_id, b_name in rows:
        norm_name = normalize_name(b_name)
        is_selected = norm_name in selected_set
        icon = "[x]" if is_selected else "[ ]"
        markup.add(InlineKeyboardButton(f"{icon} {b_name}", callback_data=f"dt_{b_id}"))

    sel_count = len(selected_set)
    delete_btn_label = f"حذف العناصر المحددة ({sel_count})" if sel_count > 0 else "تحديد عناصر للحذف"
    markup.add(InlineKeyboardButton(delete_btn_label, callback_data="d_exec"))
    markup.add(InlineKeyboardButton("مسح وشطب الأرشيف بالكامل", callback_data="d_all_conf"))
    markup.add(InlineKeyboardButton("القائمة الرئيسية", callback_data="admin_menu"))

    msg_text = (
        "*إدارة وحذف كتب الأرشيف*\n"
        "━━━━━━━\n"
        "• حدد الكتب المراد إزالتها بالضغط عليها `[x]`.\n"
        "• اضغط على *زر حذف العناصر المحددة* لتنفيذ الحذف فوراً.\n"
        "• أو اختر مسح الأرشيف بالكامل لتصفية القاعدة."
    )
    return markup, msg_text

# --- رسالة البداية /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.from_user.id in ADMIN_IDS:
        welcome_text = (
            "أهلاً بك في بوت حراسة القناة والأرشيف:\n"
            "• أعمل تلقائياً على فحص منشورات القناة لمنع التكرار مع حفظ باقي الأجزاء.\n\n"
            "*لوحة تحكم المشرفين:* اختر من الأزرار أدناه:"
        )
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    else:
        restricted_text = (
            f"عذراً، هذا البوت خاص فقط بـ [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي.\n\n"
            f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
        )
        bot.reply_to(message, restricted_text, parse_mode="Markdown", disable_web_page_preview=True)

# --- معالجة الضغط على الأزرار الشفافة ---
@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call):
    user_id = call.from_user.id
    if user_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "هذه اللوحة مخصصة للمشرفين فقط.")
        return

    # 1. العودة للوحة الرئيسية
    if call.data == "admin_menu":
        bot.answer_callback_query(call.id)
        user_selections[user_id] = set()
        bot.edit_message_text(
            "أهلاً بك في بوت حراسة القناة والأرشيف:\n"
            "• أعمل تلقائياً على فحص منشورات القناة لمنع التكرار مع حفظ باقي الأجزاء.\n\n"
            "*لوحة تحكم المشرفين:* اختر من الأزرار أدناه:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    # 2. عرض قائمة الكتب المستثناة
    elif call.data in ["btn_allowed_list", "refresh_allowed"]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, original_name FROM allowed_books")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            bot.answer_callback_query(call.id, "لا توجد كتب مستثناة حالياً.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        markup = InlineKeyboardMarkup(row_width=1)
        for b_id, b_name in rows:
            markup.add(InlineKeyboardButton(f"إلغاء استثناء: {b_name}", callback_data=f"unallow_id_{b_id}"))
        markup.add(InlineKeyboardButton("القائمة الرئيسية", callback_data="admin_menu"))

        bot.edit_message_text(
            "*قائمة الكتب المستثناة من الفحص والتكرار:*\n"
            "━━━━━━━\n"
            "اضغط على اسم الكتاب لإلغاء استثنائه:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )

    # 3. تنفيذ إلغاء الاستثناء
    elif call.data.startswith("unallow_id_"):
        b_id = int(call.data.split("_")[2])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT original_name FROM allowed_books WHERE id = ?", (b_id,))
        res = cursor.fetchone()
        
        if res:
            b_name = res[0]
            cursor.execute("DELETE FROM allowed_books WHERE id = ?", (b_id,))
            conn.commit()
            bot.answer_callback_query(call.id, f"تم إلغاء استثناء: {b_name}", show_alert=True)
            
        conn.close()
        
        handle_inline_buttons(telebot.types.CallbackQuery(
            id=call.id, from_user=call.from_user, data="refresh_allowed",
            message=call.message, chat_instance=call.chat_instance
        ))

    # 4. إضافة استثناء جديد
    elif call.data == "btn_allow":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "*أرسل اسم الكتاب المطلوب إضافته للاستثناءات:*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_allow)

    # 5. فتح لوحة إدارة الأرشيف الحالية
    elif call.data == "btn_del_book":
        bot.answer_callback_query(call.id)
        user_selections[user_id] = set()
        markup, text = build_archive_del_keyboard(user_id)
        if not markup:
            bot.answer_callback_query(call.id, text, show_alert=True)
            return
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 6. تحديد / إلغاء تحديد كتاب للحذف
    elif call.data.startswith("dt_"):
        b_id = int(call.data.split("_")[1])
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT book_name FROM archive WHERE id = ?", (b_id,))
        res = cursor.fetchone()
        conn.close()

        if res:
            norm_name = normalize_name(res[0])
            if user_id not in user_selections:
                user_selections[user_id] = set()
            
            if norm_name in user_selections[user_id]:
                user_selections[user_id].remove(norm_name)
                bot.answer_callback_query(call.id, f"تم إزالة: {res[0]}")
            else:
                user_selections[user_id].add(norm_name)
                bot.answer_callback_query(call.id, f"تم تحديد: {res[0]}")

            markup, text = build_archive_del_keyboard(user_id)
            if markup:
                bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 7. تنفيذ حذف الكتب المحددة
    elif call.data == "d_exec":
        selected_set = user_selections.get(user_id, set())
        if not selected_set:
            bot.answer_callback_query(call.id, "يرجى تحديد كتاب واحد على الأقل.", show_alert=True)
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, book_name FROM archive")
        all_recs = cursor.fetchall()
        
        ids_to_delete = []
        for r_id, b_n in all_recs:
            if normalize_name(b_n) in selected_set:
                ids_to_delete.append((r_id,))

        if ids_to_delete:
            cursor.executemany("DELETE FROM archive WHERE id = ?", ids_to_delete)
            conn.commit()

        conn.close()

        bot.answer_callback_query(call.id, f"تم حذف {len(selected_set)} كتاب من الأرشيف بنجاح.", show_alert=True)
        user_selections[user_id] = set()

        markup, text = build_archive_del_keyboard(user_id)
        if markup:
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text("*تم إفراغ الأرشيف بالكامل.*", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=get_admin_keyboard())

    # 8. تأكيد حذف الأرشيف بالكامل
    elif call.data == "d_all_conf":
        bot.answer_callback_query(call.id)
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("تأكيد مسح الأرشيف بالكامل", callback_data="d_all_do"))
        markup.add(InlineKeyboardButton("إلغاء وتراجع", callback_data="btn_del_book"))

        bot.edit_message_text(
            "*تنبيه حرج وإجراء غير قابل للرجوع!*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "هل أنت متأكد من رغبتك في **مسح وشطب جميع بيانات الأرشيف** بالكامل؟",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )

    # 9. تنفيذ حذف الكل
    elif call.data == "d_all_do":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()

        user_selections[user_id] = set()
        bot.answer_callback_query(call.id, "تم مسح الأرشيف بالكامل.", show_alert=True)
        bot.edit_message_text(
            "*لوحة تحكم المشرفين:* (تم تفريغ الأرشيف بنجاح)",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

# --- معالجة إضافة كتاب مستثنى جديد ---
def process_add_allow(message):
    book_name = message.text.strip()
    norm_name = normalize_name(book_name)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO allowed_books (norm_name, original_name) VALUES (?, ?)", (norm_name, book_name))
        conn.commit()
        bot.reply_to(message, f"تم استثناء الكتاب: *{book_name}* بنجاح.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    except sqlite3.IntegrityError:
        bot.reply_to(message, f"الكتاب *{book_name}* موجود بالفعل في قائمة الاستثناءات.", parse_mode="Markdown", reply_markup=get_admin_keyboard())
    finally:
        conn.close()

# --- حراسة القناة عند نشر الملفات ---
@bot.channel_post_handler(content_types=['document', 'video', 'audio'])
def channel_guard(message):
    msg_id = message.message_id
    document = message.document or message.video or message.audio
    
    if document:
        book_name = document.file_name or message.caption or "Unknown_Book"
        norm_new_name = normalize_name(book_name)
        part_num = extract_part_number(book_name)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM allowed_books WHERE norm_name = ?", (norm_new_name,))
        is_allowed = cursor.fetchone()
        
        if is_allowed:
            try:
                cursor.execute(
                    "INSERT INTO archive (book_name, part_num, msg_id) VALUES (?, ?, ?)",
                    (book_name, part_num, msg_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()
            print(f"تم السماح بنشر الكتاب المستثنى: {book_name}")
            return

        cursor.execute("SELECT book_name, part_num FROM archive")
        all_records = cursor.fetchall()
        
        is_duplicate = False
        for db_book, db_part in all_records:
            if normalize_name(db_book) == norm_new_name and db_part == part_num:
                is_duplicate = True
                break
        
        if is_duplicate:
            try:
                bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
                print(f"تم حذف الكتاب المكرر بنجاح: {book_name}")
            except Exception as e:
                print(f"خطأ أثناء حذف الرسالة: {e}")
        else:
            try:
                cursor.execute(
                    "INSERT INTO archive (book_name, part_num, msg_id) VALUES (?, ?, ?)",
                    (book_name, part_num, msg_id)
                )
                conn.commit()
                print(f"تمت إضافة كتاب جديد للأرشيف: {book_name}")
            except sqlite3.IntegrityError:
                pass
        
        conn.close()

# --- التعامل مع الرسائل في الخاص ---
@bot.message_handler(func=lambda message: True)
def search_and_forward(message):
    if message.chat.type == 'channel':
        return
        
    # تقييد الاستخدام للأدمن فقط
    if message.from_user.id not in ADMIN_IDS:
        restricted_text = (
            f"عذراً، هذا البوت خاص فقط بـ [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي."
        )
        bot.reply_to(message, restricted_text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    text = message.text.strip()
    if text.startswith('/'):
        return

    clean_query = text
    phrases_to_remove = ["اريد كتاب", "أريد كتاب", "اريد", "أريد", "كتاب", "رواية"]
    phrases_to_remove = sorted(phrases_to_remove, key=len, reverse=True)
    
    for phrase in phrases_to_remove:
        if clean_query.startswith(phrase):
            clean_query = clean_query[len(phrase):].strip()
            break
            
    if not clean_query:
        clean_query = text

    norm_query = normalize_name(clean_query)

    # التحقق من أن كلمة البحث ليست فارغة أو عبارة عن رموز فقط
    if not norm_query or len(norm_query) < 2:
        if message.chat.type == 'private':
            bot.reply_to(message, "يرجى كتابة اسم كتاب أو كلمة بحث صالحة تحتوي على أحرف.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    results = []
    
    for book_name, msg_id in all_records:
        norm_name = normalize_name(book_name)
        if norm_name.startswith(norm_query):
            results.append((book_name, msg_id))
    
    if results:
        sorted_results = sorted(results, key=lambda x: extract_part_number(x[0]))
        seen_names = set()
        unique_results = []
        
        for book_name, msg_id in sorted_results:
            key_name = normalize_name(book_name)
            if key_name not in seen_names:
                seen_names.add(key_name)
                unique_results.append((book_name, msg_id))

        for book_name, msg_id in unique_results:
            try:
                bot.forward_message(chat_id=message.chat.id, from_chat_id=CHANNEL_ID, message_id=msg_id)
                time.sleep(0.5)
            except Exception as e:
                pass
    else:
        if message.chat.type == 'private':
            bot.reply_to(message, f"عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}').")

if __name__ == "__main__":
    print("البوت يعمل وتصلحت مشكلة البحث بالرموز...")
    bot.infinity_polling()
