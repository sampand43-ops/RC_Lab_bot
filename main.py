import os
import sqlite3
import re
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from telegram.error import TelegramError

from pyrogram import Client, enums
from pyrogram.errors import FloodWait


# ============================================================
# إعدادات التخزين
# ============================================================

DATA_DIR = "/app/data"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "archive_bot.db")


# ============================================================
# بيانات Telegram
# ============================================================

# بيانات API لحساب Telegram العادي
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# Session String لحساب Telegram العادي
PYROGRAM_SESSION_STRING = os.getenv(
    "PYROGRAM_SESSION_STRING",
    ""
)

# Bot Token
TOKEN = os.getenv(
    "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8",
    ""
)


# ============================================================
# القناة
# ============================================================

CHANNEL_ID = -1004395670008


# ============================================================
# المشرفون
# ============================================================

ADMIN_IDS = [
    7898871921,
    1937491557
]


# ============================================================
# معلومات البوت والمجموعة
# ============================================================

BOT_USERNAME = "RCGivvvv_bot"

GROUP_NAME = "مجتمع القراءة Reading Community"

GROUP_LINK = "https://t.me/reading_community_group"


# ============================================================
# النصوص
# ============================================================

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) "
    f"ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)


LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة [{GROUP_NAME}]({GROUP_LINK}) "
    f"ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
    f"سأقوم بالمغادرة الآن..."
)


ADMIN_WELCOME_TEXT = (
    "أهلاً بك في لوحة تحكم البوت 📚⚙️\n\n"
    "بصفتك مشرفاً رئيسياً للنظام، تتوفر لك الصلاحيات الكاملة.\n\n"
    "💡 أرسل /help للحصول على التعليمات.\n\n"
    "البوت قيد التشغيل وجاهز لخدمتكم ✨"
)


ADMIN_HELP_TEXT = (
    "📌 *دليل استخدام البوت*\n\n"

    "━━━━━━ 👑 *صلاحيات المشرف* ━━━━━━\n\n"

    "• يمكن للمشرف إضافة البوت إلى المجموعات المعتمدة.\n\n"

    "• البحث يتم داخل ملفات القناة فقط.\n\n"

    "• الملفات القديمة الموجودة قبل إضافة البوت للقناة "
    "يمكن الوصول إليها من خلال حساب البحث المرتبط بـPyrogram.\n\n"

    "• لا يتم تنزيل الكتب إلى Railway.\n\n"

    "• لا يتم أرشفة الصور أو الروابط أو الرسائل النصية.\n\n"

    "• لا يتم استخدام caption كاسم للكتاب؛ "
    "اسم الكتاب يؤخذ من اسم الملف نفسه.\n\n"

    "━━━━━━ 👥 *استخدام الأعضاء* ━━━━━━\n\n"

    f"• الإشارة للبوت:\n"
    f"`@{BOT_USERNAME} اسم الكتاب`\n\n"

    "• أو الرد على رسالة للبوت وكتابة اسم الكتاب.\n\n"

    "• البحث متاح داخل المجموعات المعتمدة فقط."
)


# ============================================================
# قاعدة البيانات
# ============================================================

def init_db():

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
    """)

    conn.commit()
    conn.close()


def is_group_approved(chat_id: int) -> bool:

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM allowed_groups
        WHERE chat_id = ?
        """,
        (chat_id,)
    )

    row = cursor.fetchone()

    conn.close()

    return bool(row)


# ============================================================
# التحقق من المجموعة
# ============================================================

async def is_allowed_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:

    chat = update.effective_chat

    if chat and chat.type in [
        "group",
        "supergroup"
    ]:

        if is_group_approved(chat.id):
            return True

        try:

            await context.bot.send_message(
                chat_id=chat.id,
                text=LEAVE_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

        except Exception:
            pass

        try:

            await context.bot.leave_chat(
                chat.id
            )

        except Exception:
            pass

        return False

    return True


# ============================================================
# عند إضافة البوت إلى المجموعة
# ============================================================

async def on_added_to_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in [
        "group",
        "supergroup"
    ]:
        return

    if not update.message:
        return

    if not update.message.new_chat_members:
        return

    user_id = (
        update.message.from_user.id
        if update.message.from_user
        else None
    )

    for member in update.message.new_chat_members:

        if member.id != context.bot.id:
            continue

        if user_id in ADMIN_IDS:

            conn = sqlite3.connect(DB_PATH)

            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO allowed_groups
                (chat_id, added_by)
                VALUES (?, ?)
                """,
                (
                    chat.id,
                    user_id
                )
            )

            conn.commit()
            conn.close()

            try:

                await context.bot.send_message(
                    chat_id=chat.id,
                    text=(
                        "أهلاً بكم! 📚🤖\n"
                        "تم تفعيل البوت بنجاح لهذه المجموعة "
                        "بواسطة المشرف."
                    )
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

            try:

                await context.bot.leave_chat(
                    chat.id
                )

            except Exception:
                pass


# ============================================================
# عند خروج البوت من المجموعة
# ============================================================

async def on_bot_left_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.left_chat_member:
        return

    if update.message.left_chat_member.id != context.bot.id:
        return

    chat_id = update.effective_chat.id

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM allowed_groups
        WHERE chat_id = ?
        """,
        (chat_id,)
    )

    conn.commit()
    conn.close()


# ============================================================
# تطبيع النص العربي
# ============================================================

def normalize_arabic(text):

    if not text:
        return ""

    text = str(text)

    # إزالة التشكيل
    text = re.sub(
        r"[\u064b-\u0652]",
        "",
        text
    )

    # توحيد الألف
    text = re.sub(
        r"[إأآٱ]",
        "ا",
        text
    )

    # توحيد الياء
    text = text.replace(
        "ى",
        "ي"
    )

    # توحيد الواو والهمزات
    text = text.replace(
        "ؤ",
        "و"
    )

    text = text.replace(
        "ئ",
        "ي"
    )

    # إزالة الامتدادات وعلامات الترقيم
    text = re.sub(
        r"[^\w\s]",
        " ",
        text
    )

    text = text.replace(
        "_",
        " "
    )

    # إزالة المسافات الزائدة
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip().lower()


# ============================================================
# أرقام الأجزاء
# ============================================================

ARABIC_NUM_WORDS = {

    "الأول": 1,
    "اول": 1,
    "1": 1,

    "الثاني": 2,
    "ثاني": 2,
    "2": 2,

    "الثالث": 3,
    "ثالث": 3,
    "3": 3,

    "الرابع": 4,
    "رابع": 4,
    "4": 4,

    "الخامس": 5,
    "خامس": 5,
    "5": 5,

    "السادس": 6,
    "سادس": 6,
    "6": 6,

    "السابع": 7,
    "سابع": 7,
    "7": 7,

    "الثامن": 8,
    "ثامن": 8,
    "8": 8,

    "التاسع": 9,
    "تاسع": 9,
    "9": 9,

    "العاشر": 10,
    "عاشر": 10,
    "10": 10,
}


# ============================================================
# استخراج رقم الجزء
# ============================================================

def extract_part_number(filename):

    if not filename:
        return 9999

    match = re.search(
        r"(الجزء|المجلد|جـ?|مجلد|part|vol)"
        r"\s*"
        r"([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|"
        r"الخامس|السادس|السابع|الثامن|التاسع|العاشر)",
        filename,
        re.IGNORECASE
    )

    if match:

        value = match.group(2)

        if value in ARABIC_NUM_WORDS:
            return ARABIC_NUM_WORDS[value]

        value = value.translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩",
                "0123456789"
            )
        )

        if value.isdigit():
            return int(value)

    # رقم في نهاية اسم الملف
    num_match = re.search(
        r"[\s\-_]"
        r"([0-9٠-٩]+)"
        r"\s*"
        r"(?:\.pdf|\.epub|\.zip|\.rar|\.7z)?$",
        filename,
        re.IGNORECASE
    )

    if num_match:

        value = num_match.group(1)

        value = value.translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩",
                "0123456789"
            )
        )

        if value.isdigit():
            return int(value)

    return 9999


# ============================================================
# تنظيف طلب العضو
# ============================================================

def clean_search_query(text):

    phrases = [

        "اريد كتاب",
        "أريد كتاب",

        "اريد كتاب ال",
        "أريد كتاب ال",

        "اريد رواية",
        "أريد رواية",

        "اعطني كتاب",
        "أعطني كتاب",

        "اريد",
        "أريد",

        "كتاب",
        "رواية"
    ]

    phrases.sort(
        key=len,
        reverse=True
    )

    for phrase in phrases:

        if text.startswith(phrase):

            text = text[
                len(phrase):
            ].strip()

            break

    return text


# ============================================================
# Pyrogram
# ============================================================

pyro_client = None

pyro_lock = asyncio.Lock()


def create_pyrogram_client():

    global pyro_client

    if pyro_client is not None:
        return pyro_client

    if not API_ID:

        raise RuntimeError(
            "API_ID غير موجود في Railway Variables."
        )

    if not API_HASH:

        raise RuntimeError(
            "API_HASH غير موجود في Railway Variables."
        )

    if not PYROGRAM_SESSION_STRING:

        raise RuntimeError(
            "PYROGRAM_SESSION_STRING غير موجود "
            "في Railway Variables."
        )

    pyro_client = Client(
        "reading_library_user",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=PYROGRAM_SESSION_STRING
    )

    return pyro_client


# ============================================================
# التحقق من أن الرسالة ملف فقط
# ============================================================

def get_document_info(message):

    # مهم جداً:
    #
    # نحن نقبل DOCUMENT فقط.
    #
    # لا Photo
    # لا Video
    # لا Audio
    # لا Voice
    # لا Animation
    # لا Text
    # لا WebPage
    # لا Caption وحده

    if not message:
        return None

    if not message.document:
        return None

    document = message.document

    file_name = document.file_name

    if not file_name:
        return None

    return {
        "file_name": file_name,
        "message_id": message.id,
        "file_id": document.file_id,
        "mime_type": document.mime_type
    }


# ============================================================
# البحث في ملفات القناة
# ============================================================

async def search_channel_files(query):

    client = create_pyrogram_client()

    normalized_query = normalize_arabic(
        query
    )

    if not normalized_query:
        return []

    results = []

    seen_files = set()

    async with pyro_lock:

        try:

            if not client.is_connected:

                await client.start()

            # =================================================
            # مهم:
            #
            # لا نستخدم search_messages هنا للبحث باسم الملف،
            # لأن Telegram قد يطبق query على caption عند
            # البحث في الوسائط.
            #
            # بدلاً من ذلك نقرأ DOCUMENT فقط من تاريخ القناة
            # ونقارن file_name محلياً.
            # =================================================

            async for message in client.get_chat_history(
                CHANNEL_ID
            ):

                document_info = get_document_info(
                    message
                )

                # تجاهل أي شيء ليس ملفاً
                if not document_info:
                    continue

                file_name = document_info[
                    "file_name"
                ]

                normalized_file_name = normalize_arabic(
                    file_name
                )

                if not normalized_file_name:
                    continue

                # البحث داخل اسم الملف فقط
                if normalized_query not in normalized_file_name:
                    continue

                # =================================================
                # منع تكرار الملف نفسه
                #
                # لا نستخدم file_id فقط لأن النسخة المكررة
                # من نفس الكتاب قد يكون لها file_id مختلف.
                #
                # لذلك نستخدم الاسم الطبيعي للملف كمفتاح أولي.
                # =================================================

                duplicate_key = normalized_file_name

                if duplicate_key in seen_files:
                    continue

                seen_files.add(
                    duplicate_key
                )

                document_info["part"] = (
                    extract_part_number(
                        file_name
                    )
                )

                results.append(
                    document_info
                )

                # =================================================
                # حد أقصى للنتائج
                # =================================================

                if len(results) >= 30:
                    break

        except FloodWait as e:

            print(
                f"Telegram FloodWait: "
                f"انتظار {e.value} ثانية."
            )

            await asyncio.sleep(
                e.value
            )

        except Exception as e:

            print(
                "[Pyrogram Search Error]",
                type(e).__name__,
                str(e)
            )

    return results


# ============================================================
# ترتيب النتائج
# ============================================================

def sort_results(results):

    return sorted(
        results,
        key=lambda item: (
            item.get(
                "part",
                9999
            ),
            item.get(
                "message_id",
                0
            )
        )
    )


# ============================================================
# البحث عن الكتاب وإرساله
# ============================================================

async def search_and_forward(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    user_id = update.effective_user.id

    chat_type = update.effective_chat.type

    text = update.message.text.strip()

    if not text:
        return

    if text.startswith("/"):
        return


    # ========================================================
    # الخاص
    # ========================================================

    if chat_type == "private":

        if user_id not in ADMIN_IDS:

            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

            return

        clean_query = text


    # ========================================================
    # المجموعة
    # ========================================================

    elif chat_type in [
        "group",
        "supergroup"
    ]:

        if not await is_allowed_group(
            update,
            context
        ):
            return

        # هل الرسالة رد على البوت؟
        is_reply_to_bot = (
            update.message.reply_to_message
            and
            update.message.reply_to_message.from_user
            and
            update.message.reply_to_message.from_user.id
            == context.bot.id
        )

        # هل يوجد منشن للبوت؟
        mention_pattern = (
            rf"@{re.escape(BOT_USERNAME)}"
        )

        has_mention = bool(
            re.search(
                mention_pattern,
                text,
                re.IGNORECASE
            )
        )

        # إذا لم يكن منشن أو Reply للبوت
        if not (
            is_reply_to_bot
            or
            has_mention
        ):
            return

        clean_query = re.sub(
            mention_pattern,
            "",
            text,
            flags=re.IGNORECASE
        ).strip()


    else:

        return


    # ========================================================
    # تنظيف الاستعلام
    # ========================================================

    clean_query = clean_search_query(
        clean_query
    )

    if not clean_query:

        clean_query = text


    normalized_query = normalize_arabic(
        clean_query
    )

    if (
        not normalized_query
        or
        len(normalized_query) < 2
    ):

        if chat_type == "private":

            await update.message.reply_text(
                "⚠️ يرجى كتابة اسم كتاب صالح."
            )

        return


    # ========================================================
    # رسالة حالة مؤقتة للمشرف فقط
    # ========================================================

    status_message = None

    if chat_type == "private":

        try:

            status_message = (
                await update.message.reply_text(
                    "🔎 جاري البحث داخل ملفات القناة..."
                )
            )

        except Exception:
            pass


    # ========================================================
    # البحث
    # ========================================================

    try:

        results = await search_channel_files(
            clean_query
        )

    except Exception as e:

        print(
            "[Search Error]",
            type(e).__name__,
            str(e)
        )

        if status_message:

            try:

                await status_message.edit_text(
                    "❌ حدث خطأ أثناء البحث في ملفات القناة."
                )

            except Exception:
                pass

        return


    # ========================================================
    # ترتيب النتائج
    # ========================================================

    results = sort_results(
        results
    )


    # ========================================================
    # إزالة بعض النتائج غير المرغوبة
    # ========================================================

    forbidden_prefixes = [
        "صور من",
        "قصص من",
        "مختصر",
        "شرح"
    ]

    normalized_forbidden = [
        normalize_arabic(
            value
        )
        for value in forbidden_prefixes
    ]

    filtered_results = []

    for item in results:

        normalized_name = normalize_arabic(
            item["file_name"]
        )

        if any(
            normalized_name.startswith(
                prefix
            )
            for prefix in normalized_forbidden
        ):
            continue

        filtered_results.append(
            item
        )

    if filtered_results:

        results = filtered_results


    # ========================================================
    # لا توجد نتائج
    # ========================================================

    if not results:

        if status_message:

            try:

                await status_message.edit_text(
                    f"❌ لم يتم العثور على ملف يطابق:\n"
                    f"`{clean_query}`",
                    parse_mode="Markdown"
                )

            except Exception:
                pass

        elif chat_type == "private":

            await update.message.reply_text(
                f"❌ لم يتم العثور على ملف يطابق:\n"
                f"`{clean_query}`",
                parse_mode="Markdown"
            )

        return


    # ========================================================
    # إرسال النتائج
    # ========================================================

    sent_count = 0

    for item in results:

        message_id = item[
            "message_id"
        ]

        try:

            # =================================================
            # Bot API هو الذي يقوم بالتحويل.
            #
            # لا يتم تنزيل الملف إلى Railway.
            # =================================================

            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=CHANNEL_ID,
                message_id=message_id
            )

            sent_count += 1

            await asyncio.sleep(
                0.5
            )

        except TelegramError as e:

            print(
                f"[Forward Error] "
                f"message_id={message_id}: "
                f"{e}"
            )

        except Exception as e:

            print(
                f"[Forward Error] "
                f"message_id={message_id}: "
                f"{type(e).__name__}: {e}"
            )


    # ========================================================
    # تحديث رسالة المشرف
    # ========================================================

    if status_message:

        try:

            await status_message.edit_text(
                f"✅ تم العثور على "
                f"{sent_count} ملف."
            )

        except Exception:
            pass


# ============================================================
# /start
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    chat_type = update.effective_chat.type


    if chat_type in [
        "group",
        "supergroup"
    ]:

        if not await is_allowed_group(
            update,
            context
        ):
            return


    if chat_type == "private":

        if user_id in ADMIN_IDS:

            await update.message.reply_text(
                ADMIN_WELCOME_TEXT,
                parse_mode="Markdown"
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
            f"1️⃣ الإشارة للبوت: "
            f"`@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل Reply على أي رسالة للبوت "
            f"وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )


# ============================================================
# /help
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    chat_type = update.effective_chat.type


    if chat_type in [
        "group",
        "supergroup"
    ]:

        if not await is_allowed_group(
            update,
            context
        ):
            return

        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"
            f"للبحث عن أي كتاب، يمكنك:\n"
            f"1️⃣ الإشارة للبوت: "
            f"`@{BOT_USERNAME} اسم الكتاب`\n"
            f"2️⃣ أو عمل Reply على أي رسالة للبوت "
            f"وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown"
        )


    elif chat_type == "private":

        if user_id in ADMIN_IDS:

            await update.message.reply_text(
                ADMIN_HELP_TEXT,
                parse_mode="Markdown"
            )

        else:

            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )


# ============================================================
# تشغيل جلسة Pyrogram
# ============================================================

async def post_init(application):

    print(
        "========================================"
    )

    print(
        "جاري تشغيل جلسة البحث في ملفات القناة..."
    )

    try:

        client = create_pyrogram_client()

        if not client.is_connected:

            await client.start()

        # التأكد من الوصول إلى القناة
        chat = await client.get_chat(
            CHANNEL_ID
        )

        print(
            f"تم الاتصال بالقناة بنجاح: "
            f"{chat.title}"
        )

        print(
            "جلسة Pyrogram جاهزة."
        )

    except Exception as e:

        print(
            "❌ فشل تشغيل جلسة Pyrogram:"
        )

        print(
            type(e).__name__,
            str(e)
        )

        print(
            "تأكد من:"
        )

        print(
            "1. API_ID"
        )

        print(
            "2. API_HASH"
        )

        print(
            "3. PYROGRAM_SESSION_STRING"
        )

        print(
            "4. أن حساب Telegram المرتبط بالجلسة "
            "يستطيع الوصول إلى القناة."
        )

    print(
        "========================================"
    )


# ============================================================
# إغلاق جلسة Pyrogram
# ============================================================

async def post_shutdown(application):

    global pyro_client

    if pyro_client is None:
        return

    try:

        if pyro_client.is_connected:

            await pyro_client.stop()

    except Exception as e:

        print(
            "Pyrogram shutdown error:",
            e
        )


# ============================================================
# Main
# ============================================================

def main():

    init_db()

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود في Railway Variables."
        )

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )


    # ========================================================
    # الأوامر
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )


    # ========================================================
    # إضافة البوت إلى مجموعة
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            on_added_to_group
        )
    )


    # ========================================================
    # خروج البوت من مجموعة
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            on_bot_left_group
        )
    )


    # ========================================================
    # البحث
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & (
                filters.ChatType.PRIVATE
                | filters.ChatType.GROUPS
                | filters.ChatType.SUPERGROUP
            ),
            search_and_forward
        )
    )


    print(
        "البوت جاهز ويعمل مع المشرفين المعتمدين..."
    )

    application.run_polling()


# ============================================================
# بدء البرنامج
# ============================================================

if __name__ == "__main__":

    main()
