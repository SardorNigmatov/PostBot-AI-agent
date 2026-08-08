"""
PythonAnywhere "Web" tabida bu faylni Flask app sifatida ko'rsating.

PythonAnywhere odatda o'zi flask_app.py yaratadi - o'sha faylning tarkibini
shu bilan almashtiring, yoki shu yerdan import qiling:

    from wsgi import app  # flask_app.py ichida
"""

import logging

from flask import Flask, request

from bot import process_update_sync, run_daily_check_sync
from config import ADMIN_ID, WEBHOOK_SECRET

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    """
    Telegram har bir yangi update kelganda shu endpointga POST yuboradi.

    MUHIM: Telegram webhook javobini ~60 soniya kutadi. Agar javob kechiksa,
    u xuddi shu update'ni QAYTA yuboradi - natijada post ikki marta
    generatsiya qilinishi mumkin. Gemini chaqiruvi sekin bo'lgani uchun
    xatoni ushlab, baribir 200 qaytaramiz (Telegram qayta yubormasin).
    """
    update_data = request.get_json(force=True, silent=True)
    if not update_data:
        return "Bad Request", 400

    try:
        process_update_sync(update_data)
    except Exception:
        logger.exception("Update qayta ishlashda xatolik")
        # 200 qaytaramiz: aks holda Telegram bu update'ni qayta-qayta yuboradi.

    return "OK", 200


@app.route(f"/trigger-daily/{WEBHOOK_SECRET}", methods=["GET", "POST"])
def trigger_daily():
    """
    Tashqi cron-servis (masalan cron-job.org) shu endpointga muntazam
    (tavsiya: har 10-15 daqiqada) so'rov yuboradi.
    """
    try:
        run_daily_check_sync(ADMIN_ID)
    except Exception:
        logger.exception("Kunlik tekshiruvda xatolik")
        return "Error", 500

    return "OK", 200


@app.route("/", methods=["GET"])
def health_check():
    """Bot ishlab turganini tekshirish uchun oddiy endpoint."""
    return "Bot ishlayapti.", 200