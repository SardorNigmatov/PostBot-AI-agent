"""
Gemini API PythonAnywhere proksisi orqali haqiqatan ishlashini tekshiradi.

Ishlatish:
    cd ~/PostBot-AI-agent
    source venv/bin/activate
    python test_gemini.py
"""

import os

PROXY = "http://proxy.server:3128"
for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[var] = PROXY

from config import GEMINI_API_KEY  # noqa: E402
from google import genai  # noqa: E402

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

print(f"Proksi: {PROXY}")
print(f"Model:  {MODEL}\n")

client = genai.Client(api_key=GEMINI_API_KEY)

# 1) Mavjud modellar ro'yxati - ulanish ishlayotganini tasdiqlaydi
try:
    print("Mavjud modellar (birinchi 10 ta):")
    for i, m in enumerate(client.models.list()):
        if i >= 10:
            break
        print(f"  - {m.name}")
    print()
except Exception as e:
    print(f"❌ Modellar ro'yxatini olib bo'lmadi: {type(e).__name__}: {e}\n")

# 2) Haqiqiy generatsiya sinovi
try:
    resp = client.models.generate_content(
        model=MODEL,
        contents="Javob sifatida faqat 'ISHLAYAPTI' deb yoz.",
    )
    print(f"✅ GEMINI ISHLAYDI. Javob: {resp.text.strip()[:60]}")
except Exception as e:
    print(f"❌ Generatsiya xatosi: {type(e).__name__}: {e}")
