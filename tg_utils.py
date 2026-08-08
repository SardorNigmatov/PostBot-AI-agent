import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import TOPIC_LABELS, TOPIC_HASHTAGS

logger = logging.getLogger(__name__)

SEPARATOR = "─" * 22


async def safe_send_message(bot: Bot, chat_id, text: str, parse_mode: str = "Markdown", **kwargs):
    """
    Xabarni yuboradi. Gemini generatsiya qilgan matnda ba'zan Telegram Markdown
    formatiga mos kelmaydigan belgilar (masalan, juftlanmagan * yoki _) bo'lishi
    mumkin - shunda Telegram xato qaytaradi. Shu holatda xabar oddiy matn
    (parse_mode=None) sifatida qayta yuboriladi, bot yiqilib qolmaydi.
    """
    try:
        return await bot.send_message(chat_id, text, parse_mode=parse_mode, **kwargs)
    except TelegramBadRequest as e:
        logger.warning(f"'{parse_mode}' bilan yuborishda xatolik, oddiy matn sifatida qayta urinilmoqda: {e}")
        return await bot.send_message(chat_id, text, parse_mode=None, **kwargs)


async def safe_edit_text(message, text: str, parse_mode: str = "Markdown", **kwargs):
    """edit_text uchun ham xuddi safe_send_message kabi Markdown fallback."""
    try:
        return await message.edit_text(text, parse_mode=parse_mode, **kwargs)
    except TelegramBadRequest as e:
        logger.warning(f"Edit uchun '{parse_mode}' bilan xatolik, oddiy matn bilan qayta urinilmoqda: {e}")
        return await message.edit_text(text, parse_mode=None, **kwargs)


def extract_title(content: str, max_len: int = 60) -> str:
    """Post matnining birinchi qatorini (sarlavhasini) statistikada ko'rsatish uchun tozalab qaytaradi."""
    title = content.partition("\n")[0].strip()
    # content_generator._ensure_bold_title sarlavhani bitta yulduzcha juftligi
    # bilan formatlaydi (*Sarlavha*), shuning uchun ** bilan bir qatorda
    # yakka * ni ham olib tashlash kerak - aks holda "*Sarlavha*" deb chiqadi.
    title = title.replace("**", "").replace("*", "").strip()
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title


def format_post_preview(topic_type: str, content: str) -> str:
    """Adminga ko'rsatiladigan post oldindan ko'rishni chiroyli qatorlar bilan bezaydi."""
    label = TOPIC_LABELS.get(topic_type, topic_type)
    return (
        f"🆕 *Yangi post tayyor*\n"
        f"🏷 Mavzu: *{label}*\n"
        f"{SEPARATOR}\n\n"
        f"{content}\n\n"
        f"{SEPARATOR}\n"
        f"👇 Tasdiqlaysiz, tahrirlaysiz yoki qayta generatsiya qilamizmi?"
    )


def format_channel_post(topic_type: str, content: str) -> str:
    """Kanalga joylanadigan yakuniy matn: kontent + mavzuga mos hashtaglar (mavzu yorlig'isiz)."""
    hashtags = TOPIC_HASHTAGS.get(topic_type, "")
    parts = [content]
    if hashtags:
        parts += ["", hashtags]
    return "\n".join(parts)


def build_post_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Post oldindan ko'rish xabari ostidagi asosiy tugmalar: tasdiqlash / tahrirlash / qayta generatsiya / bekor qilish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve:{post_id}"),
            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"edit:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Qayta generatsiya", callback_data=f"regen:{post_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"reject:{post_id}"),
        ],
    ])


def build_topic_choice_keyboard() -> InlineKeyboardMarkup:
    """/generate bosilganda mavzuni tanlash uchun inline tugmalar."""
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"gen_topic:{key}")]
        for key, label in TOPIC_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------------------------------------------------------------------
# Doimiy tugmalar paneli (reply keyboard)
# ---------------------------------------------------------------------------
# Bu tugmalar chat oynasining pastida DOIM ko'rinib turadi - foydalanuvchi
# har safar "/" yozib buyruq qidirmasligi kerak.

BTN_GENERATE = "📝 Post yaratish"
BTN_STATS = "📊 Statistika"
BTN_MODE = "⚙️ Rejim"
BTN_STATUS = "🕒 Bugungi holat"


def build_main_keyboard() -> ReplyKeyboardMarkup:
    """Chat pastida doim turadigan asosiy tugmalar paneli."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_GENERATE), KeyboardButton(text=BTN_STATUS)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_MODE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Tugmani tanlang yoki buyruq yozing",
    )