"""
PythonAnywhere bepul akkauntida qaysi tashqi manzillar ishlashini tekshiradi.

Ishlatish (PythonAnywhere Bash konsolda):
    cd ~/PostBot-AI-agent
    source venv/bin/activate
    python test_proxy.py
"""

import urllib.request

PROXY = "http://proxy.server:3128"

TARGETS = [
    ("Telegram API", "https://api.telegram.org"),
    ("Gemini API", "https://generativelanguage.googleapis.com"),
    ("TechCrunch RSS", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat RSS", "https://venturebeat.com/category/ai/feed/"),
    ("The Verge RSS", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("OpenAI News RSS", "https://openai.com/news/rss.xml"),
    ("HuggingFace RSS", "https://huggingface.co/blog/feed.xml"),
    ("MIT Tech Review RSS", "https://www.technologyreview.com/feed/"),
]

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
)

print(f"Proksi: {PROXY}\n")
print(f"{'Manzil':<24} {'Holat'}")
print("-" * 60)

for name, url in TARGETS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=20) as resp:
            print(f"{name:<24} ✅ ISHLAYDI (HTTP {resp.status})")
    except Exception as e:
        msg = str(e)[:45]
        print(f"{name:<24} ❌ {type(e).__name__}: {msg}")

print("\nEslatma: ❌ bo'lgan manzillar PythonAnywhere ruxsat ro'yxatida yo'q.")
print("Ularni ro'yxatga qo'shishni so'rash: pythonanywhere.com/forums/")
