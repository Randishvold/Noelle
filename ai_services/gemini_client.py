# Noelle_AI_Bot/ai_services/gemini_client.py
import os
import google.genai as genai
import logging

_logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation"
DESIGNATED_AI_CHANNEL_NAME = "ai-channel" # Nama channel AI yang ditetapkan

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

gemini_client: genai.Client | None = None
ai_service_enabled = True

def initialize_client():
    global gemini_client, ai_service_enabled
    if not GOOGLE_API_KEY:
        _logger.error("GEMINI_CLIENT: GOOGLE_API_KEY tidak diatur. Layanan AI tidak akan berfungsi.")
        ai_service_enabled = False
        gemini_client = None
        return
    try:
        gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("GEMINI_CLIENT: Klien Google GenAI berhasil diinisialisasi.")
        ai_service_enabled = True
        # Verifikasi model opsional
        try: gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME); _logger.info(f"GEMINI_CLIENT: Model '{GEMINI_TEXT_MODEL_NAME}' OK.")
        except Exception as e: _logger.warning(f"GEMINI_CLIENT: Gagal cek model '{GEMINI_TEXT_MODEL_NAME}': {e}")
        try: gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME); _logger.info(f"GEMINI_CLIENT: Model '{GEMINI_IMAGE_GEN_MODEL_NAME}' OK.")
        except Exception as e: _logger.warning(f"GEMINI_CLIENT: Gagal cek model '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}")
    except Exception as e:
        _logger.error(f"GEMINI_CLIENT: Error inisialisasi klien: {e}", exc_info=True)
        gemini_client = None
        ai_service_enabled = False

def get_gemini_client() -> genai.Client | None:
    return gemini_client

def is_ai_service_enabled() -> bool:
    return ai_service_enabled and gemini_client is not None

def get_designated_ai_channel_name() -> str:
    return DESIGNATED_AI_CHANNEL_NAME

def toggle_ai_service_status(status: bool) -> str: # Disederhanakan, tidak perlu referensi sesi dari sini
    """Mengubah status layanan AI."""
    global ai_service_enabled, gemini_client
    
    if status == ai_service_enabled:
        return f"Layanan AI sudah dalam status **{'aktif' if ai_service_enabled else 'nonaktif'}**."

    ai_service_enabled = status
    message = ""

    if ai_service_enabled:
        if gemini_client is None:
            initialize_client() 
        if gemini_client:
            _logger.info("GEMINI_CLIENT: Layanan AI diaktifkan.")
            message = "✅ Layanan AI Noelle telah **diaktifkan**."
        else:
            ai_service_enabled = False 
            _logger.error("GEMINI_CLIENT: Gagal aktifkan layanan AI, klien tidak terinisialisasi.")
            message = "⚠️ Gagal mengaktifkan layanan AI. Pastikan API Key benar."
    else:
        _logger.info("GEMINI_CLIENT: Layanan AI dinonaktifkan.")
        message = "🛑 Layanan AI Noelle telah **dinonaktifkan**."
    return message

initialize_client()