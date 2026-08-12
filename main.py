import os
import sqlite3
import re
import asyncio
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes
)
from pyrogram import Client, enums

# استيراد مكتبات PDF للتقرير
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import arabic_reshaper
from bidi.algorithm import get_display

# --- الإعدادات وبيانات الاتصال ---
API_ID = 34123643
API_HASH = "12dccc6e1dce1c82853587ba04e9694d"
TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"

# تم اعتماد اسم معرف القناة لمنع مشكلة Peer ID Invalid
CHANNEL_ID = "@ReadingCommunity_Library"

# قائمة معرفات المشرفين
ADMIN_IDS = [7898871921, 1937491557]

BOT_USERNAME = "RCGivvv_bot"
GROUP_NAME = "مجتمع القراءة Reading Community"
GROUP_LINK = "https://t.me/reading_community_group"

# مسار قاعدة البيانات
DB_PATH = "archive_bot.db"

# قاموس لإدارة طلبات إلغاء الأرشفة
CANCEL_SYNC_REQUESTS = {}

# --- دالة تجهيز وإعادة تنظيف النصوص العربية للبحث ---
def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u064B-\u0652]', '', text)  # إزالة التشكيل
    text = re.sub(r'[أإآ]', 'ا', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\s]', ' ', text)
    return text.lower().strip()

# --- دالة تهيئة قاعدة البيانات ---
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_book_name ON archive(book_name);")
    conn.commit()
    conn.close()

# --- دالة الأرشفة السريعة لمستندات القناة ---
async def run_fast_doc_sync(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    CANCEL_SYNC_REQUESTS[chat_id] = False
    
    cancel_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 إلغاء الأرشفة", callback_data="cancel_sync")]])
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🚀 *جاري الاتصال بالقناة والبدء بأرشفة الملفات فقط...*",
        parse_mode="Markdown",
        reply_markup=cancel_btn
    )
    
    try:
        # استخدام الجلسة للاتصال بالقناة وقراءة الملفات
        async with Client("my_bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN) as app:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            added_count = 0
            skipped_count = 0
            scanned_count = 0
            
            async for message in app.search_messages(CHANNEL_ID, filter=enums.MessagesFilter.DOCUMENT):
                if CANCEL_SYNC_REQUESTS.get(chat_id, False):
                    await context.bot.send_message(chat_id=chat_id, text="🛑 *تمت عملية إلغاء الأرشفة بناءً على طلبك.*", parse_mode="Markdown")
                    break
                
                scanned_count += 1
                doc = message.document
                book_name = doc.file_name if doc and doc.file_name else (message.caption or f"Book_{message.id}")
                
                cursor.execute("SELECT id FROM archive WHERE msg_id = ?", (message.id,))
                if cursor.fetchone():
                    skipped_count += 1
                else:
                    cursor.execute("INSERT INTO archive (book_name, msg_id) VALUES (?, ?)", (book_name, message.id))
                    added_count += 1
                
                if scanned_count % 100 == 0:
                    conn.commit()
                    try:
                        await status_msg.edit_text(
                            f"⚡ *جاري الأرشفة السريعة...*\n\n"
                            f"📑 المستندات المفحوصة: `{scanned_count}`\n"
                            f"➕ الملفات المضافة: `{added_count}`\n"
                            f"⏭ الملفات المكررة: `{skipped_count}`",
                            parse_mode="Markdown",
                            reply_markup=cancel_btn
                        )
                    except Exception:
                        pass

            conn.commit()
            conn.close()
            
            if not CANCEL_SYNC_REQUESTS.get(chat_id, False):
                await status_msg.edit_text(
                    f"✅ *اكتملت الأرشفة السريعة بنجاح!*\n\n"
                    f"📊 *الإحصائيات النهائية:*\n"
                    f"• الملفات المفحوصة: `{scanned_count}`\n"
                    f"• الكتب المضافة: `{added_count}`\n"
                    f"• الكتب الموجودة سابقاً: `{skipped_count}`",
                    parse_mode="Markdown"
                )
    except Exception as e:
        await status_msg.edit_text(
            f"❌ *حدث خطأ أثناء الأرشفة السريعة:*\n`{str(e)}`\n\n"
            f"تأكد من إعطاء البوت صلاحية مشرف داخل القناة.",
            parse_mode="Markdown"
        )
    finally:
        CANCEL_SYNC_REQUESTS[chat_id] = False

# --- دالة إنشاء ملف تقرير PDF ---
def generate_pdf_report():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, book_name, msg_id FROM archive ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, alignment=1, spaceAfter=20)
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=2)

    def prepare_arabic_text(text):
        if not text: return ""
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)

    title_text = prepare_arabic_text(f"تقرير مكتبة {GROUP_NAME}")
    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 10))

    data = [[prepare_arabic_text("رقم الرسالة"), prepare_arabic_text("اسم الكتاب"), prepare_arabic_text("#")]]
    
    for row in rows:
        b_id, b_name, m_id = row
        data.append([
            prepare_arabic_text(str(m_id)),
            Paragraph(prepare_arabic_text(b_name), cell_style),
            prepare_arabic_text(str(b_id))
        ])

    table = Table(data, colWidths=[100, 380, 40])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#EAECEE")]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- لوحة تحكم المشرفين ---
def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 تصدير تقرير (PDF)", callback_data="export_pdf"), InlineKeyboardButton("📊 عرض الإحصائيات السريعة", callback_data="show_stats")],
        [InlineKeyboardButton("🗑 حذف عدد محدد من الكتب", callback_data="delete_limit"), InlineKeyboardButton("🗑 حذف الأرشيف بالكامل", callback_data="delete_all")],
        [InlineKeyboardButton("⚡ أرشفة القناة بالكامل (الملفات فقط)", callback_data="start_fast_sync")]
    ])

# --- معالجة الأمر /start ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        welcome_text = (
            f"أهلاً بك في لوحة تحكم بوت أرشيف [{GROUP_NAME}]({GROUP_LINK}) 📚⚙️\n\n"
            f"📌 *ملاحظة:* زر الأرشفة السريعة يقرأ الملفات والمستندات مباشرة ويتجاهل الرسائل النصية والصور."
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    else:
        text = (
            f"مرحباً بك في بوت مكتبة [{GROUP_NAME}]({GROUP_LINK}) 📚\n\n"
            f"ابحث عن أي كتاب بكتابة اسمه مباشرة في الشات."
        )
        await update.message.reply_text(text, parse_mode="Markdown")

# --- معالجة الضغط على الأزرار ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in ADMIN_IDS:
        return

    data = query.data

    if data == "start_fast_sync":
        asyncio.create_task(run_fast_doc_sync(query.message.chat_id, context))
        
    elif data == "cancel_sync":
        CANCEL_SYNC_REQUESTS[query.message.chat_id] = True
        
    elif data == "show_stats":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM archive")
        total_books = cursor.fetchone()[0]
        conn.close()
        await query.message.reply_text(f"📊 *إجمالي الكتب المؤرشفة حالياً:* `{total_books}` كتاب.", parse_mode="Markdown")
        
    elif data == "export_pdf":
        msg = await query.message.reply_text("⏳ *جاري توليد تقرير PDF...* ", parse_mode="Markdown")
        pdf_file = generate_pdf_report()
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=pdf_file,
            filename="Library_Report.pdf",
            caption="📄 *تقرير بجميع الكتب المؤرشفة في قاعدة البيانات.*",
            parse_mode="Markdown"
        )
        await msg.delete()
        
    elif data == "delete_all":
        confirm_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data="confirm_delete_all")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")]
        ])
        await query.message.reply_text("⚠️ *هل أنت تأكد تماماً من رغبتك في حذف الأرشيف بالكامل؟*", parse_mode="Markdown", reply_markup=confirm_btn)
        
    elif data == "confirm_delete_all":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive")
        conn.commit()
        conn.close()
        await query.message.reply_text("🗑 *تم تفريغ الأرشيف بالكامل بنجاح.*", parse_mode="Markdown")
        
    elif data == "delete_limit":
        context.user_data['awaiting_delete_count'] = True
        await query.message.reply_text("🔢 *أرسل الآن عدد الكتب الأخيرة التي تريد حذفها من الأرشيف:*", parse_mode="Markdown")
        
    elif data == "cancel_delete":
        await query.message.reply_text("❌ *تمت عملية الإلغاء.*", parse_mode="Markdown")

# --- البحث عن الكتب ومعالجة الرسائل النصية ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # إذا كان الأدمن يريد حذف عدد معين من الكتب
    if user_id in ADMIN_IDS and context.user_data.get('awaiting_delete_count'):
        if text.isdigit():
            count = int(text)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM archive WHERE id IN (SELECT id FROM archive ORDER BY id DESC LIMIT ?)", (count,))
            conn.commit()
            conn.close()
            context.user_data['awaiting_delete_count'] = False
            await update.message.reply_text(f"🗑 *تم حذف آخر {count} كتاب من الأرشيف بنجاح.*", parse_mode="Markdown")
            return
        else:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح فقط.")
            return

    # إجراء البحث للمستخدمين
    clean_query = normalize_arabic(text)
    if len(clean_query) < 2:
        await update.message.reply_text("🔍 يرجى كتابة اسم كتاب يتكون من حرفين أو أكثر للبحث.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT book_name, msg_id FROM archive")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for book_name, msg_id in rows:
        norm_name = normalize_arabic(book_name)
        if clean_query in norm_name:
            results.append((book_name, msg_id))

    if not results:
        await update.message.reply_text(f"❌ لم يتم العثور على كتاب باسم: `{text}` في المكتبة.", parse_mode="Markdown")
        return

    if len(results) == 1:
        msg_id = results[0][1]
        try:
            await context.bot.forward_message(chat_id=update.effective_chat.id, from_chat_id=CHANNEL_ID, message_id=msg_id)
        except Exception:
            await update.message.reply_text("❌ حدث خطأ عند جلب الملف من القناة، تأكد أن البوت مشرف فيها.")
    else:
        buttons = []
        for b_name, m_id in results[:10]:  # عرض أول 10 نتائج فقط لمنع القوائم الطويلة
            buttons.append([InlineKeyboardButton(f"📖 {b_name}", callback_data=f"getmsg_{m_id}")])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(f"🔎 عثرت على عدة نتائج لـ `{text}`، اختر الكتاب المطلوب:", parse_mode="Markdown", reply_markup=reply_markup)

# --- معالجة اختيار كتاب من نتائج البحث المتعددة ---
async def handle_get_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("getmsg_"):
        msg_id = int(query.data.split("_")[1])
        try:
            await context.bot.forward_message(chat_id=query.message.chat_id, from_chat_id=CHANNEL_ID, message_id=msg_id)
        except Exception:
            await query.message.reply_text("❌ تعذر إعادة توجيه الملف. تأكد من وجود البوت كمشرف بالقناة.")

# --- تشغيل البوت الرئيسي ---
def main():
    init_db()
    application = ApplicationBuilder().token(TOKEN).build()

    # تسجيل المعالجات (Handlers)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(handle_get_message_callback, pattern="^getmsg_"))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 البوت يعمل الآن وتأطير الاتصال جاهز...")
    application.run_polling()

if __name__ == "__main__":
    main()

