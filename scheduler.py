import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from config import (
    POST_WINDOW_START_HOUR,
    POST_WINDOW_END_HOUR,
    TOPIC_TYPES,
    TOPIC_LABELS,
    CHANNEL_ID,
)
from db import (
    next_topic_type,
    create_post,
    mark_news_used,
    mark_posted,
    get_auto_post_mode,
    get_or_create_daily_schedule,
    get_daily_schedule_status,
    claim_daily_run,
    DatabaseError,
)
from content_generator import generate_post_async
from news_fetcher import fetch_latest_news_item_async
from tg_utils import (
    safe_send_message,
    build_post_keyboard,
    format_post_preview,
    format_channel_post,
)

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Asia/Tashkent")

# Rejalashtirilgan vaqt o'tib ketgan bo'lsa, qancha kechikishgacha postni
# baribir joylash mumkin. Bundan ko'p kechiksa (masalan cron uzoq vaqt
# ishlamay qolgan bo'lsa) - post o'tkazib yuboriladi, chunki tunda yoki
# ertasi kuni chiqib qolishi noto'g'ri bo'lardi.
MAX_LATE_MINUTES = 90


class GeneratedPost(NamedTuple):
    topic_type: str | None
    post_id: int | None
    content: str | None
    error: Exception | None


def _random_time_for_day(local_day: date) -> datetime:
    """
    Berilgan kun uchun POST_WINDOW ichida (Asia/Tashkent vaqtida) random
    vaqt tanlaydi va UTC datetime sifatida qaytaradi.
    """
    start_local = datetime(
        local_day.year, local_day.month, local_day.day,
        POST_WINDOW_START_HOUR, 0, 0, tzinfo=LOCAL_TZ,
    )
    end_local = datetime(
        local_day.year, local_day.month, local_day.day,
        POST_WINDOW_END_HOUR, 0, 0, tzinfo=LOCAL_TZ,
    )

    delta_seconds = int((end_local - start_local).total_seconds())
    random_offset = random.randint(0, max(delta_seconds, 0))
    run_at_local = start_local + timedelta(seconds=random_offset)

    return run_at_local.astimezone(timezone.utc)


def _parse_utc(iso_text: str) -> datetime:
    parsed = datetime.fromisoformat(iso_text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def today_local_key() -> str:
    """Bugungi kun kaliti (Asia/Tashkent bo'yicha)."""
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ).date().isoformat()


def ensure_today_schedule() -> datetime:
    """
    Bugungi kun uchun rejalashtirilgan vaqtni qaytaradi (mahalliy vaqtda).
    Yozuv bo'lmasa yaratadi - shuning uchun /mode da avtomatik rejim
    tanlanganda darhol aniq vaqt ko'rsatish mumkin bo'ladi.
    """
    now_utc = datetime.now(timezone.utc)
    today_local = now_utc.astimezone(LOCAL_TZ).date()
    day_key = today_local.isoformat()

    planned = _random_time_for_day(today_local)
    run_at_iso = get_or_create_daily_schedule(day_key, planned.isoformat())

    return _parse_utc(run_at_iso).astimezone(LOCAL_TZ)


def peek_today_schedule() -> tuple[datetime, bool] | None:
    """
    Bugungi rejani faqat O'QIYDI (yaratmaydi).
    Qaytadi: (mahalliy vaqt, bajarilganmi) yoki None.
    """
    status = get_daily_schedule_status(today_local_key())
    if status is None:
        return None

    run_at_iso, executed = status
    return _parse_utc(run_at_iso).astimezone(LOCAL_TZ), executed


def format_schedule_line() -> str:
    """/start, /mode, /status uchun bugungi holat qatorini tayyorlaydi."""
    try:
        info = peek_today_schedule()
    except Exception:
        logger.exception("Kunlik rejani o'qib bo'lmadi")
        return "🕒 Bugungi post vaqti: aniqlab bo'lmadi"

    if info is None:
        return (
            f"🕒 Bugungi post vaqti hali belgilanmagan "
            f"(oyna: {POST_WINDOW_START_HOUR:02d}:00-{POST_WINDOW_END_HOUR:02d}:00)"
        )

    run_at_local, executed = info
    time_text = run_at_local.strftime("%H:%M")

    if executed:
        return f"🕒 Bugungi post vaqti: {time_text} - ✅ allaqachon bajarilgan"

    now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    if now_local < run_at_local:
        remaining = run_at_local - now_local
        hours, minutes = divmod(int(remaining.total_seconds() // 60), 60)
        left = f"{hours} soat {minutes} daqiqa" if hours else f"{minutes} daqiqa"
        return f"🕒 Bugungi post vaqti: {time_text} (taxminan {left} qoldi)"

    return f"🕒 Bugungi post vaqti: {time_text} - kutilmoqda"


async def _generate_and_save(topic_type: str | None = None) -> GeneratedPost:
    """Post generatsiya qilib, bazaga saqlaydi."""
    if topic_type is None:
        topic_type = next_topic_type(TOPIC_TYPES)

    news_item = None

    if topic_type == "yangilik":
        try:
            news_item = await fetch_latest_news_item_async()
        except Exception:
            logger.exception("RSS yangiligini olishda xatolik")
            news_item = None

        if news_item is None:
            logger.info("Yangi AI/IT yangiligi topilmadi, 'maqola' turiga almashtirildi.")
            topic_type = "maqola"

    try:
        content = await generate_post_async(topic_type, news_item=news_item)
    except Exception as e:
        logger.exception("Kontent generatsiyasida xatolik")
        return GeneratedPost(None, None, None, e)

    if news_item is not None:
        try:
            mark_news_used(news_item["link"])
        except Exception:
            logger.exception("Yangilikni 'ishlatilgan' deb belgilab bo'lmadi")

    try:
        post_id = create_post(topic_type, content)
    except (ValueError, DatabaseError) as e:
        logger.exception("Postni bazaga saqlashda xatolik")
        return GeneratedPost(None, None, None, e)

    return GeneratedPost(topic_type, post_id, content, None)


async def generate_and_request_approval(bot, admin_id, topic_type: str | None = None):
    """Post generatsiya qilib, adminga tasdiqlash uchun yuboradi."""
    topic_type, post_id, content, error = await _generate_and_save(topic_type)
    if error is not None:
        await safe_send_message(bot, admin_id, f"⚠️ Post generatsiya qilishda xatolik: {error}")
        return

    await safe_send_message(
        bot,
        admin_id,
        format_post_preview(topic_type, content),
        reply_markup=build_post_keyboard(post_id),
    )


async def generate_and_auto_post(bot, admin_id):
    """Avtomatik rejim: tasdiqlashsiz to'g'ridan-to'g'ri kanalga joylaydi."""
    topic_type, post_id, content, error = await _generate_and_save(None)
    if error is not None:
        await safe_send_message(bot, admin_id, f"⚠️ Avtomatik post generatsiya qilishda xatolik: {error}")
        return

    try:
        sent = await safe_send_message(bot, CHANNEL_ID, format_channel_post(topic_type, content))
    except Exception as e:
        logger.exception("Avtomatik kanalga joylashda xatolik")
        await safe_send_message(bot, admin_id, f"⚠️ Avtomatik post kanalga joylanmadi: {e}")
        return

    try:
        mark_posted(post_id, sent.message_id)
    except DatabaseError:
        logger.exception("mark_posted bajarilmadi")

    label = TOPIC_LABELS.get(topic_type, topic_type)
    await safe_send_message(bot, admin_id, f"🤖 Avtomatik rejimda yangi post kanalga joylandi ({label}).")


async def _daily_job_entrypoint(bot, admin_id):
    if get_auto_post_mode():
        await generate_and_auto_post(bot, admin_id)
    else:
        await generate_and_request_approval(bot, admin_id)


async def maybe_run_daily_job(bot, admin_id):
    """
    Webhook arxitekturasi uchun kirish nuqtasi. Tashqi cron har 10-15
    daqiqada chaqiradi.

    Muhim: rejalashtirilgan vaqt o'tib ketgan bo'lsa ham, MAX_LATE_MINUTES
    dan ko'p kechikkan bo'lsa post joylanmaydi - aks holda cron kechikib
    ishga tushganda post tunda yoki oyna tashqarisida chiqib ketardi.
    """
    now_utc = datetime.now(timezone.utc)
    today_local = now_utc.astimezone(LOCAL_TZ).date()
    day_key = today_local.isoformat()

    planned_run_at_utc = _random_time_for_day(today_local)

    try:
        run_at_iso = get_or_create_daily_schedule(day_key, planned_run_at_utc.isoformat())
    except DatabaseError:
        logger.exception("Kunlik rejani o'qib bo'lmadi")
        return

    run_at_utc = _parse_utc(run_at_iso)

    if now_utc < run_at_utc:
        return  # Hali vaqt kelmagan.

    lateness = now_utc - run_at_utc
    if lateness > timedelta(minutes=MAX_LATE_MINUTES):
        logger.warning(
            "Kunlik post o'tkazib yuborildi: %.0f daqiqa kechikish (day=%s)",
            lateness.total_seconds() / 60, day_key,
        )
        claim_daily_run(day_key)  # Qayta urinmasligi uchun belgilab qo'yamiz.
        return

    if not claim_daily_run(day_key):
        return  # Boshqa chaqiruv allaqachon bajargan.

    logger.info("Kunlik post ishga tushirilmoqda (day=%s, vaqt=%s UTC)", day_key, run_at_utc)
    await _daily_job_entrypoint(bot, admin_id)