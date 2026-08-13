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

from pyrogram import Client
from pyrogram.errors import FloodWait


# ============================================================
# بيانات Telegram
# مأخوذة من الكود الأصلي
# ============================================================

API_ID = 34123643

API_HASH = "12dccc6e1dce1c82853587ba04e9694d"

TOKEN = "8619586974:AAGuSahN1tsDZLNOtmSOmdjwjw8ZcC2IMe8"


# ============================================================
# قناة المكتبة
# ============================================================

CHANNEL_ID = -1004395670008


# ============================================================
# المشرفون
# ============================================================

ADMIN_IDS = [
    7898871921,
    1937491557,
]


# ============================================================
# معلومات البوت والمجموعة
# ============================================================

BOT_USERNAME = "RCGivvvv_bot"

GROUP_NAME = "مجتمع القراءة Reading Community"

GROUP_LINK = "https://t.me/reading_community_group"


# ============================================================
# قاعدة بيانات المجموعات فقط
#
# مهم:
# لا يتم تخزين الكتب
# لا يتم تخزين أسماء الملفات
# لا يتم تخزين message_id للكتب
# ============================================================

DATA_DIR = "/app/data"

os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "groups.db")


# ============================================================
# رسائل البوت
# ============================================================

RESTRICTED_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة "
    f"[{GROUP_NAME}]({GROUP_LINK}) "
    f"ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه."
)


LEAVE_TEXT = (
    f"عذراً، هذا البوت خاص بمجموعة "
    f"[{GROUP_NAME}]({GROUP_LINK}) "
    f"ولا يمكن استخدامه بشكل فردي أو من قِبل جهات خارجية أخرى.\n\n"
    f"يمكنك الانضمام إلينا والمشاركة معنا عبر رابط المجموعة أعلاه.\n\n"
    f"سأقوم بالمغادرة الآن..."
)


ADMIN_WELCOME_TEXT = (
    "أهلاً بك في لوحة تحكم البوت 📚⚙️\n\n"
    "بصفتك مشرفاً رئيسياً للنظام، تتوفر لك الصلاحيات.\n\n"
    "💡 أرسل /help للحصول على التعليمات.\n\n"
    "البوت قيد التشغيل وجاهز لخدمتك ✨"
)


ADMIN_HELP_TEXT = (
    "📌 *دليل استخدام البوت*\n\n"

    "━━━━━━ 👑 *المشرف* ━━━━━━\n\n"

    "• يمكن للمشرف إضافة البوت إلى المجموعات المعتمدة.\n"
    "• لا توجد أرشفة للكتب ولا يتم تخزين أسماء الملفات.\n"
    "• البحث يتم مباشرة في سجل القناة عند طلب الكتاب.\n\n"

    "━━━━━━ 👥 *الأعضاء* ━━━━━━\n\n"

    f"• الإشارة للبوت: `@{BOT_USERNAME} اسم الكتاب`\n"
    "• أو الرد Reply على رسالة للبوت وكتابة اسم الكتاب.\n\n"

    "• البحث يتعامل مع الملفات Documents فقط."
)


# ============================================================
# إنشاء قاعدة البيانات
# ============================================================

def init_db():

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER
        )
        """
    )

    conn.commit()

    conn.close()


# ============================================================
# التحقق من المجموعة
# ============================================================

def is_group_approved(chat_id: int) -> bool:

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM allowed_groups WHERE chat_id = ?",
        (chat_id,),
    )

    row = cursor.fetchone()

    conn.close()

    return bool(row)


# ============================================================
# التحقق من صلاحية المجموعة
# ============================================================

async def is_allowed_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    chat = update.effective_chat

    if not chat:
        return False

    if chat.type in ("group", "supergroup"):

        if is_group_approved(chat.id):
            return True

        try:

            await context.bot.send_message(
                chat_id=chat.id,
                text=LEAVE_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

        except Exception as e:

            print(
                "[Send leave message error]",
                type(e).__name__,
                str(e),
            )

        try:

            await context.bot.leave_chat(chat.id)

        except Exception as e:

            print(
                "[Leave group error]",
                type(e).__name__,
                str(e),
            )

        return False

    return True


# ============================================================
# عند إضافة البوت إلى مجموعة
# ============================================================

async def on_added_to_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return

    if not update.message:
        return

    if not update.message.new_chat_members:
        return

    user_id = None

    if update.message.from_user:
        user_id = update.message.from_user.id

    for member in update.message.new_chat_members:

        if member.id != context.bot.id:
            continue

        # ----------------------------------------------------
        # إذا أضافه أحد المشرفين
        # ----------------------------------------------------

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
                    user_id,
                ),
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
                    ),
                )

            except Exception as e:

                print(
                    "[Welcome error]",
                    type(e).__name__,
                    str(e),
                )

        # ----------------------------------------------------
        # إذا أضافه شخص غير مشرف
        # ----------------------------------------------------

        else:

            try:

                await context.bot.send_message(
                    chat_id=chat.id,
                    text=LEAVE_TEXT,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )

            except Exception as e:

                print(
                    "[Unauthorized group message error]",
                    type(e).__name__,
                    str(e),
                )

            try:

                await context.bot.leave_chat(chat.id)

            except Exception as e:

                print(
                    "[Unauthorized group leave error]",
                    type(e).__name__,
                    str(e),
                )


# ============================================================
# عند خروج البوت من المجموعة
# ============================================================

async def on_bot_left_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
        "DELETE FROM allowed_groups WHERE chat_id = ?",
        (chat_id,),
    )

    conn.commit()

    conn.close()


# ============================================================
# تنظيف النص العربي
# ============================================================

def normalize_arabic(text: str) -> str:

    if not text:
        return ""

    text = str(text)

    # إزالة التشكيل
    text = re.sub(
        r"[\u064b-\u0652]",
        "",
        text,
    )

    # توحيد الألف
    text = re.sub(
        r"[إأآٱ]",
        "ا",
        text,
    )

    # توحيد الياء
    text = text.replace(
        "ى",
        "ي",
    )

    # توحيد الواو
    text = text.replace(
        "ؤ",
        "و",
    )

    # توحيد الياء الهمزية
    text = text.replace(
        "ئ",
        "ي",
    )

    text = text.replace(
        "_",
        " ",
    )

    # إزالة الرموز مع إبقاء الحروف والأرقام
    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip().lower()


# ============================================================
# تنظيف طلب البحث
# ============================================================

def clean_search_query(text: str) -> str:

    phrases = [
        "اريد كتاب ال",
        "أريد كتاب ال",
        "اريد كتاب",
        "أريد كتاب",
        "اريد رواية",
        "أريد رواية",
        "اعطني كتاب",
        "أعطني كتاب",
        "اريد",
        "أريد",
        "كتاب",
        "رواية",
    ]

    phrases.sort(
        key=len,
        reverse=True,
    )

    for phrase in phrases:

        if text.startswith(phrase):

            return text[len(phrase):].strip()

    return text.strip()


# ============================================================
# الأرقام العربية للأجزاء
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

def extract_part_number(filename: str) -> int:

    if not filename:
        return 9999

    match = re.search(
        r"(الجزء|المجلد|جـ?|مجلد|part|vol)"
        r"\s*"
        r"([0-9٠-٩]+|الأول|الثاني|الثالث|الرابع|"
        r"الخامس|السادس|السابع|الثامن|التاسع|العاشر)",
        filename,
        re.IGNORECASE,
    )

    if match:

        value = match.group(2)

        if value in ARABIC_NUM_WORDS:

            return ARABIC_NUM_WORDS[value]

        value = value.translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩",
                "0123456789",
            )
        )

        if value.isdigit():

            return int(value)

    # محاولة اكتشاف رقم في نهاية اسم الملف
    num_match = re.search(
        r"[\s\-_]([0-9٠-٩]+)\s*"
        r"(?:\.pdf|\.epub|\.zip|\.rar|\.7z)?$",
        filename,
        re.IGNORECASE,
    )

    if num_match:

        value = num_match.group(1).translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩",
                "0123456789",
            )
        )

        if value.isdigit():

            return int(value)

    return 9999


# ============================================================
# عميل Pyrogram
#
# مهم:
# لا يوجد PYROGRAM_SESSION_STRING
#
# يتم تسجيل الدخول مباشرة باستخدام:
# API_ID
# API_HASH
# BOT TOKEN
# ============================================================

pyro_client = None

pyro_lock = asyncio.Lock()


def create_pyrogram_client():

    global pyro_client

    if pyro_client is not None:
        return pyro_client

    pyro_client = Client(
        "reading_library_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=TOKEN,
        workdir=DATA_DIR,
    )

    return pyro_client


# ============================================================
# استخراج معلومات الملف فقط
#
# Document فقط
#
# لا صور
# لا فيديو
# لا صوت
# لا روابط
# لا نصوص
# ============================================================

def get_document_info(message):

    if not message:
        return None

    if not message.document:
        return None

    document = message.document

    if not document.file_name:
        return None

    return {
        "file_name": document.file_name,
        "message_id": message.id,
        "part": extract_part_number(
            document.file_name
        ),
    }


# ============================================================
# البحث المباشر في القناة
#
# لا توجد أرشفة.
#
# لا يتم تخزين الكتب.
#
# لا يتم تنزيل الملفات.
#
# يتم قراءة سجل القناة وقت الطلب فقط.
# ============================================================

async def search_channel_files(query: str):

    client = create_pyrogram_client()

    normalized_query = normalize_arabic(
        query
    )

    if not normalized_query:
        return []

    results = []

    seen_names = set()

    async with pyro_lock:

        try:

            if not client.is_connected:

                await client.start()

            print(
                f"[SEARCH] Searching channel for: {query}"
            )

            async for message in client.get_chat_history(
                CHANNEL_ID
            ):

                # --------------------------------------------
                # لا نهتم إلا بالـ Documents
                # --------------------------------------------

                info = get_document_info(
                    message
                )

                if not info:
                    continue

                file_name = info["file_name"]

                normalized_name = normalize_arabic(
                    file_name
                )

                if not normalized_name:
                    continue

                # --------------------------------------------
                # البحث في اسم الملف فقط
                # --------------------------------------------

                if normalized_query not in normalized_name:
                    continue

                # --------------------------------------------
                # منع تكرار نفس اسم الملف
                #
                # إذا كان نفس الاسم موجوداً أكثر من مرة،
                # نحتفظ بنتيجة واحدة فقط.
                #
                # الأجزاء المختلفة تبقى نتائج مختلفة لأن
                # اسمها مختلف.
                # --------------------------------------------

                if normalized_name in seen_names:
                    continue

                seen_names.add(
                    normalized_name
                )

                results.append(
                    info
                )

                # حماية من إرسال عدد هائل من النتائج
                if len(results) >= 30:
                    break

            print(
                f"[SEARCH] Found {len(results)} files."
            )

        except FloodWait as e:

            print(
                f"[Pyrogram FloodWait] "
                f"waiting {e.value} seconds."
            )

            await asyncio.sleep(
                e.value
            )

        except Exception as e:

            print(
                "[Pyrogram Search Error]",
                type(e).__name__,
                str(e),
            )

            raise

    return results


# ============================================================
# البحث وإرسال الكتاب
# ============================================================

async def search_and_forward(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
    # المحادثة الخاصة
    # ========================================================

    if chat_type == "private":

        if user_id not in ADMIN_IDS:

            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

            return

        clean_query = text

    # ========================================================
    # المجموعة
    # ========================================================

    elif chat_type in (
        "group",
        "supergroup",
    ):

        if not await is_allowed_group(
            update,
            context,
        ):

            return

        is_reply_to_bot = (

            update.message.reply_to_message

            and update.message.reply_to_message.from_user

            and update.message.reply_to_message.from_user.id
            == context.bot.id
        )

        mention_pattern = (
            rf"@{re.escape(BOT_USERNAME)}"
        )

        has_mention = bool(
            re.search(
                mention_pattern,
                text,
                re.IGNORECASE,
            )
        )

        if not (
            is_reply_to_bot
            or has_mention
        ):

            return

        clean_query = re.sub(
            mention_pattern,
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    else:

        return

    # ========================================================
    # تنظيف اسم الكتاب
    # ========================================================

    clean_query = clean_search_query(
        clean_query
    )

    if not clean_query:

        clean_query = text

    normalized_query = normalize_arabic(
        clean_query
    )

    if not normalized_query:

        if chat_type == "private":

            await update.message.reply_text(
                "⚠️ يرجى كتابة اسم كتاب أو كلمة بحث صالحة."
            )

        return

    if len(normalized_query) < 2:

        if chat_type == "private":

            await update.message.reply_text(
                "⚠️ يرجى كتابة اسم كتاب أو كلمة بحث أطول."
            )

        return

    # ========================================================
    # رسالة حالة البحث
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

            status_message = None

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
            str(e),
        )

        if status_message:

            try:

                await status_message.edit_text(
                    "❌ حدث خطأ أثناء البحث في القناة."
                )

            except Exception:

                pass

        elif chat_type == "private":

            await update.message.reply_text(
                "❌ حدث خطأ أثناء البحث في القناة."
            )

        return

    # ========================================================
    # ترتيب النتائج
    # ========================================================

    starts_with = []

    contains = []

    forbidden_prefixes = [

        normalize_arabic(
            "صور من"
        ),

        normalize_arabic(
            "قصص من"
        ),

        normalize_arabic(
            "مختصر"
        ),

        normalize_arabic(
            "شرح"
        ),
    ]

    for item in results:

        normalized_name = normalize_arabic(
            item["file_name"]
        )

        # تجاهل بعض النتائج غير المرغوبة
        if any(
            normalized_name.startswith(prefix)
            for prefix in forbidden_prefixes
        ):

            continue

        if normalized_name.startswith(
            normalized_query
        ):

            starts_with.append(
                item
            )

        else:

            contains.append(
                item
            )

    results = (
        starts_with
        + contains
    )

    # ========================================================
    # لم نجد شيئاً
    # ========================================================

    if not results:

        if status_message:

            try:

                await status_message.edit_text(
                    f"❌ لم يتم العثور على ملف يطابق:\n"
                    f"`{clean_query}`",
                    parse_mode="Markdown",
                )

            except Exception:

                pass

        elif chat_type == "private":

            await update.message.reply_text(
                f"❌ لم يتم العثور على ملف يطابق:\n"
                f"`{clean_query}`",
                parse_mode="Markdown",
            )

        return

    # ========================================================
    # ترتيب الأجزاء
    # ========================================================

    results.sort(
        key=lambda item: (
            item["part"],
            item["message_id"],
        )
    )

    # ========================================================
    # إذا كانت هناك أجزاء:
    # أرسل الأجزاء.
    #
    # إذا لم تكن هناك أجزاء:
    # أرسل أفضل نتيجة واحدة.
    # ========================================================

    part_results = [

        item
        for item in results
        if item["part"] != 9999

    ]

    if part_results:

        results_to_forward = (
            part_results
        )

    else:

        results_to_forward = [
            results[0]
        ]

    # ========================================================
    # إرسال الملفات
    #
    # مهم جداً:
    # لا يتم تنزيل الملف.
    #
    # Telegram يقوم بتحويل الرسالة الموجودة
    # في القناة مباشرة إلى المجموعة.
    # ========================================================

    sent_count = 0

    for item in results_to_forward:

        try:

            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=CHANNEL_ID,
                message_id=item["message_id"],
            )

            sent_count += 1

            await asyncio.sleep(
                0.5
            )

        except Exception as e:

            print(
                f"[Forward Error] "
                f"message_id={item['message_id']}: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # تحديث رسالة الحالة
    # ========================================================

    if status_message:

        try:

            if sent_count > 0:

                await status_message.edit_text(
                    f"✅ تم العثور على وإرسال "
                    f"{sent_count} ملف."
                )

            else:

                await status_message.edit_text(
                    "❌ تم العثور على الملف، "
                    "لكن تعذر تحويله إلى المحادثة."
                )

        except Exception:

            pass


# ============================================================
# /start
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    chat_type = update.effective_chat.type

    # ========================================================
    # المجموعة
    # ========================================================

    if chat_type in (
        "group",
        "supergroup",
    ):

        if not await is_allowed_group(
            update,
            context,
        ):

            return

    # ========================================================
    # الخاص
    # ========================================================

    if chat_type == "private":

        if user_id in ADMIN_IDS:

            await update.message.reply_text(
                ADMIN_WELCOME_TEXT,
                parse_mode="Markdown",
            )

        else:

            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

    # ========================================================
    # المجموعة
    # ========================================================

    else:

        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"

            f"للبحث عن أي كتاب، يمكنك:\n"

            f"1️⃣ الإشارة للبوت: "
            f"`@{BOT_USERNAME} اسم الكتاب`\n"

            f"2️⃣ أو عمل Reply على رسالة للبوت "
            f"وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown",
        )


# ============================================================
# /help
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    chat_type = update.effective_chat.type

    # ========================================================
    # المجموعة
    # ========================================================

    if chat_type in (
        "group",
        "supergroup",
    ):

        if not await is_allowed_group(
            update,
            context,
        ):

            return

        await update.message.reply_text(
            f"أهلاً بكم في مجموعة مجتمع القراءة! 📚\n\n"

            f"للبحث عن أي كتاب، يمكنك:\n"

            f"1️⃣ الإشارة للبوت: "
            f"`@{BOT_USERNAME} اسم الكتاب`\n"

            f"2️⃣ أو عمل Reply على رسالة للبوت "
            f"وكتابة اسم الكتاب مباشرة.",
            parse_mode="Markdown",
        )

    # ========================================================
    # الخاص
    # ========================================================

    elif chat_type == "private":

        if user_id in ADMIN_IDS:

            await update.message.reply_text(
                ADMIN_HELP_TEXT,
                parse_mode="Markdown",
            )

        else:

            await update.message.reply_text(
                RESTRICTED_TEXT,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )


# ============================================================
# تشغيل Pyrogram عند بدء البوت
# ============================================================

async def post_init(
    application,
):

    print(
        "========================================"
    )

    print(
        "Starting Reading Library Bot..."
    )

    print(
        "Connecting to Telegram with Pyrogram..."
    )

    try:

        client = create_pyrogram_client()

        if not client.is_connected:

            await client.start()

        me = await client.get_me()

        print(
            f"Pyrogram connected successfully."
        )

        print(
            f"Bot ID: {me.id}"
        )

        print(
            f"Bot username: @{me.username}"
        )

        # ----------------------------------------------------
        # التأكد من الوصول إلى القناة
        # ----------------------------------------------------

        chat = await client.get_chat(
            CHANNEL_ID
        )

        print(
            f"Library channel connected: {chat.title}"
        )

        print(
            f"Channel ID: {CHANNEL_ID}"
        )

    except Exception as e:

        print(
            "========================================"
        )

        print(
            "[Pyrogram Startup Error]"
        )

        print(
            type(e).__name__,
            str(e),
        )

        print(
            "========================================"
        )

        # لا نوقف Bot API هنا.
        # إذا كان هناك خطأ في Pyrogram سيظهر في Logs
        # ونستطيع إصلاحه دون أن يكون الخطأ مخفياً.

    print(
        "========================================"
    )

    print(
        "Bot initialization completed."
    )

    print(
        "========================================"
    )


# ============================================================
# إيقاف Pyrogram
# ============================================================

async def post_shutdown(
    application,
):

    global pyro_client

    if pyro_client is None:

        return

    try:

        if pyro_client.is_connected:

            await pyro_client.stop()

            print(
                "Pyrogram stopped successfully."
            )

    except Exception as e:

        print(
            "[Pyrogram Shutdown Error]",
            type(e).__name__,
            str(e),
        )


# ============================================================
# تشغيل البرنامج
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        "Reading Library Bot"
    )

    print(
        "Starting..."
    )

    print(
        "========================================"
    )

    # إنشاء قاعدة بيانات المجموعات فقط
    init_db()

    # --------------------------------------------------------
    # التأكد من وجود التوكن داخل الكود
    # --------------------------------------------------------

    if not TOKEN:

        raise RuntimeError(
            "Bot TOKEN is empty."
        )

    if not API_ID:

        raise RuntimeError(
            "API_ID is empty."
        )

    if not API_HASH:

        raise RuntimeError(
            "API_HASH is empty."
        )

    # --------------------------------------------------------
    # إنشاء تطبيق Telegram Bot API
    # --------------------------------------------------------

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # --------------------------------------------------------
    # الأوامر
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # --------------------------------------------------------
    # عند إضافة البوت إلى مجموعة
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            on_added_to_group,
        )
    )

    # --------------------------------------------------------
    # عند خروج البوت من المجموعة
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            on_bot_left_group,
        )
    )

    # --------------------------------------------------------
    # الرسائل النصية فقط
    #
    # ملاحظة:
    # هذا الجزء لا يجعل البوت يتعامل مع ملفات المستخدمين.
    # نستخدم النص فقط كـ "طلب بحث".
    #
    # أما الملفات نفسها في القناة فلا يتم التعامل معها
    # إلا إذا كانت Document.
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.GROUPS,
            search_and_forward,
        )
    )

    # --------------------------------------------------------
    # الخاص للمشرف
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            search_and_forward,
        )
    )

    print(
        "البوت جاهز ويعمل..."
    )

    print(
        "لا توجد أرشفة للكتب."
    )

    print(
        "البحث يتم مباشرة في سجل القناة."
    )

    print(
        "التعامل مع الكتب يقتصر على Documents."
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # تشغيل البوت
    # --------------------------------------------------------

    application.run_polling(
        drop_pending_updates=False
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    main()
