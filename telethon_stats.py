"""
IXTIYORIY MODUL: Kanal postlarining KO'RISHLAR SONINI (views) olish uchun.

Nega alohida? Telegram Bot API'da kanal postining necha marta ko'rilgani
haqida ma'lumot YO'Q - bu faqat Telegram'ning "user" client protokoli
(MTProto) orqali, ya'ni sening shaxsiy akkaunting nomidan olinadi.

Sozlash (bir marta qo'lda bajariladi):
1. https://my.telegram.org ga kirib API_ID va API_HASH ol
2. .env fayliga TELEGRAM_API_ID va TELEGRAM_API_HASH ni yoz
3. Terminalda: python telethon_stats.py
   - birinchi ishga tushirishda telefon raqami va SMS kod so'raladi
   - muvaffaqiyatli login qilingandan so'ng "session.session" fayli yaratiladi
   - shundan keyin bu skript qayta login so'ramasdan ishlaydi

Bu skriptni cron orqali (masalan har soatda) alohida ishga tushirib,
posts jadvalidagi views ustunini yangilab turish mumkin.
"""

import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetMessagesViewsRequest

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, CHANNEL_ID
from db import get_recent_posted, update_views

SESSION_NAME = "session"


async def update_all_views():
    client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await client.start()

    channel = await client.get_entity(CHANNEL_ID)
    posts = get_recent_posted(limit=20)
    message_ids = [p["channel_message_id"] for p in posts if p["channel_message_id"]]

    if not message_ids:
        print("Yangilanadigan post topilmadi.")
        await client.disconnect()
        return

    result = await client(GetMessagesViewsRequest(
        peer=channel, id=message_ids, increment=False
    ))

    for msg_id, views_info in zip(message_ids, result.views):
        views = views_info.views or 0
        update_views(msg_id, views)
        print(f"Post {msg_id}: {views} ko'rish")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(update_all_views())
