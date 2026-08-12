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
from telegram.error import RetryAfter, TelegramError

from pyrogram import Client, enums

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

# --- إعدادات الحساب وتليجرام API ---
API_ID = 34123643
API_HASH = "12dccc6e1dce1c82853587ba04e9694d"

TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"
CHANNEL_NUMERIC_ID = -1004395670008
ADMIN_IDS = [7898871921, 1937491557]

BOT_USERNAME = "RCGivvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")
FONT_PATH = os.path.join(DATA_DIR, "Amiri-Regular.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf"

CANCEL_SYNC_REQUESTS = {}

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) ولا يمكن استخدامه بشكل فردي.\n\n"
    f"يمكنك الانضمام إلينا عبر رابط المجموعة أعلاه."
)

LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}).\n\n"
    f"سأقوم بالمغادرة الآن..."
)

ADMIN_WELCOME_TEXT = (
    f"أهلاً بك في لوحة تحكم بوت أرشيف [{GROUP_NAME}]({GROUP_LINK}) 📚⚙️\n\n"
    "📌 **ملاحظة:** زر الأرشفة الآن يقرأ **الملفات والمستندات فقط** مباشرة ويتجاهل تماماً باقي الرسائل والصور."
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_name TEXT,
            msg_id INTEGER UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_name ON archive(book_name);")
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
        [InlineKeyboardButton("⚡ أرشفة القناة بالكامل (الملفات فقط)", callback_data="sync_all_docs")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_sync_keyboard():
    keyboard = [[InlineKeyboardButton("🛑 إيقاف الأرشفة الآن", callback_data="stop_sync")]]
    return InlineKeyboardMarkup(keyboard)

def get_confirm_delete_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("⚠️ نعم، احذف الأرشيف بالكامل", callback_data="do_delete_all"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def run_fast_doc_sync(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    CANCEL_SYNC_REQUESTS[chat_id] = False
    
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🚀 *جاري بدء فحص وأرشفة المستندات والملفات فقط من القناة...*",
        parse_mode="Markdown",
        reply_markup=get_cancel_sync_keyboard()
    )
    
    scanned_count = 0
    added_count = 0

    pyro_app = Client(
        "fast_indexer_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=TOKEN
    )

    try:
        await pyro_app.start()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        async for message in pyro_app.search_messages(CHANNEL_NUMERIC_ID, filter=enums.MessagesFilter.DOCUMENT):
            if CANCEL_SYNC_REQUESTS.get(chat_id, False):
                conn.commit()
                conn.close()
                await pyro_app.stop()
                await status_msg.edit_text(
                    f"🛑 *تم إيقاف عملية الأرشفة!*\n\n"
                    f"📊 *النتائج حتى لحظة الإيقاف:*\n"
                    f"• الملفات المفحوصة: {scanned_count:,}\n"
                    f"• الكتب المضافة حديثاً: {added_count:,}",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard()
                )
                return

            scanned_count += 1
            doc = message.document or message.audio or message.video
            book_title = None

            if doc and doc.file_name:
                book_title = doc.file_name
            elif message.caption:
                book_title = message.caption.split('\n')[0]
            else:
                book_title = f"Book_Msg_{message.id}"

            cursor.execute(
                "INSERT OR IGNORE INTO archive (book_name, msg_id) VALUES (?, ?)",
                (book_title, message.id)
            )
            if cursor.rowcount > 0:
                added_count += 1

            if scanned_count % 50 == 0:
                conn.commit()
                try:
                    await status_msg.edit_text(
                        f"⏳ *جاري أرشفة الملفات فقط...*\n\n"
                        f"• **تم فحص:** {scanned_count:,} ملف\n"
                        f"• **كتب جديدة مضافة:** {added_count:,}",
                        parse_mode="Markdown",
                        reply_markup=get_cancel_sync_keyboard()
                    )
                except Exception:
                    pass

        conn.commit()
        conn.close()
        await pyro_app.stop()

        await status_msg.edit_text(
            f"🎉 *اكتملت أرشفة الملفات بنجاح!*\n\n"
            f"📊 *التقرير النهائي:*\n"
            f"• إجمالي الملفات في القناة: {scanned_count:,}\n"
            f"• إجمالي الكتب المسجلة بالفهرس: {added_count:,}",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ حدث خطأ أثناء الأرشفة السريعة: `{e}`\n"
            "تأكد من صحة بيانات الاتصال.",
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
        f"• *إجمالي الكتب المفهرسة:* {total_books:,} كتاب 📚\n"
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
    title_text = reshape_arabic(f"📚 قائمة الكتب المفهرسة - مجتمع القراءة (الإجمالي: {total_count:,} كتاب)")
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
            caption=f"📊 *إحصائيات الأرشيف الحالي:*\n\n• *عدد الكتب المفهرسة:* {total_count:,} كتاب 📚",
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

    if data == "sync_all_docs":
        asyncio.create_task(run_fast_doc_sync(chat_id, context))

    elif data == "stop_sync":
        CANCEL_SYNC_REQUESTS[chat_id] = True

    elif data == "show_stats":
        asyncio.create_task(show_stats_text(chat_id, context))

    elif data == "export_pdf":
        asyncio.create_task(generate_pdf_report(chat_id, user_id, context))

    elif data == "confirm_delete_all":
        await query.message.reply_text(
            "⚠️ *تنبيه هام جداً!*\n\nهل أنت تأكد من رغبتك في **حذف الأرشيف بالكامل**؟",
            parse_mode="Markdown",
            reply_markup=get_confirm_delete_keyboard()
        )

    elif data == "do_delete_all":
        delete_all_records()
        await query.message.reply_text(
            "🗑 *تم مسح الفهرس بالكامل بنجاح!*",
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
            "يرجى إرسال **عدد الكتب** التي تريد حذفها:",
            parse_mode="Markdown"
        )

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if message:
        msg_id = message.message_id
        document = message.document or message.video or message.audio
        
        if document:
            book_name = document.file_name or message.caption or f"Book_Msg_{msg_id}"
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO archive (book_name, msg_id) VALUES (?, ?)",
                    (book_name, msg_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            finally:
                conn.close()

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
                f"✅ تم حذف أحدث **{deleted:,}** كتاب من الفهرس بنجاح.",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
            return

    if chat_type == 'private':
        if user_id not in ADMIN_IDS:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)
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

    norm_query = normalize_arabic(clean_query)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive GROUP BY msg_id")
    all_records = cursor.fetchall()
    conn.close()
    
    results = []
    exact_pattern = r'\b' + re.escape(norm_query) + r'\b'

    for book_name, msg_id in all_records:
        norm_name = normalize_arabic(book_name)
        if re.search(exact_pattern, norm_name):
            query_words = norm_query.split()
            name_words = norm_name.split()
            if len(name_words) <= len(query_words) + 2:
                results.append((book_name, msg_id))
    
    if results:
        sent_any = False
        for book_name, msg_id in results:
            try:
                await context.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=CHANNEL_NUMERIC_ID,
                    message_id=msg_id
                )
                sent_any = True
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Forward error: {e}")

        if not sent_any and chat_type == 'private':
            await update.message.reply_text("❌ تعذر تحويل الملف. تأكد من رفع البوت مشرفاً بالقناة.")
    else:
        if chat_type == 'private':
            await update.message.reply_text(f"❌ عذراً، لم يتم العثور على كتاب يطابق ('{clean_query}').")

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
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text(RESTRICTED_TEXT, parse_mode="Markdown", disable_web_page_preview=True)

def main():
    init_db()
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.AUDIO | filters.VIDEO), handle_channel_post))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.PRIVATE | filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP), search_and_forward))

    print("البوت جاهز ويعمل بالكامل...")
    application.run_polling()

if __name__ == "__main__":
    main()

