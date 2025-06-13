# Noelle_AI_Bot/ai_services/gemini_client.py

import os
import google.genai as genai
import logging
from google.api_core import exceptions as google_exceptions

_logger = logging.getLogger("noelle_bot.ai.gemini_client") # Nama logger yang lebih spesifik

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation" 
DESIGNATED_AI_CHANNEL_NAME = "ai-channel"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Status Layanan yang Lebih Detail ---
_gemini_client: genai.Client | None = None
_text_service_enabled = False
_image_service_enabled = False
# ----------------------------------------

def initialize_client():
    """Menginisialisasi klien Google GenAI dan memverifikasi ketersediaan model."""
    global _gemini_client, _text_service_enabled, _image_service_enabled
    
    if not GOOGLE_API_KEY:
        _logger.error("GOOGLE_API_KEY tidak diatur. Semua layanan AI dinonaktifkan.")
        _text_service_enabled = False
        _image_service_enabled = False
        _gemini_client = None
        return

    try:
        _logger.info("Mencoba inisialisasi klien Google GenAI...")
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")
    except Exception as e:
        _logger.critical(f"Gagal total inisialisasi klien Google GenAI: {e}", exc_info=True)
        _gemini_client = None
        _text_service_enabled = False
        _image_service_enabled = False
        return

    # Verifikasi model teks
    try:
        _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME)
        _logger.info(f"Model Teks '{GEMINI_TEXT_MODEL_NAME}' ditemukan dan siap digunakan.")
        _text_service_enabled = True
    except google_exceptions.NotFound:
        _logger.error(f"Model Teks '{GEMINI_TEXT_MODEL_NAME}' tidak ditemukan. Layanan teks AI dinonaktifkan.")
        _text_service_enabled = False
    except Exception as e:
        _logger.error(f"Error saat memeriksa model teks '{GEMINI_TEXT_MODEL_NAME}': {e}")
        _text_service_enabled = False

    # Verifikasi model gambar
    try:
        _gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME)
        _logger.info(f"Model Gambar '{GEMINI_IMAGE_GEN_MODEL_NAME}' ditemukan dan siap digunakan.")
        _image_service_enabled = True
    except google_exceptions.NotFound:
        # --- LOGIKA PENONAKTIFAN OTOMATIS ---
        _logger.warning(f"Model Gambar '{GEMINI_IMAGE_GEN_MODEL_NAME}' tidak ditemukan. Fitur generasi gambar akan dinonaktifkan.")
        _image_service_enabled = False
    except Exception as e:
        _logger.error(f"Error saat memeriksa model gambar '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}")
        _image_service_enabled = False

def get_gemini_client() -> genai.Client | None:
    """Mengembalikan instance klien GenAI jika tersedia."""
    return _gemini_client

def is_text_service_enabled() -> bool:
    """Cek apakah layanan teks (chat, mention) aktif."""
    return _text_service_enabled and _gemini_client is not None

def is_image_service_enabled() -> bool:
    """Cek apakah layanan generasi gambar aktif."""
    return _image_service_enabled and _gemini_client is not None

def get_designated_ai_channel_name() -> str:
    return DESIGNATED_AI_CHANNEL_NAME

# Panggil inisialisasi saat modul diimpor
initialize_client()