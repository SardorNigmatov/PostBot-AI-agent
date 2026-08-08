import asyncio
import json
import logging
from functools import wraps

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, TOPIC_LABELS, PROXY_URL
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    MessageReactionCountUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeChat,
    Update,
)

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, TOPIC_LABELS
from db import (
    init_db,
    get_post,
    update_content,
    mark_posted,
    mark_status,
    update_reactions,
    get_recent_posted,
    get_auto_post_mode,
    set_auto_post_mode,
    claim_post_for_publishing,
    release_publish_claim,
    DatabaseError,
    STATUS_REJECTED,
)
from tg_utils import (
    safe_send_message,
    safe_edit_text,
    build_post_keyboard,
    build_topic_choice_keyboard,
    build_main_keyboard,
    format_post_preview,
    format_channel_post,
    extract_title,
    BTN_GENERATE,
    BTN_STATS,
    BTN_MODE,
    BTN_STATUS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MUHIM: bot obyekti global emas, har bir webhook chaqiruvi uchun yangi
# yaratiladi. Sabab: har chaqiruvda asyncio.run() yangi event loop ochadi,
# global bot esa eski (yopilgan) loopga bog'langan aiohttp sessiyani saqlaydi
# - natijada ikkinchi so'rovdan boshlab "Event loop is closed" xatosi chiqadi.
dp = Dispatcher(storage=MemoryStorage())


def _new_bot() -> Bot:
    """
    Har bir so'rov uchun yangi Bot (va yangi aiohttp sessiya) yaratadi.

    PythonAnywhere bepul akkauntida proksi majburiy - aiohttp muhit
    o'zgaruvchilaridagi proksini o'zi o'qimaydi, shuning uchun aniq beramiz.
    """
    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
    return Bot(token=BOT_TOKEN, session=session)


# ---------- Telegram buyruqlar menyusi ----------
# Bu bo'lmasa foydalanuvchi "/" bosganda buyruqlar ro'yxati ko'rinmaydi.

BOT_COMMANDS = [
    BotCommand(command="generate", description="📝 Yangi post yaratish"),
    BotCommand(command="status", description="🕒 Bugungi post vaqti"),
    BotCommand(command="stats", description="📊 Kanal statistikasi"),
    BotCommand(command="mode", description="⚙️ Rejimni o'zgartirish"),
    BotCommand(command="start", description="ℹ️ Yordam"),
]


async def setup_bot_commands(bot: Bot):
    """Telegram'ga buyruqlar ro'yxatini ro'yxatdan o'tkazadi."""
    try:
        await bot.set_my_commands(
            BOT_COMMANDS,
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )
        logger.info("Buyruqlar menyusi o'rnatildi.")
    except Exception:
        logger.exception("Buyruqlar menyusini o'rnatib bo'lmadi")


class EditState(StatesGroup):
    waiting_for_new_text = State()


def admin_only(handler):
    """
    Faqat ADMIN_ID dan kelgan Message yoki CallbackQuery uchun handlerni
    chaqiradi.
    """
    @wraps(handler)
    async def wrapper(event, *args, **kwargs):
        user = event.from_user
        if user is None or user.id != ADMIN_ID:
            if isinstance(event, CallbackQuery):
                await event.answer("Ruxsat yo'q", show_alert=True)
            return
        return await handler(event, *args, **kwargs)
    return wrapper


def _mode_label(auto: bool) -> str:
    return "🤖 Avtomatik (o'zi kanalga joylaydi)" if auto else "✅ Tasdiqlash bilan (har bir post tekshiriladi)"


# ---------- Buyruqlar ----------

@dp.message(Command("start"))
@admin_only
async def cmd_start(message: Message):
    from scheduler import format_schedule_line

    await setup_bot_commands(message.bot)

    mode_text = _mode_label(get_auto_post_mode())

    await message.answer(
        "👋 Salom! Men kanalingiz uchun kontent-agentman.\n\n"
        f"⚙️ Hozirgi rejim: {mode_text}\n"
        f"{format_schedule_line()}\n\n"
        "Pastdagi tugmalardan foydalaning yoki quyidagi buyruqlarni yozing:\n"
        "/generate - yangi post yaratish\n"
        "/status - bugungi post vaqti\n"
        "/stats - kanal statistikasi\n"
        "/mode - rejimni o'zgartirish",
        reply_markup=build_main_keyboard(),
    )


@dp.message(Command("status"))
@admin_only
async def cmd_status(message: Message):
    """Bugungi post vaqti va hozirgi rejimni ko'rsatadi."""
    from scheduler import format_schedule_line

    mode_text = _mode_label(get_auto_post_mode())
    await message.answer(
        f"⚙️ Rejim: {mode_text}\n{format_schedule_line()}",
        reply_markup=build_main_keyboard(),
    )


@dp.message(Command("generate"))
@admin_only
async def cmd_generate_now(message: Message):
    await message.answer(
        "📝 Qaysi mavzuda post generatsiya qilay?",
        reply_markup=build_topic_choice_keyboard(),
    )


@dp.message(Command("mode"))
@admin_only
async def cmd_mode(message: Message):
    current_label = _mode_label(get_auto_post_mode())

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🤖 Avtomatik rejim", callback_data="mode:auto"),
        InlineKeyboardButton(text="✅ Tasdiqlash rejimi", callback_data="mode:manual"),
    ]])
    await message.answer(
        f"Hozirgi rejim: {current_label}\n\n"
        "🤖 *Avtomatik* - kunlik post random vaqtda tasdiqlashsiz to'g'ridan-to'g'ri kanalga joylanadi.\n"
        "✅ *Tasdiqlash bilan* - har bir post avval sizga yuboriladi, faqat siz tasdiqlagach kanalga chiqadi.\n\n"
        "Qaysi rejimni tanlaysiz?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@dp.callback_query(F.data.startswith("mode:"))
@admin_only
async def cb_set_mode(callback: CallbackQuery):
    from scheduler import ensure_today_schedule, peek_today_schedule

    mode = callback.data.split(":", 1)[1]
    is_auto = mode == "auto"
    set_auto_post_mode(is_auto)

    lines = [f"✅ Rejim o'zgartirildi: {_mode_label(is_auto)}"]

    # Bugungi post vaqtini aniq ko'rsatamiz. ensure_today_schedule() yozuv
    # bo'lmasa yaratadi - shuning uchun rejim tanlangan zahoti foydalanuvchi
    # "bugun soat nechida post chiqadi" degan savolga javob oladi.
    try:
        status = peek_today_schedule()
        if status is None:
            run_at_local = ensure_today_schedule()
            executed = False
        else:
            run_at_local, executed = status

        time_text = run_at_local.strftime("%H:%M")
        if executed:
            lines.append(f"🕒 Bugungi post ({time_text}) allaqachon bajarilgan.")
            lines.append("Yangi rejim ertadan boshlab kuchga kiradi.")
        elif is_auto:
            lines.append(f"🕒 Bugun soat {time_text} da post avtomatik kanalga joylanadi.")
        else:
            lines.append(f"🕒 Bugun soat {time_text} da post tasdiqlash uchun yuboriladi.")
    except Exception:
        logger.exception("Kunlik vaqtni aniqlab bo'lmadi")
        lines.append("🕒 Bugungi post vaqtini aniqlab bo'lmadi.")

    await safe_edit_text(callback.message, "\n".join(lines))
    await callback.answer("Saqlandi!")


def _reaction_total(post) -> int:
    return sum(json.loads(post["reactions_json"] or "{}").values())


def _channel_message_link(message_id: int | None) -> str | None:
    if message_id and CHANNEL_ID and CHANNEL_ID.startswith("@"):
        return f"https://t.me/{CHANNEL_ID[1:]}/{message_id}"
    return None


@dp.message(Command("stats"))
@admin_only
async def cmd_stats(message: Message):
    bot = message.bot
    try:
        chat, member_count = await asyncio.gather(
            bot.get_chat(CHANNEL_ID),
            bot.get_chat_member_count(CHANNEL_ID),
        )
    except Exception as e:
        await message.answer(f"⚠️ Kanal ma'lumotini olishda xatolik: {e}")
        return

    lines = [f"📊 *{chat.title}* statistikasi", f"👥 Obunachilar: {member_count}", ""]

    all_posted = get_recent_posted(limit=1000)

    if not all_posted:
        lines.append("Hali joylangan postlar yo'q.")
        await safe_send_message(bot, message.chat.id, "\n".join(lines))
        return

    best_viewed = max(all_posted, key=lambda p: p["views"])
    best_reacted = max(all_posted, key=_reaction_total)

    if best_viewed["views"] > 0:
        lines.append("🏆 *Eng ko'p ko'rilgan post:*")
        lines.append(f"#{best_viewed['id']} — {extract_title(best_viewed['content'])}")
        lines.append(f"👁 {best_viewed['views']} ko'rish")
        link = _channel_message_link(best_viewed["channel_message_id"])
        if link:
            lines.append(f"[Postni ko'rish]({link})")
        lines.append("")

    if _reaction_total(best_reacted) > 0:
        lines.append("🔥 *Eng ko'p reaksiya olgan post:*")
        lines.append(f"#{best_reacted['id']} — {extract_title(best_reacted['content'])}")
        reactions = json.loads(best_reacted["reactions_json"] or "{}")
        lines.append("👍 " + ", ".join(f"{emoji} {count}" for emoji, count in reactions.items()))
        link = _channel_message_link(best_reacted["channel_message_id"])
        if link:
            lines.append(f"[Postni ko'rish]({link})")
        lines.append("")

    lines.append("*So'nggi postlar:*")
    for post in all_posted[:5]:
        reactions = json.loads(post["reactions_json"] or "{}")
        reactions_str = ", ".join(f"{emoji} {count}" for emoji, count in reactions.items()) or "—"
        lines.append(
            f"\n#{post['id']} ({post['topic_type']}) — {extract_title(post['content'])}\n"
            f"👁 Ko'rishlar: {post['views']}\n"
            f"👍 Reaksiyalar: {reactions_str}"
        )

    if all(p["views"] == 0 for p in all_posted):
        lines.append(
            "\n_Eslatma: ko'rishlar soni Bot API orqali olinmaydi. "
            "To'liq ko'rishlar statistikasi uchun telethon_stats.py skriptini sozlang._"
        )

    await safe_send_message(bot, message.chat.id, "\n".join(lines))


# ---------- Mavzu tanlash / qayta generatsiya ----------

@dp.callback_query(F.data.startswith("gen_topic:"))
@admin_only
async def cb_gen_topic(callback: CallbackQuery):
    from scheduler import generate_and_request_approval

    topic_type = callback.data.split(":", 1)[1]
    label = TOPIC_LABELS.get(topic_type, topic_type)
    await safe_edit_text(callback.message, f"⏳ {label} mavzusida post tayyorlanmoqda...")
    await callback.answer()
    await generate_and_request_approval(callback.bot, ADMIN_ID, topic_type=topic_type)


@dp.callback_query(F.data.startswith("regen:"))
@admin_only
async def cb_regen(callback: CallbackQuery):
    from scheduler import generate_and_request_approval

    post_id = int(callback.data.split(":")[1])
    post = get_post(post_id)
    if post is None:
        await callback.answer("Post topilmadi", show_alert=True)
        return

    topic_type = post["topic_type"]
    label = TOPIC_LABELS.get(topic_type, topic_type)

    try:
        mark_status(post_id, STATUS_REJECTED)
    except DatabaseError as e:
        logger.warning("Eski postni rad etib bo'lmadi: %s", e)

    await safe_edit_text(callback.message, f"🔄 {label} mavzusida qayta generatsiya qilinmoqda...")
    await callback.answer()
    await generate_and_request_approval(callback.bot, ADMIN_ID, topic_type=topic_type)


# ---------- Tugmalar (approve / edit / reject) ----------

@dp.callback_query(F.data.startswith("approve:"))
@admin_only
async def cb_approve(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    post = get_post(post_id)
    if post is None:
        await callback.answer("Post topilmadi", show_alert=True)
        return

    # Ikki marta bosilishdan himoya: faqat bitta chaqiruv claim oladi.
    if not claim_post_for_publishing(post_id):
        await callback.answer("Bu post allaqachon joylangan yoki bekor qilingan", show_alert=True)
        return

    try:
        sent = await safe_send_message(
            callback.bot,
            CHANNEL_ID,
            format_channel_post(post["topic_type"], post["content"]),
        )
    except Exception as e:
        logger.exception("Kanalga joylashda xatolik")
        release_publish_claim(post_id)
        await callback.answer(f"⚠️ Kanalga joylanmadi: {e}", show_alert=True)
        return

    try:
        mark_posted(post_id, sent.message_id)
    except DatabaseError as e:
        logger.exception("mark_posted bajarilmadi: %s", e)

    await safe_edit_text(callback.message, (callback.message.text or "") + "\n\n✅ Kanalga joylandi")
    await callback.answer("Joylandi!")


@dp.callback_query(F.data.startswith("reject:"))
@admin_only
async def cb_reject(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    try:
        mark_status(post_id, STATUS_REJECTED)
    except DatabaseError as e:
        await callback.answer(f"Bekor qilib bo'lmadi: {e}", show_alert=True)
        return

    await safe_edit_text(callback.message, (callback.message.text or "") + "\n\n❌ Bekor qilindi")
    await callback.answer("Bekor qilindi")


@dp.callback_query(F.data.startswith("edit:"))
@admin_only
async def cb_edit(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    await state.update_data(post_id=post_id)
    await state.set_state(EditState.waiting_for_new_text)
    await callback.message.answer("✏️ Yangi matnni yuboring (to'liq post matni sifatida):")
    await callback.answer()


@dp.message(EditState.waiting_for_new_text)
@admin_only
async def process_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("post_id")
    if post_id is None:
        await state.clear()
        await message.answer("⚠️ Tahrirlanayotgan post topilmadi. /generate bilan qaytadan boshlang.")
        return

    try:
        update_content(post_id, message.text or "")
    except (ValueError, DatabaseError) as e:
        await message.answer(f"⚠️ Saqlab bo'lmadi: {e}")
        return

    await state.clear()

    post = get_post(post_id)
    await safe_send_message(
        message.bot,
        message.chat.id,
        format_post_preview(post["topic_type"], post["content"]),
        reply_markup=build_post_keyboard(post_id),
    )


# ---------- Doimiy panel tugmalari ----------
# Tugma bosilganda oddiy matnli xabar keladi (masalan "📝 Post yaratish"),
# shuning uchun matnga qarab mos buyruqni chaqiramiz.
# MUHIM: bu handlerlar EditState dan KEYIN turishi kerak - aks holda
# tahrirlash rejimida tugma matni post matni sifatida saqlanib qolardi.

@dp.message(F.text == BTN_GENERATE)
@admin_only
async def btn_generate(message: Message):
    await cmd_generate_now(message)


@dp.message(F.text == BTN_STATUS)
@admin_only
async def btn_status(message: Message):
    await cmd_status(message)


@dp.message(F.text == BTN_STATS)
@admin_only
async def btn_stats(message: Message):
    await cmd_stats(message)


@dp.message(F.text == BTN_MODE)
@admin_only
async def btn_mode(message: Message):
    await cmd_mode(message)


# ---------- Reaksiyalarni kuzatish ----------

@dp.message_reaction_count()
async def on_reaction_count(update: MessageReactionCountUpdated):
    channel_username = str(CHANNEL_ID).lstrip("@")
    if (
        str(update.chat.id) != str(CHANNEL_ID)
        and (update.chat.username or "") != channel_username
    ):
        return

    reactions = {}
    for r in update.reactions:
        emoji = getattr(r.type, "emoji", None) or getattr(r.type, "custom_emoji_id", "custom")
        reactions[emoji] = r.total_count

    try:
        update_reactions(update.message_id, json.dumps(reactions, ensure_ascii=False))
    except (ValueError, DatabaseError):
        logger.exception("Reaksiyalarni saqlab bo'lmadi")


# ---------- Webhook uchun kirish nuqtasi ----------

_db_initialized = False


def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True


async def process_update_async(update_data: dict):
    """Telegram'dan webhook orqali kelgan bitta update'ni qayta ishlaydi."""
    _ensure_db()
    bot = _new_bot()
    try:
        update = Update.model_validate(update_data)
        await dp.feed_update(bot, update)
    finally:
        await bot.session.close()


def process_update_sync(update_data: dict):
    """WSGI (sinxron Flask) ichidan chaqirish uchun wrapper."""
    asyncio.run(process_update_async(update_data))


async def run_daily_check_async(admin_id: int):
    """Tashqi cron (/trigger-daily) tomonidan chaqiriladi."""
    from scheduler import maybe_run_daily_job

    _ensure_db()
    bot = _new_bot()
    try:
        await maybe_run_daily_job(bot, admin_id)
    finally:
        await bot.session.close()


def run_daily_check_sync(admin_id: int):
    asyncio.run(run_daily_check_async(admin_id))