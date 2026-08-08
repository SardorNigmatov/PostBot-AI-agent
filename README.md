<<<<<<< HEAD
# 🤖 Telegram Kontent Agenti

AI/ML sohasidagi Telegram kanali uchun **avtomatik kontent agenti**: har kuni
belgilangan vaqt oralig'ida post tayyorlaydi, tasdiqlash uchun yuboradi va
kanal statistikasini kuzatib boradi.

> Kontent generatsiyasi **Google Gemini API** orqali amalga oshiriladi —
> bepul tarifda ([aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
> dan kalit olinadi). Kunlik so'rov cheklovi bor, lekin kuniga bir-ikki post
> uchun bemalol yetarli.

---

## ✨ Imkoniyatlar

- **Kunlik avtomatik post** — belgilangan oyna ichida (masalan 08:00–22:00)
  tasodifiy vaqt tanlanadi
- **Ikki rejim** — tasdiqlash bilan yoki to'liq avtomatik
- **Tugmali interfeys** — tasdiqlash, tahrirlash, qayta generatsiya, bekor qilish
- **AI yangiliklari** — RSS manbalardan avtomatik topib, o'zbek tilida tahlil qiladi
- **Statistika** — obunachilar, reaksiyalar, ko'rishlar; eng ommabop postlar
- **Ikki ishga tushirish rejimi** — lokal (polling) va server (webhook)

---

## 📚 Post mavzulari

Mavzular navbat bilan (round-robin) aylanadi:

| Mavzu | Mazmuni |
|---|---|
| 📘 **Qo'llanma va manbalar** | AI/ML/CV/NLP: ilmiy maqolalar, kitoblar, tutoriallar |
| 📰 **AI yangiliklari** | RSS manbalardan olingan yangiliklar tahlili |
| 🎤 **Intervyu savoli** | AI/ML kompaniyalari intervyu savollari + kod bilan yechim |

Mavzularni `config.py` (`TOPIC_TYPES`, `TOPIC_LABELS`, `TOPIC_HASHTAGS`) va
promptlarni `content_generator.py` (`TOPIC_PROMPTS`) orqali o'zgartirish mumkin.

---

## 🗂 Loyiha tuzilishi

```
Postproject/
├── bot.py                 # Handlerlar: buyruqlar, tugmalar, reaksiyalar
├── config.py              # Sozlamalar, mavzular, RSS manbalar
├── content_generator.py   # Gemini orqali post yaratish
├── news_fetcher.py        # RSS manbalardan yangilik olish
├── scheduler.py           # Kunlik reja va post oqimi
├── db.py                  # SQLite: postlar, statistika, reja
├── tg_utils.py            # Telegram formatlash va klaviaturalar
├── run_local.py           # ▶️ LOKAL ishga tushirish (polling)
├── wsgi.py                # ▶️ SERVER ishga tushirish (Flask webhook)
├── setup_webhook.py       # Webhook o'rnatish/tekshirish
├── telethon_stats.py      # Ko'rishlar statistikasi (ixtiyoriy)
├── .env                   # 🔒 Maxfiy kalitlar (git'ga yuklanmaydi)
└── data/posts.db          # SQLite bazasi
```

---

## ⚙️ Sozlash

### 1. Muhit va kutubxonalar

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

### 2. `.env` faylini yaratish

```bash
cp .env.example .env
```

Keyin `.env` faylini to'ldiring:

| O'zgaruvchi | Qayerdan olinadi | Majburiymi |
|---|---|---|
| `BOT_TOKEN` | Telegram [@BotFather](https://t.me/BotFather) → `/newbot` | ✅ |
| `ADMIN_ID` | [@userinfobot](https://t.me/userinfobot) ga `/start` | ✅ |
| `CHANNEL_ID` | Kanal username, masalan `@mening_kanalim` | ✅ |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | ✅ |
| `WEBHOOK_SECRET` | Tasodifiy satr (pastda ko'rsatilgan) | ✅ |
| `POST_WINDOW_START_HOUR` | Post oynasi boshi (standart: `8`) | ➖ |
| `POST_WINDOW_END_HOUR` | Post oynasi oxiri (standart: `22`) | ➖ |
| `GEMINI_MODEL` | Model nomi (standart: `gemini-3.5-flash`) | ➖ |
| `GEMINI_THINKING_LEVEL` | `MINIMAL`/`LOW`/`MEDIUM`/`HIGH` (standart: `LOW`) | ➖ |
| `TELEGRAM_API_ID` va `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org) | ➖ |

`WEBHOOK_SECRET` generatsiya qilish:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

> ⚠️ `WEBHOOK_SECRET` lokal rejimda ishlatilmaydi, lekin `config.py` uni
> majburiy talab qiladi — bo'sh qoldirsangiz dastur ishga tushmaydi.

### 3. Botni kanalga admin qilish

Kanal → Administrators → Add Admin → botni tanlang → **"Post messages"**
huquqini bering.

---

## ▶️ Ishga tushirish

### Variant A — Lokal (kompyuterda, sinov uchun)

```bash
python run_local.py
```

Polling rejimida ishlaydi. Kompyuter o'chsa bot ham to'xtaydi.

### Variant B — Server (PythonAnywhere, 24/7)

1. Web app yarating, WSGI faylida:

   ```python
   import sys
   sys.path.insert(0, '/home/FOYDALANUVCHI/Postproject')
   from wsgi import app as application
   ```

2. Webhook o'rnating:

   ```bash
   python setup_webhook.py set https://FOYDALANUVCHI.pythonanywhere.com
   ```

3. Kunlik postlar uchun tashqi cron ([cron-job.org](https://cron-job.org))
   sozlang — har 10–15 daqiqada:

   ```
   https://FOYDALANUVCHI.pythonanywhere.com/trigger-daily/WEBHOOK_SECRET
   ```

**Webhook holatini tekshirish:**

```bash
python setup_webhook.py info      # holat va xatolarni ko'rsatadi
python setup_webhook.py delete    # o'chirish (polling'ga qaytish uchun)
```

> ⚠️ Lokal va server rejimini bir vaqtda ishlatib bo'lmaydi — Telegram
> faqat bittasiga update yuboradi. `run_local.py` ishga tushganda webhook
> avtomatik o'chiriladi.

---

## 💬 Buyruqlar

Faqat `ADMIN_ID` uchun ishlaydi. Chat pastida doimiy tugmalar paneli ham bor.

| Buyruq | Vazifasi |
|---|---|
| `/start` | Tanishtirish, rejim va bugungi vaqt |
| `/generate` | Mavzu tanlab, darhol post yaratish |
| `/status` | Bugungi post vaqti va qancha qolgani |
| `/stats` | Kanal statistikasi va ommabop postlar |
| `/mode` | Rejimni almashtirish |

### Rejimlar

- **✅ Tasdiqlash bilan** *(standart)* — post avval sizga yuboriladi, siz
  tasdiqlagach kanalga chiqadi
- **🤖 Avtomatik** — post tasdiqlashsiz to'g'ridan-to'g'ri kanalga joylanadi

### Post tugmalari

| Tugma | Vazifasi |
|---|---|
| ✅ Tasdiqlash | Kanalga joylash |
| ✏️ Tahrirlash | Matnni o'zgartirish |
| 🔄 Qayta generatsiya | Shu mavzuda yangi post |
| ❌ Bekor qilish | Rad etish |

---

## 📊 Ko'rishlar statistikasi (ixtiyoriy)

Telegram **Bot API'da** post ko'rishlar soni yo'q — u faqat foydalanuvchi
akkaunti orqali (MTProto) olinadi. Shuning uchun alohida skript bor:

```bash
python telethon_stats.py
```

Birinchi ishga tushirishda telefon raqami va SMS kod so'raladi, keyin
`session.session` fayli orqali avtomatik ishlaydi.

Cron orqali muntazam yangilash:

```
0 * * * * cd /path/to/Postproject && venv/bin/python telethon_stats.py
```

> Obunachilar soni va reaksiyalar Bot API orqali ishlaydi — bu skript
> faqat **ko'rishlar** uchun kerak.

---

## 🔧 Sozlash bo'yicha maslahatlar

### Postlar qisqa yoki chala chiqsa

`content_generator.py` da `MAX_OUTPUT_TOKENS` ni oshiring. Gemini 3.x da bu
qiymat **fikrlash va javob uchun umumiy byudjet** — kichik qiymat fikrlashga
sarflanib ketadi va postga oz qoladi.

### Sifat yetarli bo'lmasa

`.env` ga qo'shing:

```env
GEMINI_THINKING_LEVEL=MEDIUM
```

Sifat oshadi, tezlik biroz pasayadi.

### `404 NOT_FOUND` xatosi chiqsa

Model nomi eskirgan. Hozirgi ro'yxatni ko'rish:

```python
from google import genai
client = genai.Client(api_key="SIZNING_KALITINGIZ")
for m in client.models.list():
    print(m.name)
```

Topilgan nomni `.env` ga yozing: `GEMINI_MODEL=...`

### RSS manbani qo'shish yoki olib tashlash

`config.py` dagi `NEWS_RSS_FEEDS` ro'yxatini tahrirlang. Ikkinchi qiymat
`True` bo'lsa kalit so'z filtri qo'llanilmaydi (manba to'liq AI'ga
ixtisoslashgan bo'lsa), `False` bo'lsa `NEWS_KEYWORDS` filtri ishlaydi.

---

## 🔒 Xavfsizlik

`.gitignore` faylida quyidagilar bo'lishi **shart**:

```gitignore
.env
*.session
*.session-journal
data/
*.db
venv/
__pycache__/
```

> ⚠️ `session.session` — Telegram akkauntingizga to'liq kirish huquqi.
> `.env` — bot tokeni va API kalitlari. Bular ochiq repozitoriyga
> **hech qachon** tushmasligi kerak.

Agar tasodifan yuklab yuborsangiz: @BotFather da `/revoke` bilan tokenni
bekor qiling, Gemini kalitini o'chirib yangisini yarating, va Telegram
sozlamalarida faol sessiyalarni tekshiring.

---

## 🗺 Keyingi qadamlar

- [ ] Post bilan birga rasm generatsiyasi
- [ ] Bir necha admin qo'llab-quvvatlash
- [ ] Haftalik statistika hisoboti
- [ ] Postni oldindan rejalashtirish (aniq sana/vaqtga)
- [ ] Statistika asosida mavzu tanlashni moslashtirish
=======
# ============================================
# MAXFIY - HECH QACHON YUKLANMASIN
# ============================================
.env
.env.local
*.session
*.session-journal

# Ma'lumotlar bazasi
data/
*.db
*.sqlite
*.sqlite3

# ============================================
# Python
# ============================================
venv/
env/
ENV/
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.pytest_cache/

# ============================================
# IDE va OS
# ============================================
.vscode/
.idea/
*.swp
.DS_Store
Thumbs.db

# ============================================
# Loglar
# ============================================
*.log
logs/
>>>>>>> 44a5837e2a35fadccc075a97dce297aab703163f
