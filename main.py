import os
import sqlite3
import re
import asyncio
import urllib.request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.error import RetryAfter

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")

FONT_PATH = os.path.join(DATA_DIR, "Amiri-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf"

CHANNEL_ID = -1004395670008
ADMIN_IDS = [7898871921, 1937491557]

BOT_USERNAME = "RCGivvvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)

LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
    f"سأقوم بالمغادرة الآن..."
)

ADMIN_WELCOME_TEXT = (
    "أهلاً بك في لوحة تحكم البوت 📚⚙️\n\n"
    "يمكنك إدارة الأرشيف، إظهار الإحصائيات، تصدير التقارير، أو حذف الكتب باستخدام الأزرار أدناه."
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. إنشاء الجداول الأساسية
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            msg_id INTEGER UNIQUE,
            file_unique_id TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)
    
    # 2. ترقية قاعدة البيانات إذا كانت قديمة وحذف عدم وجود العمود
    try:
        cursor.execute("ALTER TABLE archive ADD COLUMN file_unique_id TEXT;")
    except sqlite3.OperationalError:
        pass  # العمود موجود بالفعل
        
    # 3. إنشاء الفهارس لسرعة البحث
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_name ON archive(book_name);")
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_uid ON archive(file_unique_id);")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def ensure_font_exists():
    if not os.path.exists(FONT_PATH):
        try:
            urllib.request.urlretrieve(FONT_URL, FONT_PATH)
        except Exception as e:
            print(f"خطأ في تحميل الخط: {e}")

def reshape_arabic(text):
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def is_group_approved(chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM allowed_groups WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

async def is_allowed_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        if is_group_approved(chat.id):
            return True
        else:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=LEAVE_TEXT,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception:
                pass
            finally:
                try:
                    await context.bot.leave_chat(chat.id)
                except Exception:
                    pass
            return False
    return True

def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 عرض الإحصائيات السريعة", callback_data="show_stats"),
            InlineKeyboardButton("📄 تصدير تقرير (PDF)", callback_data="export_pdf")
        ],
        [
            InlineKeyboardButton("🗑 حذف الأرشيف بالكامل", callback_data="confirm_delete_all"),
            InlineKeyboardButton("✂️ حذف عدد محدد من الكتب", callback_data="ask_delete_count")
        ],
        [InlineKeyboardButton("🔄 أرشفة الدفعة 1 (1 - 50,000)", callback_data="sync_1_50000")],
        [InlineKeyboardButton("🔄 أرشفة الدفعة 2 (50,001 - 100,000)", callback_data="sync_50001_100000")],
        [InlineKeyboardButton("🔄 أرشفة الدفعة 3 (100,001 - 150,000)", callback_data="sync_100001_150000")],
        [InlineKeyboardButton("🔄 أرشفة الدفعة 4 (150,001 - 200,000)", callback_data="sync_150001_200000")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirm_delete_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⚠️ نعم، احذف الأرشيف بالكامل", callback_data="do_delete_all"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def run_sync_process(chat_id: int, user_id: int, start_id: int, end_id: int, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ جاري بدء أرشفة القناة للدفعة ({start_id:,} إلى {end_id:,})...\nيرجى الانتظار."
    )
    
    added_count = 0
    skipped_duplicates = 0
    scanned_count = 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    msg_id = start_id
    while msg_id <= end_id:
        try:
            fwd_msg = await context.bot.forward_message(
                chat_id=user_id,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id
            )
            
            document = fwd_msg.document or fwd_msg.video or fwd_msg.audio
            if document:
                book_name = document.file_name or fwd_msg.caption or "Unknown_Book"
                file_uid = document.file_unique_id

                cursor.execute(
                    "SELECT 1 FROM archive WHERE file_unique_id = ? OR book_name = ?", 
                    (file_uid, book_name)
                )
                if cursor.fetchone():
                    skipped_duplicates += 1
                else:
                    cursor.execute(
                        "INSERT OR IGNORE INTO archive (book_name, msg_id, file_unique_id) VALUES (?, ?, ?)",
                        (book_name, msg_id, file_uid)
                    )
                    added_count += 1
            
            try:
                await fwd_msg.delete()
            except Exception:
                pass

            scanned_count += 1
            msg_id += 1

            if scanned_count % 200 == 0:
                conn.commit()
                try:
                    await status_msg.edit_text(
                        f"⏳ جاري الأرشفة...\n"
                        f"• تم فحص: {scanned_count:,}\n"
                        f"• كتب جديدة: {added_count:,}\n"
                        f"• مكرر ومتجاوز: {skipped_duplicates:,}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.02)

        except RetryAfter as e:
            wait_time = e.retry_after + 2
            await asyncio.sleep(wait_time)
            continue
        except Exception:
            scanned_count += 1
            msg_id += 1
            pass

    conn.commit()
    conn.close()
    
    await status_msg.edit_text(
        f"✅ *اكتملت أرشفة الدفعة بنجاح!*\n\n"
        f"📊 *التقرير النهائي:*\n"
        f"• الرسائل المفحوصة: {scanned_count:,}\n"
        f"• الكتب الجديدة المضافة: {added_count:,}\n"
        f"• المكررة المتجاوزة: {skipped_duplicates:,}",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

async def show_stats_text(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), MAX(msg_id) FROM archive")
    row = cursor.fetchone()
    conn.close()

    total_books = row[0] if row else 0
    last_msg_id = row[1] if row and row[1] else 0

    text = (
        f"📊 *إحصائيات الأرشيف الحالي:*\n\n"
        f"• *إجمالي الكتب المؤرشفة:* {total_books:,} كتاب 📚\n"
        f"• *رقم آخر رسالة محفوظة:* {last_msg_id:,}"
    )
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

async def generate_pdf_report(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive ORDER BY id ASC")
    records = cursor.fetchall()
    conn.close()

    total_count = len(records)
    if total_count == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📂 الأرشيف فارغ حالياً.",
            reply_markup=get_admin_keyboard()
        )
        return

    status_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ جاري توليد ملف الـ PDF...")

    ensure_font_exists()
    pdf_path = os.path.join(DATA_DIR, "archived_books.pdf")
    pdfmetrics.registerFont(TTFont('Amiri', FONT_PATH))

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30
    )

    styles = getSampleStyleSheet()
    arabic_style = ParagraphStyle('ArabicStyle', parent=styles['Normal'], fontName='Amiri', fontSize=11, leading=16, alignment=2)
    title_style = ParagraphStyle('ArabicTitle', parent=styles['Title'], fontName='Amiri', fontSize=16, leading=22, alignment=1)

    story = []
    title_text = reshape_arabic(f"📚 قائمة الكتب المؤرشفة - مجتمع القراءة (الإجمالي: {total_count:,} كتاب)")
    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 15))

    for idx, (book_name, msg_id) in enumerate(records, start=1):
        line_raw = f"{idx}. {book_name} (معرف الرسالة: {msg_id})"
        line_reshaped = reshape_arabic(line_raw)
        story.append(Paragraph(line_reshaped, arabic_style))
        story.append(Spacer(1, 4))

    doc.build(story)

    try:
        await status_msg.delete()
    except Exception:
        pass

    with open(pdf_path, "rb") as pdf_file:
        await context.bot.send_document(
            chat_id=user_id,
            document=pdf_file,
            filename="قائمة_الكتب_المؤرشفة.pdf",
            caption=f"📊 *إحصائيات الأرشيف الحالي:*\n\n• *عدد الكتب المحفوظة:* {total_count:,} كتاب 📚",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

def delete_all_records():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM archive")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='archive'")
    conn.commit()
    conn.close()

def delete_last_records(count: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM archive 
        WHERE id IN (
            SELECT id FROM archive ORDER BY id DESC LIMIT ?
        )
    """, (count,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if user_id not in ADMIN_IDS:
        return

    data = query.data

    if data.startswith("sync_"):
        parts = data.split("_")
        start_id = int(parts[1])
        end_id = int(parts[2])
        asyncio.create_task(run_sync_process(chat_id, user_id, start_id, end_id, context))

    elif data == "show_stats":
        asyncio.create_task(show_stats_text(chat_id, context))

    elif data == "export_pdf":
        asyncio.create_task(generate_pdf_report(chat_id, user_id, context))

    elif data == "confirm_delete_all":
        await query.message.reply_text(
            "⚠️ *تنبيه هام جداً!*\n\nهل أنت تأكد من رغبتك في **حذف الأرشيف بالكامل**؟ لن تتمكن من استعادة البيانات إلا بإعادة الأرشفة.",
            parse_mode="Markdown",
            reply_markup=get_confirm_delete_keyboard()
        )

    elif data == "do_delete_all":
        delete_all_records()
        await query.message.reply_text(
            "🗑 *تم مسح الأرشيف بالكامل بنجاح!*",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    elif data == "cancel_delete":
        await query.message.reply_text(
            "❌ تم إلغاء عملية الحذف.",
            reply_markup=get_admin_keyboard()
        )

    elif data == "ask_delete_count":
        context.user_data['awaiting_delete_count'] = True
        await query.message.reply_text(
            "✂️ *حذف عدد محدد من الكتب:*\n\n"
            "يرجى إرسال **عدد الكتب** التي تريد حذفها من أحدث الكتب المضافة الآن (مثلاً اكتب: `50` أو `100`):",
            parse_mode="Markdown"
        )

async def delete_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ يرجى تحديد عدد الكتب المراد حذفها. مثال: `/delete_last 50`", parse_mode="Markdown")
        return

    count = int(context.args[0])
    deleted = delete_last_records(count)
    await update.message.reply_text(
        f"✅ تم حذف أحدث **{deleted:,}** كتاب من الأرشيف بنجاح.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

async def sync_channel_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return

    start_id = 1
    end_id = 200000

    if context.args:
        try:
            start_id = int(context.args[0])
            if len(context.args) > 1:
                end_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال أرقام صالحة. مثال: `/sync 1 50000`", parse_mode="Markdown")
            return

    asyncio.create_task(run_sync_process(update.effective_chat.id, user_id, start_id, end_id, context))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private' or user_id not in ADMIN_IDS:
        return
    asyncio.create_task(show_stats_text(update.effective_chat.id, context))

async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ['group', 'supergroup']:
        return

    user_id = update.message.from_user.id if update.message and update.message.from_user else None

    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            if user_id in ADMIN_IDS:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO allowed_groups (chat_id, added_by) VALUES (?, ?)", (chat.id, user_id))
                conn.commit()
                conn.close()
                
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text="أهلاً بكم! 📚🤖\nتم تفعيل البوت بنجاح لهذه المجموعة بواسطة المشرف."
                    )
                except Exception:
                    pass
            else:
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=LEAVE_TEXT,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                except Exception:
                    pass
                finally:
                    try:
                        await context.bot.leave_chat(chat.id)
                    except Exception:
                        pass

async def on_bot_left_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.left_chat_member:
        if update.message.left_chat_member.id == context.bot.id:
            chat_id = update.effective_chat.id
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM allowed_groups WHERE chat_id = ?", (chat_id,))
            conn.commit()
            conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return

    if chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(
                ADMIN_WELCOME_TEXT,
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text(
                RESTRICTED_TEXT, 
                parse_mode="Markdown", 
                disable_web_page_preview=True
            )
    else:
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ إشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل (رد/Reply) على أي رسالة للبوت وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    if chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return
        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ إشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل (رد/Reply) على أي رسالة للبوت وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )
    elif chat_type == 'private':
        if user_id in ADMIN_IDS:
            await update.message.reply_text(
                ADMIN_WELCOME_TEXT,
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text(
                RESTRICTED_TEXT, 
                parse_mode="Markdown", 
                disable_web_page_preview=True
            )

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message:
        msg_id = message.message_id
        document = message.document or message.video or message.audio
        
        if document:
            book_name = document.file_name or message.caption or "Unknown_Book"
            file_uid = document.file_unique_id
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO archive (book_name, msg_id, file_unique_id) VALUES (?, ?, ?)",
                    (book_name, msg_id, file_uid)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()

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
            
    return 9999

def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r'[\u064b-\u0652]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

async def search_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    text = update.message.text.strip()

    if text.startswith('/'):
        return

    if chat_type == 'private' and user_id in ADMIN_IDS and context.user_data.get('awaiting_delete_count'):
        if text.isdigit():
            count = int(text)
            deleted = delete_last_records(count)
            context.user_data['awaiting_delete_count'] = False
            await update.message.reply_text(
                f"✅ تم حذف أحدث **{deleted:,}** كتاب من الأرشيف بنجاح.",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
            return
        else:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صريح فقط (مثلاً: 50).")
            return

    if chat_type == 'private':
        if user_id not in ADMIN_IDS:
            await update.message.reply_text(
                RESTRICTED_TEXT, 
                parse_mode="Markdown", 
                disable_web_page_preview=True
            )
            return
        clean_query = text

    elif chat_type in ['group', 'supergroup']:
        if not await is_allowed_group(update, context):
            return

        is_reply_to_bot = (
            update.message.reply_to_message 
            and update.message.reply_to_message.from_user 
            and update.message.reply_to_message.from_user.id == context.bot.id
        )
        
        mention_pattern = rf'@{re.escape(BOT_USERNAME)}'
        has_mention = bool(re.search(mention_pattern, text, re.IGNORECASE))

        if not (is_reply_to_bot or has_mention):
            return

        clean_query = re.sub(mention_pattern, '', text, flags=re.IGNORECASE).strip()

    else:
        return

    phrases_to_remove = [
        "اريد كتاب", "أريد كتاب", "اريد كتاب ال", "أريد كتاب ال",
        "اريد رواية", "أريد رواية", "اعطني كتاب", "أعطني كتاب", 
        "اريد", "أريد", "كتاب", "رواية"
    ]
    phrases_to_remove = sorted(phrases_to_remove, key=len, reverse=True)
    
    for phrase in phrases_to_remove:
        if clean_query.startswith(phrase):
            clean_query = clean_query[len(phrase):].strip()
            break
            
    if not clean_query:
        clean_query = text

    norm_query = normalize_arabic(clean_query)

    if not norm_query or len(norm_query) < 2:
        if chat_type == 'private':
            await update.message.reply_text("⚠️ يرجى كتابة اسم كتاب أو كلمة بحث صالحة تحتوي على أحرف.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    results = []
    
    for book_name, msg_id in all_records:
        norm_name = normalize_arabic(book_name)
        if norm_name.startswith(norm_query):
            results.append((book_name, msg_id))
            
    if not results:
        forbidden_prefixes = ["صور من", "قصص من", "مختصر", "شرح"]
        norm_forbidden = [normalize_arabic(p) for p in forbidden_prefixes]
        
        for book_name, msg_id in all_records:
            norm_name = normalize_arabic(book_name)
            if norm_query in norm_name:
                if not any(norm_name.startswith(p) for p in norm_forbidden):
                    results.append((book_name, msg_id))
    
    if results:
        sorted_results = sorted(results, key=lambda x: extract_part_number(x[0]))
        valid_books = [item for item in sorted_results if extract_part_number(item[0]) != 9999]
        
        if not valid_books:
            valid_books = [sorted_results[0]]

        for book_name, msg_id in valid_books:
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                await asyncio.sleep(0.5)
            except Exception:
                pass
    else:
        if chat_type == 'private':
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}') في الأرشيف.")

def main():
    init_db()
    
    TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("sync", sync_channel_history))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("delete_last", delete_last_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_added_to_group))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_bot_left_group))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), search_and_forward))

    print("البوت جاهز ويعمل بالكامل...")
    application.run_polling()

if __name__ == "__main__":
    main()

