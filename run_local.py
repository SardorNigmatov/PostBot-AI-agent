"""
LOKAL SINOV UCHUN: botni o'z kompyuteringizda polling rejimida ishga tushiradi.

Nega alohida fayl?
wsgi.py + bot.py webhook arxitekturasiga mo'ljallangan - u yerda Telegram
sizning serveringizga so'rov yuboradi. Kompyuterda ommaviy HTTPS manzil
yo'q, shuning uchun webhook ishlamaydi. Bu fayl esa aksincha ishlaydi:
bot o'zi Telegram'dan yangi xabarlarni so'rab turadi (polling).

ISHLATISH:
    python run_local.py

To'xtatish: Ctrl+C

MUHIM: Bu fayl ishlab turganda PythonAnywhere'dagi webhook o'chirilgan
bo'lishi kerak - aks holda Telegram update'larni ikkiga bo'lib yuboradi.
Webhook'ni o'chirish:  python setup_webhook.py delete
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from config import BOT_TOKEN, ADMIN_ID
from bot import dp, setup_bot_commands
from db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Kunlik postni qanchalik tez-tez tekshirish (soniyada).
# Webhook versiyasida buni tashqi cron qiladi, bu yerda ichki loop qiladi.
DAILY_CHECK_INTERVAL_SECONDS = 600  # 10 daqiqa


async def _daily_check_loop(bot: Bot):
    """
    Fon vazifasi: har 10 daqiqada "bugungi post vaqti keldimi?" deb
    tekshiradi. maybe_run_daily_job o'zi atomik claim qiladi, shuning uchun
    tez-tez chaqirilishi xavfsiz.
    """
    from scheduler import maybe_run_daily_job

    while True:
        try:
            await maybe_run_daily_job(bot, ADMIN_ID)
        except Exception:
            logger.exception("Kunlik tekshiruvda xatolik")

        await asyncio.sleep(DAILY_CHECK_INTERVAL_SECONDS)


async def main():
    init_db()
    logger.info("Baza tayyor.")

    bot = Bot(token=BOT_TOKEN, session=AiohttpSession())

    # Webhook o'rnatilgan bo'lsa, polling ishlamaydi - avval uni olib tashlaymiz.
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook o'chirildi, polling rejimiga o'tildi.")

    # Buyruqlar menyusini ro'yxatdan o'tkazish - "/" bosilganda ko'rinadi.
    await setup_bot_commands(bot)

    daily_task = asyncio.create_task(_daily_check_loop(bot))

    try:
        logger.info("Bot ishga tushdi. To'xtatish uchun Ctrl+C bosing.")
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "message_reaction_count"],
        )
    finally:
        daily_task.cancel()
        try:
            await daily_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        logger.info("Bot to'xtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")