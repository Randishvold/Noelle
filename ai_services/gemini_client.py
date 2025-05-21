# Noelle_AI_Bot/ai_services/gemini_client.py
import os
import google.genai as genai
import logging

_logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Variabel global untuk klien dan status layanan
gemini_client: genai.Client | None = None
ai_service_enabled = True  # Defaultnya aktif

def initialize_client():
    """Menginisialisasi klien Gemini global."""
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
        # Verifikasi model (opsional)
        try:
            gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME)
            _logger.info(f"GEMINI_CLIENT: Model '{GEMINI_TEXT_MODEL_NAME}' dapat diakses.")
        except Exception as e:
            _logger.warning(f"GEMINI_CLIENT: Gagal cek model '{GEMINI_TEXT_MODEL_NAME}': {e}")
        try:
            gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME)
            _logger.info(f"GEMINI_CLIENT: Model '{GEMINI_IMAGE_GEN_MODEL_NAME}' dapat diakses.")
        except Exception as e:
            _logger.warning(f"GEMINI_CLIENT: Gagal cek model '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}")
            
    except Exception as e:
        _logger.error(f"GEMINI_CLIENT: Error inisialisasi klien: {e}", exc_info=True)
        gemini_client = None
        ai_service_enabled = False

def get_gemini_client() -> genai.Client | None:
    """Mengembalikan instance klien Gemini."""
    return gemini_client

def is_ai_service_enabled() -> bool:
    """Mengembalikan status layanan AI."""
    return ai_service_enabled and gemini_client is not None

def toggle_ai_service(status: bool, active_chat_sessions_ref: dict, chat_session_last_active_ref: dict, chat_context_token_counts_ref: dict):
    """Mengubah status layanan AI dan membersihkan sesi jika dinonaktifkan/diaktifkan."""
    global ai_service_enabled, gemini_client
    
    if status == ai_service_enabled: # Tidak ada perubahan
        return f"Layanan AI sudah dalam status **{'aktif' if ai_service_enabled else 'nonaktif'}**."

    ai_service_enabled = status
    message = ""

    if ai_service_enabled:
        if gemini_client is None:
            initialize_client() # Coba inisialisasi lagi jika sebelumnya gagal
        
        if gemini_client:
            # Bersihkan sesi saat diaktifkan kembali
            active_chat_sessions_ref.clear()
            chat_session_last_active_ref.clear()
            chat_context_token_counts_ref.clear()
            _logger.info("GEMINI_CLIENT: Layanan AI diaktifkan. Sesi chat dibersihkan.")
            message = "✅ Layanan AI Noelle telah **diaktifkan**. Sesi sebelumnya direset."
        else:
            ai_service_enabled = False # Gagal aktifkan
            _logger.error("GEMINI_CLIENT: Gagal aktifkan layanan AI, klien tidak terinisialisasi.")
            message = "⚠️ Gagal mengaktifkan layanan AI. Pastikan API Key benar."
    else:
        active_chat_sessions_ref.clear()
        chat_session_last_active_ref.clear()
        chat_context_token_counts_ref.clear()
        _logger.info("GEMINI_CLIENT: Layanan AI dinonaktifkan. Sesi chat dibersihkan.")
        message = "🛑 Layanan AI Noelle telah **dinonaktifkan**."
    return message

# Panggil inisialisasi saat modul diimpor
initialize_client()