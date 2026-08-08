"""
Telegram webhook'ni o'rnatish / tekshirish / o'chirish skripti.

Webhook arxitekturasi ishlashi uchun Telegram'ga "update'larni qayerga
yuborish kerakligini" bir marta aytish shart. Bu qadam bajarilmasa, bot
umuman javob bermaydi - polling ham yo'q, webhook ham yo'q.

ISHLATISH (PythonAnywhere Bash konsolida yoki kompyuterda):

    # 1. Hozirgi holatni tekshirish
    python setup_webhook.py info

    # 2. Webhook o'rnatish (URL ni o'zingiznikiga almashtiring)
    python setup_webhook.py set https://foydalanuvchi.pythonanywhere.com

    # 3. O'chirish (masalan polling rejimiga qaytish uchun)
    python setup_webhook.py delete
"""

import asyncio
import sys

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from config import BOT_TOKEN, WEBHOOK_SECRET

ALLOWED_UPDATES = ["message", "callback_query", "message_reaction_count"]


async def show_info():
    bot = Bot(token=BOT_TOKEN, session=AiohttpSession())
    try:
        info = await bot.get_webhook_info()
        print(f"URL: {info.url or '(o‘rnatilmagan)'}")
        print(f"Kutayotgan update'lar: {info.pending_update_count}")
        print(f"Ruxsat etilgan turlar: {info.allowed_updates}")
        if info.last_error_message:
            print(f"⚠️ Oxirgi xato: {info.last_error_message}")
            print(f"   Vaqti: {info.last_error_date}")
        else:
            print("✅ Xatolar yo'q")
    finally:
        await bot.session.close()


async def set_webhook(base_url: str):
    base_url = base_url.rstrip("/")
    if not base_url.startswith("https://"):
        print("❌ URL https:// bilan boshlanishi kerak (Telegram faqat HTTPS qabul qiladi).")
        return

    webhook_url = f"{base_url}/webhook/{WEBHOOK_SECRET}"

    bot = Bot(token=BOT_TOKEN, session=AiohttpSession())
    try:
        await bot.set_webhook(
            url=webhook_url,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
        print(f"✅ Webhook o'rnatildi:\n   {webhook_url}")
        print("\nEndi cron-job.org da quyidagi manzilni har 10-15 daqiqada chaqirishni sozlang:")
        print(f"   {base_url}/trigger-daily/{WEBHOOK_SECRET}")
    finally:
        await bot.session.close()


async def delete_webhook():
    bot = Bot(token=BOT_TOKEN, session=AiohttpSession())
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        print("✅ Webhook o'chirildi.")
    finally:
        await bot.session.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "info":
        asyncio.run(show_info())
    elif command == "set":
        if len(sys.argv) < 3:
            print("Ishlatish: python setup_webhook.py set https://sizning-domeningiz.pythonanywhere.com")
            return
        asyncio.run(set_webhook(sys.argv[2]))
    elif command == "delete":
        asyncio.run(delete_webhook())
    else:
        print(f"Noma'lum buyruq: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()