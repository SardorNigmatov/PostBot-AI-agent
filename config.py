import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Yo‘llar va .env
# ---------------------------------------------------------------------------

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
ENV_PATH: Final[Path] = BASE_DIR / ".env"

# PythonAnywhere yoki terminal qaysi papkadan ishga tushirilishidan qat’i nazar,
# aynan loyiha ichidagi .env fayl o‘qiladi.
load_dotenv(dotenv_path=ENV_PATH, override=False)


# ---------------------------------------------------------------------------
# Environment qiymatlarini xavfsiz o‘qish
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Majburiy environment qiymatini oladi, bo‘lmasa aniq xato beradi."""
    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"{name} topilmadi. Uni {ENV_PATH} fayliga yoki "
            "PythonAnywhere environment sozlamalariga kiriting."
        )

    return value.strip()


def _get_int_env(
    name: str,
    default: int | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Environment qiymatini int ga o‘giradi va chegaralarini tekshiradi."""
    raw_value = os.getenv(name)

    if raw_value is None or not raw_value.strip():
        if default is None:
            raise RuntimeError(f"{name} majburiy qiymat, lekin topilmadi.")
        value = default
    else:
        try:
            value = int(raw_value.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"{name} butun son bo‘lishi kerak. Hozirgi qiymat: {raw_value!r}"
            ) from exc

    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} kamida {minimum} bo‘lishi kerak.")

    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} ko‘pi bilan {maximum} bo‘lishi kerak.")

    return value


# ---------------------------------------------------------------------------
# Telegram bot va Gemini
# ---------------------------------------------------------------------------

BOT_TOKEN: Final[str] = _require_env("BOT_TOKEN")
ADMIN_ID: Final[int] = _get_int_env("ADMIN_ID", minimum=1)
CHANNEL_ID: Final[str] = _require_env("CHANNEL_ID")
GEMINI_API_KEY: Final[str] = _require_env("GEMINI_API_KEY")

# Webhook URL manzilini taxmin qilib bo'lmasligi uchun tasodifiy uzun qiymat.
# .env fayliga generatsiya qilib qo'ying, masalan:
#   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
WEBHOOK_SECRET: Final[str] = _require_env("WEBHOOK_SECRET")


# ---------------------------------------------------------------------------
# Kunlik post oynasi
# ---------------------------------------------------------------------------

POST_WINDOW_START_HOUR: Final[int] = _get_int_env(
    "POST_WINDOW_START_HOUR",
    default=8,
    minimum=0,
    maximum=23,
)

POST_WINDOW_END_HOUR: Final[int] = _get_int_env(
    "POST_WINDOW_END_HOUR",
    default=22,
    minimum=0,
    maximum=23,
)

if POST_WINDOW_START_HOUR >= POST_WINDOW_END_HOUR:
    raise RuntimeError(
        "POST_WINDOW_START_HOUR POST_WINDOW_END_HOUR dan kichik bo‘lishi kerak. "
        f"Hozirgi qiymatlar: {POST_WINDOW_START_HOUR} va {POST_WINDOW_END_HOUR}."
    )


# ---------------------------------------------------------------------------
# Telethon statistikasi
# ---------------------------------------------------------------------------

# Botning asosiy ishlashi uchun majburiy emas.
# Faqat telethon_stats.py ishlatilsa kerak bo‘ladi.
_raw_telegram_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
TELEGRAM_API_HASH: Final[str | None] = (
    os.getenv("TELEGRAM_API_HASH", "").strip() or None
)

if _raw_telegram_api_id:
    try:
        TELEGRAM_API_ID: Final[int | None] = int(_raw_telegram_api_id)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_API_ID butun son bo‘lishi kerak.") from exc
else:
    TELEGRAM_API_ID = None

if bool(TELEGRAM_API_ID) != bool(TELEGRAM_API_HASH):
    raise RuntimeError(
        "TELEGRAM_API_ID va TELEGRAM_API_HASH birga kiritilishi kerak. "
        "Faqat bittasini kiritmang."
    )


# ---------------------------------------------------------------------------
# Ma’lumotlar bazasi
# ---------------------------------------------------------------------------

DATA_DIR: Final[Path] = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH: Final[str] = str(DATA_DIR / "posts.db")


# ---------------------------------------------------------------------------
# Post mavzulari
# ---------------------------------------------------------------------------

# Ichki kalitlar bazada saqlanishi mumkin, shu sabab nomlarini o‘zgartirmang.
TOPIC_TYPES: Final[tuple[str, ...]] = (
    "qollanma",   # AI/ML/CV/NLP: ilmiy maqola, kitob yoki tutorial
    "yangilik",   # AI/ML/CV/NLP sohasidagi yangiliklar
    "intervyu",   # AI/ML kompaniyalari intervyu savollari + kod bilan yechim
)

TOPIC_LABELS: Final[dict[str, str]] = {
    "qollanma": "📘 Qo'llanma va manbalar",
    "yangilik": "📰 AI yangiliklari",
    "intervyu": "🎤 Intervyu savoli",
}

TOPIC_HASHTAGS: Final[dict[str, str]] = {
    "qollanma": "#AI #MachineLearning #DeepLearning #Tutorial",
    "yangilik": "#AI #AInews #MachineLearning #Yangiliklar",
    "intervyu": "#MLInterview #AIJobs #CodingInterview #Career",
}

if set(TOPIC_TYPES) != set(TOPIC_LABELS):
    raise RuntimeError(
        "TOPIC_TYPES va TOPIC_LABELS kalitlari bir-biriga mos emas."
    )

if set(TOPIC_TYPES) != set(TOPIC_HASHTAGS):
    raise RuntimeError(
        "TOPIC_TYPES va TOPIC_HASHTAGS kalitlari bir-biriga mos emas."
    )


# ---------------------------------------------------------------------------
# Yangilik RSS manbalari
# ---------------------------------------------------------------------------

# (url, feed_is_ai_specific)
# feed_is_ai_specific=True bo‘lsa NEWS_KEYWORDS filtri qo‘llanmasligi mumkin.
NEWS_RSS_FEEDS: Final[tuple[tuple[str, bool], ...]] = (
    # Rasmiy AI laboratoriyalari (eng ishonchli birlamchi manba)
    ("https://openai.com/news/rss.xml", True),
    ("https://huggingface.co/blog/feed.xml", True),

    # AI'ga ixtisoslashgan nashrlar
    ("https://www.marktechpost.com/feed/", True),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", True),
    ("https://venturebeat.com/category/ai/feed/", True),
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", True),

    # Ilmiy maqolalar (arXiv) - "qollanma" turi uchun ham foydali
    ("https://export.arxiv.org/rss/cs.AI", True),   # Sun'iy intellekt
    ("https://export.arxiv.org/rss/cs.LG", True),   # Machine Learning
    ("https://export.arxiv.org/rss/cs.CL", True),   # NLP
    ("https://export.arxiv.org/rss/cs.CV", True),   # Computer Vision

    # Umumiy texnologiya - keyword filtri qo'llaniladi
    ("https://www.technologyreview.com/feed/", False),
)

NEWS_KEYWORDS: Final[tuple[str, ...]] = (
    # Umumiy AI
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "neural network",
    "generative ai",
    # Modellar va kompaniyalar
    "llm",
    "large language model",
    "gpt",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "llama",
    "mistral",
    "hugging face",
    "deepmind",
    # NLP
    "nlp",
    "natural language processing",
    "transformer",
    "embedding",
    "chatbot",
    # Computer Vision
    "computer vision",
    "image recognition",
    "object detection",
    "diffusion model",
    "text-to-image",
    # Infratuzilma va tadqiqot
    "nvidia",
    "gpu",
    "benchmark",
    "fine-tuning",
    "training data",
    "ai research",
    "ai model",
    "ai agent",
)

# ---------------------------------------------------------------------------
# HTTP proksi (PythonAnywhere bepul akkaunti uchun)
# ---------------------------------------------------------------------------
# PythonAnywhere bepul tarifida tashqi internetga faqat proksi orqali
# chiqiladi. Lokal kompyuterda bu bo'sh qoladi va proksi ishlatilmaydi.
#
# .env fayliga qo'shing (faqat serverda):
#   PROXY_URL=http://proxy.server:3128

PROXY_URL: Final[str | None] = os.getenv("PROXY_URL", "").strip() or None

if PROXY_URL:
    # httpx (google-genai) va urllib (feedparser) muhit o'zgaruvchilarini
    # o'zi o'qiydi. aiohttp o'qimaydi - unga alohida beriladi (bot.py da).
    os.environ.setdefault("HTTP_PROXY", PROXY_URL)
    os.environ.setdefault("HTTPS_PROXY", PROXY_URL)
    os.environ.setdefault("http_proxy", PROXY_URL)
    os.environ.setdefault("https_proxy", PROXY_URL)