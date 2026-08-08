# Telegram Kontent Agenti

ML/CV Telegram kanali uchun avtomatik post tayyorlash + tasdiqlash + statistika agenti.

> 💡 Kontent generatsiyasi uchun **Google Gemini API** ishlatiladi — bepul tarifda
> (aistudio.google.com/app/apikey dan kalit olinadi), kunlik so'rov cheklovi bor,
> lekin kuniga bitta post uchun bemalol yetarli.

## Sozlash

```bash
# 1. Virtual muhit
python3 -m venv venv
source venv/bin/activate

# 2. Kutubxonalar
pip install -r requirements.txt

# 3. .env faylini yaratish
cp .env.example .env
# .env faylini o'zingga moslab to'ldir (BOT_TOKEN, ADMIN_ID, CHANNEL_ID, GEMINI_API_KEY)
```

### Botni kanalga admin qilish
Kanalga bot @username orqali qo'shiladi va **"Posts" (postlarni yuborish)** huquqi beriladi.

### Botni ishga tushirish
```bash
python bot.py
```

Doim ishlab turishi uchun VPS'da `systemd` service yoki `screen`/`tmux` ichida ishlatish tavsiya etiladi.

### Buyruqlar (faqat ADMIN_ID uchun ishlaydi)
- `/start` - botni tanishtirish
- `/generate` - hozir yangi post generatsiya qilib, tasdiqlash uchun yuborish (kutmasdan test qilish uchun)
- `/stats` - kanal statistikasi (obunachilar, ko'rishlar, reaksiyalar)

## Ko'rishlar statistikasi (ixtiyoriy, qo'shimcha sozlash talab qiladi)

Bot API orqali post "views" (ko'rishlar) sonini olib bo'lmaydi. Buning uchun
`telethon_stats.py` skripti bor - u sening shaxsiy Telegram akkaunting nomidan
ishlaydi (bir marta login qilinadi, keyin session fayl orqali avtomatik ishlaydi).

```bash
python telethon_stats.py
```

Buni cron orqali har soatda ishga tushirish mumkin:
```
0 * * * * cd /path/to/telegram_content_bot && venv/bin/python telethon_stats.py
```

## AI/IT yangiliklari (avtomatik)

Mavzu aylanishida (`TOPIC_TYPES` ichida `"yangilik"`) bot avtomatik ravishda
`news_fetcher.py` orqali bepul RSS manbalardan (TechCrunch AI, VentureBeat AI,
MIT Technology Review, The Verge, Ars Technica, arXiv cs.AI) eng so'nggi
ishlatilmagan yangilikni topadi va Gemini orqali o'zbek tiliga tahlil qildirib
post qiladi, oxirida manba havolasi bilan birga.

- Bir marta ishlatilgan yangilik qayta postlanmaydi (`used_news` jadvali orqali kuzatiladi)
- Agar yangi yangilik topilmasa, avtomatik ravishda `"maqola"` turiga almashtiriladi
- Manbalarni `config.py` dagi `NEWS_RSS_FEEDS` ro'yxatida o'zgartirish/qo'shish mumkin

## Mavzularni moslashtirish

`content_generator.py` faylidagi `TOPIC_PROMPTS` lug'atini o'zingning
kanal uslubiga moslab tahrirlashing mumkin.

## Keyingi qadamlar (istasang qo'shsa bo'ladi)

- Rasm/kartinka generatsiyasi (post bilan birga)
- Bir necha admin/moderator qo'llab-quvvatlash
- Post uchun avtomatik hashtag qo'shish
- Haftalik statistika hisoboti (avtomatik yuboriladigan)
